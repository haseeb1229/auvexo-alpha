"""DS-04-A1 fixed database slots: CurrentUser DPAPI, fixed purpose and location.

No environment/config/command-line fallback or credential issuer. The same Windows user
can decrypt; local owner/admin compromise is outside the DPAPI identity guarantee.
The scheduled collector imports only the compatible writer loader. Explicit admin/app
owner APIs are in oi_owner_secrets, outside that collector import path.
"""

from __future__ import annotations

import ctypes
import hmac
import json
import os
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from enum import Enum
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

_PURPOSE = b"auvexo-alpha:phase6:ds04-a1:oi-db-password:v1"
_MAGIC = b"AUVEXO-OI-DPAPI-V1\x00"
_LIMIT = 8192
_ERROR = "OI_DATABASE_SECRET_UNAVAILABLE"


class OISecretUnavailable(ValueError):
    def __init__(self) -> None:
        super().__init__(_ERROR)


class _Slot(Enum):
    WRITER = "writer"
    ADMIN = "admin"
    APP = "app"

    @property
    def purpose(self) -> bytes:
        if self is _Slot.WRITER:
            # Preserve the reviewed writer entropy/envelope byte-for-byte.
            return _PURPOSE
        if self is _Slot.ADMIN:
            return b"auvexo-alpha:phase6:ds04-a1:oi-db-admin-password:v1"
        return b"auvexo-alpha:phase6:ds04-a1:oi-db-app-password:v1"

    @property
    def filename(self) -> str:
        if self is _Slot.WRITER:
            return "oi-db-password.v1.dpapi"
        if self is _Slot.ADMIN:
            return "oi-db-admin-password.v1.dpapi"
        return "oi-db-app-password.v1.dpapi"


def _fixed_slot(slot: _Slot) -> _Slot:
    if type(slot) is not _Slot:
        raise OISecretUnavailable() from None
    return slot


class _Crypto(Protocol):
    def protect(self, data: bytes) -> bytes: ...
    def unprotect(self, data: bytes) -> bytes: ...


class _Files(Protocol):
    def read(self) -> bytes: ...
    def write(self, data: bytes) -> None: ...
    def create(self, data: bytes) -> None: ...
    def delete(self) -> None: ...


def _valid_secret(value: object) -> str:
    if not isinstance(value, str) or not 32 <= len(value) <= 128:
        raise OISecretUnavailable()
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise OISecretUnavailable()
    return value


class _SecretStore:
    """Explicit dependency seam for tests; production always constructs native backends."""

    def __init__(self, files: _Files, crypto: _Crypto, slot: _Slot = _Slot.WRITER) -> None:
        self._files, self._crypto = files, crypto
        self._slot = _fixed_slot(slot)

    def store(self, value: object) -> None:
        self._save(value, create_only=False)

    def create(self, value: object) -> None:
        """Provisioning only: native atomic no-replace, separate from explicit rotation."""
        self._save(value, create_only=True)

    def _save(self, value: object, *, create_only: bool) -> None:
        try:
            secret = _valid_secret(value)
            plain = json.dumps(
                {"purpose": self._slot.purpose.decode("ascii"), "version": 1, "password": secret},
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
            encrypted = self._crypto.protect(plain)
            if not encrypted or len(encrypted) + len(_MAGIC) > _LIMIT:
                raise OISecretUnavailable()
            if create_only:
                self._files.create(_MAGIC + encrypted)
            else:
                self._files.write(_MAGIC + encrypted)
        except Exception:
            # Deliberate single redaction boundary: never propagate backend/path/plaintext details.
            raise OISecretUnavailable() from None

    def load(self) -> str:
        try:
            blob = self._files.read()
            if not len(_MAGIC) < len(blob) <= _LIMIT or not blob.startswith(_MAGIC):
                raise OISecretUnavailable()
            plain = self._crypto.unprotect(blob[len(_MAGIC) :])
            if len(plain) > 4096:
                raise OISecretUnavailable()

            def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
                result: dict[str, object] = {}
                for key, value in pairs:
                    if key in result:
                        raise OISecretUnavailable()
                    result[key] = value
                return result

            data = json.loads(plain, object_pairs_hook=unique)
            if (
                not isinstance(data, dict)
                or set(data) != {"purpose", "version", "password"}
                or type(data["version"]) is not int
                or data["version"] != 1
                or not isinstance(data["purpose"], str)
                or not hmac.compare_digest(data["purpose"], self._slot.purpose.decode("ascii"))
            ):
                raise OISecretUnavailable()
            return _valid_secret(data["password"])
        except Exception:
            raise OISecretUnavailable() from None

    def verify(self) -> bool:
        self.load()
        return True

    def delete(self) -> None:
        try:
            self._files.delete()
        except Exception:
            raise OISecretUnavailable() from None


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("a", wintypes.DWORD),
        ("b", wintypes.WORD),
        ("c", wintypes.WORD),
        ("d", ctypes.c_ubyte * 8),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.DWORD),
        ("descriptor", ctypes.c_void_p),
        ("inherit", wintypes.BOOL),
    ]


class _FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", wintypes.FILETIME),
        ("accessed", wintypes.FILETIME),
        ("written", wintypes.FILETIME),
        ("volume", wintypes.DWORD),
        ("high_size", wintypes.DWORD),
        ("low_size", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD),
        ("index_low", wintypes.DWORD),
    ]


class _RenameInfo(ctypes.Structure):
    _fields_ = [
        ("replace", wintypes.BOOL),
        ("root", wintypes.HANDLE),
        ("name_length", wintypes.DWORD),
        ("name", wintypes.WCHAR * 1),
    ]


class _WindowsAPI:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OISecretUnavailable()
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.crypt = ctypes.WinDLL("crypt32", use_last_error=True)
        self.shell = ctypes.WinDLL("shell32", use_last_error=True)
        self.ole = ctypes.WinDLL("ole32", use_last_error=True)
        self.kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.kernel.LocalFree.restype = ctypes.c_void_p
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(_SecurityAttributes),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CreateDirectoryW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.POINTER(_SecurityAttributes),
        ]
        self.kernel.CreateDirectoryW.restype = wintypes.BOOL
        self.kernel.GetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_FileInfo),
        ]
        self.kernel.GetFileInformationByHandle.restype = wintypes.BOOL
        self.kernel.GetFinalPathNameByHandleW.argtypes = [
            wintypes.HANDLE,
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.kernel.GetFinalPathNameByHandleW.restype = wintypes.DWORD
        self.kernel.SetFileInformationByHandle.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self.kernel.SetFileInformationByHandle.restype = wintypes.BOOL
        self.kernel.ReadFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self.kernel.ReadFile.restype = wintypes.BOOL
        self.kernel.WriteFile.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        self.kernel.WriteFile.restype = wintypes.BOOL
        self.kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
        self.kernel.FlushFileBuffers.restype = wintypes.BOOL
        self.advapi.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self.advapi.GetTokenInformation.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.advapi.ConvertSidToStringSidW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.advapi.GetSecurityInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self.advapi.GetSecurityInfo.restype = wintypes.DWORD
        self.advapi.SetKernelObjectSecurity.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self.advapi.SetKernelObjectSecurity.restype = wintypes.BOOL
        self.shell.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(_GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.LPWSTR),
        ]
        self.shell.SHGetKnownFolderPath.restype = ctypes.c_long
        self.ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        self.crypt.CryptProtectData.argtypes = [
            ctypes.POINTER(_Blob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_Blob),
        ]
        self.crypt.CryptProtectData.restype = wintypes.BOOL
        self.crypt.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_Blob),
            ctypes.c_void_p,
            ctypes.POINTER(_Blob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_Blob),
        ]
        self.crypt.CryptUnprotectData.restype = wintypes.BOOL

    def known_local_appdata(self) -> Path:
        identity = _GUID.from_buffer_copy(UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091").bytes_le)
        results = []
        for flags in (0, 0x400):
            output = wintypes.LPWSTR()
            if self.shell.SHGetKnownFolderPath(
                ctypes.byref(identity), flags, None, ctypes.byref(output)
            ):
                raise OISecretUnavailable()
            try:
                results.append(Path(output.value or ""))
            finally:
                self.ole.CoTaskMemFree(ctypes.cast(output, ctypes.c_void_p))
        if not results[0].is_absolute() or os.path.normcase(str(results[0])) != os.path.normcase(
            str(results[1])
        ):
            raise OISecretUnavailable()
        return results[0]

    def current_sid(self) -> str:
        token = wintypes.HANDLE()
        if not self.advapi.OpenProcessToken(
            self.kernel.GetCurrentProcess(), 8, ctypes.byref(token)
        ):
            raise OISecretUnavailable()
        try:
            needed = wintypes.DWORD()
            self.advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
            if not 0 < needed.value <= 65536:
                raise OISecretUnavailable()
            buffer = ctypes.create_string_buffer(needed.value)
            if not self.advapi.GetTokenInformation(token, 1, buffer, needed, ctypes.byref(needed)):
                raise OISecretUnavailable()
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
            return self.sid_text(sid)
        finally:
            self.kernel.CloseHandle(token)

    def sid_text(self, sid: object) -> str:
        text = wintypes.LPWSTR()
        if not self.advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise OISecretUnavailable()
        try:
            return text.value or ""
        finally:
            self.kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))

    @contextmanager
    def descriptor(self, sid: str) -> Iterator[ctypes.c_void_p]:
        descriptor = ctypes.c_void_p()
        sddl = f"O:{sid}D:P(A;OICI;FA;;;{sid})(A;OICI;FA;;;SY)"
        if not self.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        ):
            raise OISecretUnavailable()
        try:
            yield descriptor
        finally:
            self.kernel.LocalFree(descriptor)


class _DPAPI:
    def __init__(self, slot: _Slot = _Slot.WRITER) -> None:
        self._slot = _fixed_slot(slot)
        self.api = _WindowsAPI()

    def _transform(self, data: bytes, decrypt: bool) -> bytes:
        if not 0 < len(data) <= _LIMIT:
            raise OISecretUnavailable()
        source_buffer = ctypes.create_string_buffer(data)
        purpose = self._slot.purpose
        entropy_buffer = ctypes.create_string_buffer(purpose)
        source = _Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        entropy = _Blob(len(purpose), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = _Blob()
        try:
            if decrypt:
                ok = self.api.crypt.CryptUnprotectData(
                    ctypes.byref(source),
                    None,
                    ctypes.byref(entropy),
                    None,
                    None,
                    1,
                    ctypes.byref(output),
                )
            else:
                ok = self.api.crypt.CryptProtectData(
                    ctypes.byref(source),
                    purpose.decode("ascii"),
                    ctypes.byref(entropy),
                    None,
                    None,
                    1,
                    ctypes.byref(output),
                )
            if not ok or not 0 < output.size <= _LIMIT:
                raise OISecretUnavailable()
            return ctypes.string_at(output.data, output.size)
        finally:
            ctypes.memset(source_buffer, 0, ctypes.sizeof(source_buffer))
            ctypes.memset(entropy_buffer, 0, ctypes.sizeof(entropy_buffer))
            if output.data:
                ctypes.memset(output.data, 0, output.size)
                self.api.kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))

    def protect(self, data: bytes) -> bytes:
        return self._transform(data, False)

    def unprotect(self, data: bytes) -> bytes:
        return self._transform(data, True)


class _WindowsFiles:
    def __init__(self, test_id: UUID | None = None, *, slot: _Slot = _Slot.WRITER) -> None:
        slot = _fixed_slot(slot)
        self.api = _WindowsAPI()
        self.base = self.api.known_local_appdata()
        self.sid = self.api.current_sid()
        parent = self.base / "AuvexoAlpha" / "phase6"
        if test_id is not None:
            if not isinstance(test_id, UUID):
                raise OISecretUnavailable()
            parent = parent / ("test-" + str(test_id))
        self.path = parent / slot.filename

    def _open(
        self, path: Path, access: int, creation: int = 3, descriptor: ctypes.c_void_p | None = None
    ) -> int:
        attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
        handle = self.api.kernel.CreateFileW(
            str(path),
            access,
            3 if path != self.path and creation == 3 else 0,
            ctypes.byref(attributes) if descriptor is not None else None,
            creation,
            0x00200000 | 0x02000000,
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            raise OISecretUnavailable()
        return int(handle)

    def _check(self, handle: int, path: Path, *, directory: bool) -> None:
        info = _FileInfo()
        if not self.api.kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise OISecretUnavailable()
        if bool(info.attributes & 0x10) != directory or info.attributes & 0x400:
            raise OISecretUnavailable()
        if not directory and (info.links != 1 or info.high_size or info.low_size > _LIMIT):
            raise OISecretUnavailable()
        final = ctypes.create_unicode_buffer(32768)
        count = self.api.kernel.GetFinalPathNameByHandleW(handle, final, len(final), 0)
        if not 0 < count < len(final):
            raise OISecretUnavailable()
        actual = final.value
        if actual.startswith("\\\\?\\"):
            actual = actual[4:]
        if os.path.normcase(os.path.normpath(actual)) != os.path.normcase(
            os.path.normpath(str(path))
        ):
            raise OISecretUnavailable()

    def _check_owner(self, handle: int) -> None:
        owner, security = ctypes.c_void_p(), ctypes.c_void_p()
        result = self.api.advapi.GetSecurityInfo(
            handle, 1, 1, ctypes.byref(owner), None, None, None, ctypes.byref(security)
        )
        try:
            if result or self.api.sid_text(owner) != self.sid:
                raise OISecretUnavailable()
        finally:
            if security:
                self.api.kernel.LocalFree(security)

    def _restrict_owner(self, handle: int, descriptor: ctypes.c_void_p) -> None:
        self._check_owner(handle)
        if not self.api.advapi.SetKernelObjectSecurity(handle, 1 | 4 | 0x80000000, descriptor):
            raise OISecretUnavailable()

    @contextmanager
    def _parent(self, create: bool, *, absent_check: bool = False) -> Iterator[ctypes.c_void_p]:
        handles: list[int] = []
        with self.api.descriptor(self.sid) as descriptor:
            try:
                for path in reversed((self.path.parent, *self.path.parent.parents)):
                    scoped = path.is_relative_to(self.base) and path != self.base
                    try:
                        path.lstat()
                        exists = True
                    except FileNotFoundError:
                        exists = False
                    if not exists:
                        if absent_check and scoped:
                            # Only scoped missing ancestors mean an absent slot. Existing
                            # ancestors stay opened and checked without following reparses.
                            yield descriptor
                            return
                        if not create or not scoped:
                            raise OISecretUnavailable()
                        attributes = _SecurityAttributes(
                            ctypes.sizeof(_SecurityAttributes), descriptor, False
                        )
                        if not self.api.kernel.CreateDirectoryW(
                            str(path), ctypes.byref(attributes)
                        ):
                            raise OISecretUnavailable()
                    access = 0x80 | (0x20000 | 0x40000 | 0x80000 if scoped else 0)
                    handle = self._open(path, access)
                    handles.append(handle)
                    self._check(handle, path, directory=True)
                    if scoped and absent_check:
                        self._check_owner(handle)
                    elif scoped:
                        self._restrict_owner(handle, descriptor)
                yield descriptor
            finally:
                for handle in reversed(handles):
                    self.api.kernel.CloseHandle(handle)

    def require_absent(self) -> None:
        """Read-only preflight, not a lease or permission to overwrite an existing slot."""
        try:
            with self._parent(False, absent_check=True):
                try:
                    self.path.lstat()
                except FileNotFoundError:
                    return
                raise OISecretUnavailable()
        except Exception:
            raise OISecretUnavailable() from None

    def _target(
        self,
        descriptor: ctypes.c_void_p,
        *,
        missing_ok: bool = False,
        restrict_owner: bool = True,
    ) -> int | None:
        try:
            handle = self._open(self.path, 0x80000000 | 0x10000 | 0x20000 | 0x40000 | 0x80000)
        except OISecretUnavailable:
            if missing_ok and ctypes.get_last_error() in (2, 3):
                return None
            raise
        try:
            self._check(handle, self.path, directory=False)
            if restrict_owner:
                self._restrict_owner(handle, descriptor)
            else:
                self._check_owner(handle)
            return handle
        except Exception:
            self.api.kernel.CloseHandle(handle)
            raise

    def read(self) -> bytes:
        with self._parent(False) as descriptor:
            handle = self._target(descriptor)
            if handle is None:
                raise OISecretUnavailable()
            try:
                buffer = ctypes.create_string_buffer(_LIMIT + 1)
                count = wintypes.DWORD()
                if not self.api.kernel.ReadFile(
                    handle, buffer, len(buffer), ctypes.byref(count), None
                ):
                    raise OISecretUnavailable()
                if not 0 < count.value <= _LIMIT:
                    raise OISecretUnavailable()
                return buffer.raw[: count.value]
            finally:
                self.api.kernel.CloseHandle(handle)

    def write(self, data: bytes) -> None:
        self._write(data, replace=True)

    def create(self, data: bytes) -> None:
        self._write(data, replace=False)

    def _write(self, data: bytes, *, replace: bool) -> None:
        if not 0 < len(data) <= _LIMIT:
            raise OISecretUnavailable()
        with self._parent(True) as descriptor:
            existing = self._target(descriptor, missing_ok=True, restrict_owner=replace)
            if existing is not None:
                self.api.kernel.CloseHandle(existing)
                if not replace:
                    raise OISecretUnavailable()
            stage = self.path.parent / (".oi-secret-" + uuid4().hex + ".stage")
            handle = self._open(
                stage,
                0x80000000 | 0x40000000 | 0x10000 | 0x20000 | 0x40000 | 0x80000,
                1,
                descriptor,
            )
            moved = False
            try:
                self._check(handle, stage, directory=False)
                self._restrict_owner(handle, descriptor)
                count = wintypes.DWORD()
                buffer = ctypes.create_string_buffer(data)
                if not self.api.kernel.WriteFile(
                    handle, buffer, len(data), ctypes.byref(count), None
                ) or count.value != len(data):
                    raise OISecretUnavailable()
                if not self.api.kernel.FlushFileBuffers(handle):
                    raise OISecretUnavailable()
                name = str(self.path).encode("utf-16-le")
                # Include native structure tail padding and an explicit UTF-16 NUL.
                size = ctypes.sizeof(_RenameInfo) + len(name) + 2
                rename_buffer = ctypes.create_string_buffer(size)
                rename = _RenameInfo.from_buffer(rename_buffer)
                rename.replace, rename.root, rename.name_length = replace, None, len(name)
                ctypes.memmove(
                    ctypes.addressof(rename_buffer) + _RenameInfo.name.offset, name, len(name)
                )
                if not self.api.kernel.SetFileInformationByHandle(handle, 3, rename_buffer, size):
                    raise OISecretUnavailable()
                moved = True
                self._check(handle, self.path, directory=False)
            finally:
                if not moved:
                    delete = wintypes.BOOL(True)
                    self.api.kernel.SetFileInformationByHandle(
                        handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)
                    )
                self.api.kernel.CloseHandle(handle)

    def delete(self) -> None:
        with self._parent(False) as descriptor:
            handle = self._target(descriptor)
            if handle is None:
                raise OISecretUnavailable()
            try:
                delete = wintypes.BOOL(True)
                if not self.api.kernel.SetFileInformationByHandle(
                    handle, 4, ctypes.byref(delete), ctypes.sizeof(delete)
                ):
                    raise OISecretUnavailable()
            finally:
                self.api.kernel.CloseHandle(handle)


def _production_store() -> _SecretStore:
    return _SecretStore(_WindowsFiles(), _DPAPI())


def _owner_store(slot: _Slot) -> _SecretStore:
    slot = _fixed_slot(slot)
    if slot is _Slot.WRITER:
        raise OISecretUnavailable()
    return _SecretStore(_WindowsFiles(slot=slot), _DPAPI(slot), slot)


def _test_store(test_id: UUID, slot: _Slot) -> _SecretStore:
    if not isinstance(test_id, UUID):
        raise OISecretUnavailable()
    slot = _fixed_slot(slot)
    return _SecretStore(_WindowsFiles(test_id, slot=slot), _DPAPI(slot), slot)


def make_test_oi_secret_store(test_id: UUID) -> _SecretStore:
    """Explicit disposable native-test UUID leaf; never changes the production path rule."""
    try:
        return _test_store(test_id, _Slot.WRITER)
    except Exception:
        raise OISecretUnavailable() from None


def load_oi_database_password() -> str:
    try:
        return _production_store().load()
    except Exception:
        raise OISecretUnavailable() from None


def store_oi_database_password(secret: object) -> None:
    try:
        _production_store().store(secret)
    except Exception:
        raise OISecretUnavailable() from None


def verify_oi_database_password() -> bool:
    try:
        return _production_store().verify()
    except Exception:
        raise OISecretUnavailable() from None


def delete_oi_database_password() -> None:
    try:
        _production_store().delete()
    except Exception:
        raise OISecretUnavailable() from None
