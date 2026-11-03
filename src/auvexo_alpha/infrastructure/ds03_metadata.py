"""Fixed encrypted account metadata; admission precedes native access, no secret in JSON."""

from __future__ import annotations

import hmac
import json
from datetime import datetime
from uuid import UUID

from auvexo_alpha.domain.ds03_authority import (
    Ds03AuthorityAdmission,
    Ds03LocalMetadata,
    Ds03OnboardingAdmission,
    decode_metadata,
)
from auvexo_alpha.infrastructure.ds03_secrets import (
    _DS03DPAPI,
    _DS03WindowsFiles,
)
from auvexo_alpha.infrastructure.oi_secrets import _Crypto, _Files

_PURPOSE = b"auvexo-alpha:phase2:ds03:mt5-demo-account-metadata:v1"
_MAGIC = b"AUVEXO-DS03-METADATA-DPAPI-V1\x00"
_FILENAME = "mt5-demo-account.v1.dpapi"
_LIMIT = 8192


class Ds03MetadataUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("DS03_METADATA_UNAVAILABLE")


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise Ds03MetadataUnavailable()
        result[key] = value
    return result


class _MetadataStore:
    """Same bounded encrypted envelope/native mechanics for production and UUID tests."""

    def __init__(self, files: _Files, crypto: _Crypto) -> None:
        self._files, self._crypto = files, crypto

    def _save(self, metadata: Ds03LocalMetadata, *, create: bool) -> None:
        try:
            if type(metadata) is not Ds03LocalMetadata:
                raise Ds03MetadataUnavailable()
            checked = decode_metadata(metadata.canonical_bytes())
            plain = json.dumps(
                {"purpose": _PURPOSE.decode(), "version": 1, "metadata": checked.model_dump()},
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            if len(plain) > 4096:
                raise Ds03MetadataUnavailable()
            encrypted = self._crypto.protect(plain)
            if not encrypted or len(encrypted) + len(_MAGIC) > _LIMIT:
                raise Ds03MetadataUnavailable()
            if create:
                self._files.create(_MAGIC + encrypted)
            else:
                self._files.write(_MAGIC + encrypted)
        except Exception:
            raise Ds03MetadataUnavailable() from None

    def create(self, metadata: Ds03LocalMetadata) -> None:
        self._save(metadata, create=True)

    def rotate(self, metadata: Ds03LocalMetadata) -> None:
        try:
            previous = self.load()
            if (
                previous.login_digest != metadata.login_digest
                or previous.server_digest != metadata.server_digest
            ):
                raise Ds03MetadataUnavailable()
            self._save(metadata, create=False)
        except Exception:
            raise Ds03MetadataUnavailable() from None

    def load(self) -> Ds03LocalMetadata:
        try:
            blob = self._files.read()
            if not len(_MAGIC) < len(blob) <= _LIMIT or not blob.startswith(_MAGIC):
                raise Ds03MetadataUnavailable()
            plain = self._crypto.unprotect(blob[len(_MAGIC) :])
            if len(plain) > 4096:
                raise Ds03MetadataUnavailable()
            data = json.loads(plain, object_pairs_hook=_unique)
            if (
                type(data) is not dict
                or set(data) != {"purpose", "version", "metadata"}
                or type(data["version"]) is not int
                or data["version"] != 1
                or type(data["purpose"]) is not str
                or not hmac.compare_digest(data["purpose"], _PURPOSE.decode())
            ):
                raise Ds03MetadataUnavailable()
            return decode_metadata(json.dumps(data["metadata"], allow_nan=False).encode())
        except Exception:
            raise Ds03MetadataUnavailable() from None

    def delete(self) -> None:
        try:
            self._files.delete()
        except Exception:
            raise Ds03MetadataUnavailable() from None


class _MetadataDPAPI(_DS03DPAPI):
    def _purpose(self) -> bytes:
        return _PURPOSE


class _MetadataWindowsFiles(_DS03WindowsFiles):
    def __init__(self, test_id: UUID | None = None) -> None:
        super().__init__(test_id)
        self.path = self.path.with_name(_FILENAME)


def make_test_ds03_metadata_store(test_id: UUID) -> _MetadataStore:
    """UUID mandatory; identical production classes, fixed disposable leaf only."""
    try:
        if type(test_id) is not UUID:
            raise Ds03MetadataUnavailable()
        return _MetadataStore(_MetadataWindowsFiles(test_id), _MetadataDPAPI())
    except Exception:
        raise Ds03MetadataUnavailable() from None


def _require_authority(
    admission: Ds03AuthorityAdmission | None, now: datetime | None
) -> Ds03AuthorityAdmission:
    try:
        if type(admission) not in (Ds03AuthorityAdmission, Ds03OnboardingAdmission):
            raise Ds03MetadataUnavailable()
        if admission is None or not isinstance(now, datetime):
            raise Ds03MetadataUnavailable()
        admission.verify(now)
        from auvexo_alpha.infrastructure.ds03_mt5_binding import verify_runtime_binding

        verify_runtime_binding(admission.binding)
        return admission
    except Exception:
        raise Ds03MetadataUnavailable() from None


def _require_full(
    admission: Ds03OnboardingAdmission | None, now: datetime | None
) -> Ds03OnboardingAdmission:
    try:
        if type(admission) is not Ds03OnboardingAdmission:
            raise Ds03MetadataUnavailable()
        _require_authority(admission, now)
        return admission
    except Exception:
        raise Ds03MetadataUnavailable() from None


def _production_store() -> _MetadataStore:
    return _MetadataStore(_MetadataWindowsFiles(), _MetadataDPAPI())


def require_ds03_account_metadata_absent(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        _require_authority(admission, now)
        _MetadataWindowsFiles().require_absent()
    except Exception:
        raise Ds03MetadataUnavailable() from None


def create_ds03_account_metadata(
    admission: Ds03OnboardingAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        checked = _require_full(admission, now)
        _production_store().create(checked.metadata)
    except Exception:
        raise Ds03MetadataUnavailable() from None


def load_ds03_account_metadata(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> Ds03LocalMetadata:
    try:
        checked = _require_authority(admission, now)
        metadata = _production_store().load()
        checked.require_metadata(metadata)
        return metadata
    except Exception:
        raise Ds03MetadataUnavailable() from None


def verify_ds03_account_metadata(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> bool:
    load_ds03_account_metadata(admission, now=now)
    return True


def rotate_ds03_account_metadata(
    admission: Ds03OnboardingAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        checked = _require_full(admission, now)
        _production_store().rotate(checked.metadata)
    except Exception:
        raise Ds03MetadataUnavailable() from None


def delete_ds03_account_metadata(
    admission: Ds03AuthorityAdmission | None = None, *, now: datetime | None = None
) -> None:
    try:
        checked = _require_authority(admission, now)
        store = _production_store()
        checked.require_metadata(store.load())
        store.delete()
    except Exception:
        raise Ds03MetadataUnavailable() from None
