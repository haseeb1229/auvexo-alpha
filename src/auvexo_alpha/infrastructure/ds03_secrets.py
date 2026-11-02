"""Fixed DS-03 synthetic secret proofs; actual onboarding operations remain inert.

Only disposable UUID leaves are available to native tests. There is no production
secret selector, enable flag, environment fallback, CLI or general credential API.
"""

from __future__ import annotations

import hmac
import json
import string
from typing import Never
from uuid import UUID

from auvexo_alpha.infrastructure.oi_secrets import _DPAPI, _Crypto, _Files, _WindowsAPI
from auvexo_alpha.infrastructure.oi_secrets import _WindowsFiles as _OIWindowsFiles

_PURPOSE = b"auvexo-alpha:phase2:ds03:mt5-demo-readonly-password:v1"
_MAGIC = b"AUVEXO-DS03-DPAPI-V1\x00"
_LIMIT = 8192
_FILENAME = "mt5-demo-readonly.v1.dpapi"


class Ds03SecretUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__("DS03_SECRET_UNAVAILABLE")


def _valid_secret(value: object) -> str:
    if (
        type(value) is not str
        or not 8 <= len(value) <= 15
        or any(not 33 <= ord(character) <= 126 for character in value)
        or not any(character in string.ascii_uppercase for character in value)
        or not any(character in string.ascii_lowercase for character in value)
        or not any(character in string.digits for character in value)
        or not any(character in string.punctuation for character in value)
    ):
        raise Ds03SecretUnavailable()
    return value


class _SecretStore:
    """Synthetic dependency seam; public production operations cannot construct it."""

    def __init__(self, files: _Files, crypto: _Crypto) -> None:
        self._files, self._crypto = files, crypto

    def _save(self, value: object, *, create: bool) -> None:
        try:
            secret = _valid_secret(value)
            plain = json.dumps(
                {"purpose": _PURPOSE.decode("ascii"), "version": 1, "password": secret},
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            encrypted = self._crypto.protect(plain)
            if not encrypted or len(encrypted) + len(_MAGIC) > _LIMIT:
                raise Ds03SecretUnavailable()
            if create:
                self._files.create(_MAGIC + encrypted)
            else:
                self._files.write(_MAGIC + encrypted)
        except Exception:
            # Intentional redaction boundary: no native/path/plaintext details escape.
            raise Ds03SecretUnavailable() from None

    def create(self, value: object) -> None:
        self._save(value, create=True)

    def rotate(self, value: object) -> None:
        self.load()
        self._save(value, create=False)

    def load(self) -> str:
        try:
            blob = self._files.read()
            if not len(_MAGIC) < len(blob) <= _LIMIT or not blob.startswith(_MAGIC):
                raise Ds03SecretUnavailable()
            plain = self._crypto.unprotect(blob[len(_MAGIC) :])
            if len(plain) > 4096:
                raise Ds03SecretUnavailable()

            def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, value in pairs:
                    if key in result:
                        raise Ds03SecretUnavailable()
                    result[key] = value
                return result

            data = json.loads(plain, object_pairs_hook=unique)
            if (
                not isinstance(data, dict)
                or set(data) != {"purpose", "version", "password"}
                or type(data["version"]) is not int
                or data["version"] != 1
                or not isinstance(data["purpose"], str)
                or not hmac.compare_digest(data["purpose"], _PURPOSE.decode("ascii"))
            ):
                raise Ds03SecretUnavailable()
            return _valid_secret(data["password"])
        except Exception:
            raise Ds03SecretUnavailable() from None

    def verify(self) -> bool:
        self.load()
        return True

    def delete(self) -> None:
        try:
            self._files.delete()
        except Exception:
            raise Ds03SecretUnavailable() from None


class _DS03DPAPI(_DPAPI):
    def __init__(self) -> None:
        # Native API only: never select or initialize an OI credential slot.
        self.api = _WindowsAPI()

    def _purpose(self) -> bytes:
        return _PURPOSE


class _DS03WindowsFiles(_OIWindowsFiles):
    def __init__(self, test_id: UUID) -> None:
        if type(test_id) is not UUID:
            raise Ds03SecretUnavailable()
        self.api = _WindowsAPI()
        self.base = self.api.known_local_appdata()
        self.sid = self.api.current_sid()
        self.path = (
            self.base / "AuvexoAlpha" / "phase2" / "ds03" / ("test-" + str(test_id)) / _FILENAME
        )


def make_test_ds03_secret_store(test_id: UUID) -> _SecretStore:
    """Native synthetic proof only; UUID mandatory, no production path selector."""
    try:
        if type(test_id) is not UUID:
            raise Ds03SecretUnavailable()
        return _SecretStore(_DS03WindowsFiles(test_id), _DS03DPAPI())
    except Exception:
        raise Ds03SecretUnavailable() from None


def _onboarding_not_accepted() -> Never:
    # PRIVATE return plus independent actual-onboarding acceptance must precede a
    # separately reviewed implementation. No caller-controlled switch bypasses it.
    raise Ds03SecretUnavailable() from None


def create_ds03_readonly_password(secret: object) -> None:
    _onboarding_not_accepted()


def rotate_ds03_readonly_password(secret: object) -> None:
    _onboarding_not_accepted()


def load_ds03_readonly_password() -> str:
    _onboarding_not_accepted()


def verify_ds03_readonly_password() -> bool:
    _onboarding_not_accepted()


def delete_ds03_readonly_password() -> None:
    _onboarding_not_accepted()
