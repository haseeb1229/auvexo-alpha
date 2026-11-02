"""Explicit owner-only admin/app DPAPI slots; never imported by the OI collector.

No caller-selectable purpose, location or scope. Writer operations keep their reviewed
API in oi_secrets. Only disposable UUID factories select a separate native test leaf.
"""

from uuid import UUID

from auvexo_alpha.infrastructure.oi_secrets import (
    OISecretUnavailable,
    _owner_store,
    _production_store,
    _SecretStore,
    _Slot,
    _test_store,
    _WindowsFiles,
)


def require_oi_database_credentials_absent() -> None:
    """Future provisioner preflight only; no decrypt, creation, overwrite or recovery.

    Caller must hold its exclusive provisioning lock, use the named atomic create
    APIs below, and retain recovery-required state if persistence partially fails.
    This check is not an atomic lease.
    """
    try:
        for slot in (_Slot.ADMIN, _Slot.APP, _Slot.WRITER):
            _WindowsFiles(slot=slot).require_absent()
    except Exception:
        raise OISecretUnavailable() from None


def create_oi_database_admin_password(secret: object) -> None:
    try:
        _owner_store(_Slot.ADMIN).create(secret)
    except Exception:
        raise OISecretUnavailable() from None


def create_oi_database_app_password(secret: object) -> None:
    try:
        _owner_store(_Slot.APP).create(secret)
    except Exception:
        raise OISecretUnavailable() from None


def create_oi_database_writer_password(secret: object) -> None:
    try:
        _production_store().create(secret)
    except Exception:
        raise OISecretUnavailable() from None


def store_oi_database_admin_password(secret: object) -> None:
    try:
        _owner_store(_Slot.ADMIN).store(secret)
    except Exception:
        raise OISecretUnavailable() from None


def load_oi_database_admin_password() -> str:
    try:
        return _owner_store(_Slot.ADMIN).load()
    except Exception:
        raise OISecretUnavailable() from None


def verify_oi_database_admin_password() -> bool:
    try:
        return _owner_store(_Slot.ADMIN).verify()
    except Exception:
        raise OISecretUnavailable() from None


def delete_oi_database_admin_password() -> None:
    try:
        _owner_store(_Slot.ADMIN).delete()
    except Exception:
        raise OISecretUnavailable() from None


def store_oi_database_app_password(secret: object) -> None:
    try:
        _owner_store(_Slot.APP).store(secret)
    except Exception:
        raise OISecretUnavailable() from None


def load_oi_database_app_password() -> str:
    try:
        return _owner_store(_Slot.APP).load()
    except Exception:
        raise OISecretUnavailable() from None


def verify_oi_database_app_password() -> bool:
    try:
        return _owner_store(_Slot.APP).verify()
    except Exception:
        raise OISecretUnavailable() from None


def delete_oi_database_app_password() -> None:
    try:
        _owner_store(_Slot.APP).delete()
    except Exception:
        raise OISecretUnavailable() from None


def make_test_oi_admin_secret_store(test_id: UUID) -> _SecretStore:
    try:
        return _test_store(test_id, _Slot.ADMIN)
    except Exception:
        raise OISecretUnavailable() from None


def make_test_oi_app_secret_store(test_id: UUID) -> _SecretStore:
    try:
        return _test_store(test_id, _Slot.APP)
    except Exception:
        raise OISecretUnavailable() from None
