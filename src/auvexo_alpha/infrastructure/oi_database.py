"""Future owner-only OI PostgreSQL lifecycle; never grants collection or START.

Production has one target. The private disposable test factory has only UUID temp
roots, UUID database names and nonproduction ports, and is not exposed by the CLI.
All passwords remain in memory until fixed CurrentUser DPAPI persistence.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from sqlalchemy import URL, create_engine, text
from sqlalchemy.pool import NullPool

from auvexo_alpha.domain.oi_rights_review import OIReviewAuthority
from auvexo_alpha.infrastructure.oi_migrations import (
    OI_ADMIN,
    OI_DATABASE,
    OI_PORT,
    migrate_oi_database,
)

_ERROR = "OI_DATABASE_RECOVERY_REQUIRED"
_ROLES = ("auvexo_app", "auvexo_data_writer")
_VERSION = "17.11"
_REVISION = "0005_paper_core"
_CONFIGURATION = ("postgresql.conf", "postgresql.auto.conf", "pg_hba.conf", "pg_ident.conf")


class OIDatabaseUnavailable(ValueError):
    def __init__(self, *, cleanup_verified: bool = False) -> None:
        super().__init__(_ERROR)
        self.cleanup_verified = cleanup_verified


@dataclass(frozen=True, repr=False)
class _Passwords:
    admin: str
    app: str
    writer: str

    @classmethod
    def generate(cls) -> _Passwords:
        values = [secrets.token_urlsafe(48) for _ in range(3)]
        if len(set(values)) != 3:
            raise OIDatabaseUnavailable()
        return cls(*values)


class _Slots(Protocol):
    def require_absent(self) -> None: ...
    def store(self, passwords: _Passwords) -> None: ...
    def load(self) -> _Passwords: ...
    def load_admin(self) -> str: ...


class _Process(Protocol):
    pid: int

    def create_time(self) -> float: ...
    def exe(self) -> str: ...
    def children(self, recursive: bool) -> list[_Process]: ...
    def kill(self) -> None: ...
    def wait(self, timeout: float) -> int | None: ...


class _Processes(Protocol):
    def Process(self, pid: int) -> _Process: ...


class _WindowsSlots:
    def require_absent(self) -> None:
        from auvexo_alpha.infrastructure.oi_owner_secrets import (
            require_oi_database_credentials_absent,
        )

        require_oi_database_credentials_absent()

    def store(self, passwords: _Passwords) -> None:
        from auvexo_alpha.infrastructure.oi_owner_secrets import (
            create_oi_database_admin_password,
            create_oi_database_app_password,
            create_oi_database_writer_password,
        )

        # Any partial failure requires owner recovery; never erase or recreate slots.
        create_oi_database_admin_password(passwords.admin)
        create_oi_database_app_password(passwords.app)
        create_oi_database_writer_password(passwords.writer)

    def load(self) -> _Passwords:
        from auvexo_alpha.infrastructure.oi_owner_secrets import (
            load_oi_database_admin_password,
            load_oi_database_app_password,
        )
        from auvexo_alpha.infrastructure.oi_secrets import load_oi_database_password

        return _Passwords(
            load_oi_database_admin_password(),
            load_oi_database_app_password(),
            load_oi_database_password(),
        )

    def load_admin(self) -> str:
        from auvexo_alpha.infrastructure.oi_owner_secrets import load_oi_database_admin_password

        return load_oi_database_admin_password()


def _safe_path(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise OIDatabaseUnavailable()
    for item in (path, *path.parents):
        if not item.exists() and not item.is_symlink():
            continue
        info = item.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)
        ):
            raise OIDatabaseUnavailable()


def _native_environment() -> dict[str, str]:
    # No inherited libpq settings, DSNs, service files or password fallbacks.
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "TEMP",
        "TMP",
        "COMSPEC",
        "PATH",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
    }
    return {key: value for key, value in os.environ.items() if key.upper() in allowed}


def _run(executable: Path, arguments: list[str], *, password: str | None = None) -> bytes:
    """Suppress native output at the redaction boundary; never expose CalledProcessError."""
    _safe_path(executable)
    environment = _native_environment()
    if password is not None and os.name == "nt":
        # PG17.11 sprompt.c explicitly selects stdin/stderr for this terminal mode.
        # initdb's restricted-token re-exec can otherwise open a fresh CONIN$ even
        # under CREATE_NO_WINDOW. This nonsecret child-only setting changes no OS policy.
        environment["OSTYPE"] = "msys"
    if password is not None and any(
        password in item for item in [str(executable), *arguments, *environment.values()]
    ):
        raise OIDatabaseUnavailable()
    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = _supervised_run(
            [str(executable), *arguments],
            input=(password + "\n" + password + "\n").encode("ascii") if password else None,
            capture_output=True,
            env=environment,
            creationflags=creationflags,
            timeout=90,
            check=False,
        )
        if result.returncode or (
            password is not None and password.encode("ascii") in result.stdout + result.stderr
        ):
            raise OIDatabaseUnavailable()
        return result.stdout
    except Exception:
        raise OIDatabaseUnavailable() from None


def _supervised_run(
    argv: list[str],
    *,
    input: bytes | None,
    capture_output: bool,
    env: dict[str, str],
    creationflags: int,
    timeout: int,
    check: bool,
) -> subprocess.CompletedProcess[bytes]:
    """Bounded memory-only pipes; terminate only this invocation's proven PG tree.

    subprocess.run's Windows timeout path can wait forever on inherited descendant
    pipes. Snapshot descendant identities before terminating the owned parent.
    Unknown/inaccessible descendants require recovery rather than broad process kills.
    """
    if not capture_output or check:
        raise OIDatabaseUnavailable()
    processes = cast(_Processes, importlib.import_module("psutil"))
    # pg_ctl's detached server can inherit otherwise-unused pipe handles on Windows.
    # It never receives a password; lifecycle output is suppressed, and actual server
    # identity/return code are independently checked. initdb output stays memory-only.
    quiet = Path(argv[0]).stem.casefold() == "pg_ctl" and "--version" not in argv
    process = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
        stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
        env=env,
        creationflags=creationflags,
    )
    try:
        created_process = processes.Process(process.pid)
        owner_started = created_process.create_time()
        owned: _Process | None = created_process
    except Exception:
        owned = None  # A completed short version query may already have exited.
        owner_started = None
    try:
        output, error = process.communicate(input=input, timeout=timeout)
        return subprocess.CompletedProcess(argv, process.returncode, output or b"", error or b"")
    except (Exception, KeyboardInterrupt):
        descendants: list[tuple[_Process, float, Path]] = []
        cleanup_errors = 0
        try:
            if (
                owned is not None
                and owned.create_time() == owner_started
                and Path(owned.exe()).resolve() == Path(argv[0]).resolve()
            ):
                for child in owned.children(recursive=True):
                    executable = Path(child.exe()).resolve()
                    if executable.parent == Path(
                        argv[0]
                    ).resolve().parent and executable.name.casefold() in {
                        "initdb.exe",
                        "postgres.exe",
                        "pg_ctl.exe",
                        "initdb",
                        "postgres",
                        "pg_ctl",
                    }:
                        descendants.append((child, child.create_time(), executable))
                    else:
                        cleanup_errors += 1
            else:
                cleanup_errors += 1
        except Exception:
            cleanup_errors += 1
        # Inspection failure never prevents killing the exact Popen-owned parent handle.
        try:
            if process.poll() is None:
                process.kill()
        except Exception:
            cleanup_errors += 1
        wait_deadline = time.monotonic() + 3
        for child, created, executable in reversed(descendants):
            try:
                if child.create_time() == created and Path(child.exe()).resolve() == executable:
                    child.kill()
                    child.wait(timeout=max(0.05, wait_deadline - time.monotonic()))
                else:
                    cleanup_errors += 1
            except Exception:
                cleanup_errors += 1
        try:
            process.communicate(timeout=3)
        except Exception:
            # No unbounded second wait, no unproven cleanup or unrelated process signal.
            raise OIDatabaseUnavailable() from None
        raise OIDatabaseUnavailable(cleanup_verified=cleanup_errors == 0) from None


class OIRuntimeDatabase:
    """Fixed future third-runtime target; no arbitrary production path/host/port/name."""

    def __init__(self, source_root: Path) -> None:
        root = source_root.absolute()
        expected = Path.home() / "Desktop" / "Auvexo Alpha OI Runtime"
        if os.name != "nt" or root != expected:
            raise OIDatabaseUnavailable()
        _safe_path(root)
        self.root = root
        self.source = root
        self.pg = root / ".local" / "toolchains" / "postgres" / "pgsql" / "bin"
        self.database, self.port = OI_DATABASE, OI_PORT
        self.test_id: UUID | None = None
        self.slots: _Slots = _WindowsSlots()
        self._guard_target()

    @classmethod
    def _for_test(
        cls, identity: UUID, port: int, pg: Path, source: Path, slots: _Slots
    ) -> OIRuntimeDatabase:
        if not isinstance(identity, UUID) or type(port) is not int or not 55500 <= port <= 55999:
            raise OIDatabaseUnavailable()
        instance = object.__new__(cls)
        instance.root = Path(tempfile.gettempdir()).resolve() / (
            "auvexo-oi-db-test-" + identity.hex
        )
        _safe_path(instance.root)
        instance.source, instance.pg = source.absolute(), pg.absolute()
        instance.database = "auvexo_test_oi" + identity.hex
        instance.port, instance.test_id, instance.slots = port, identity, slots
        instance._guard_target()
        return instance

    def _guard_target(self) -> None:
        if self.test_id is None:
            if (
                os.name != "nt"
                or self.root != Path.home() / "Desktop" / "Auvexo Alpha OI Runtime"
                or self.source != self.root
                or self.pg != self.root / ".local" / "toolchains" / "postgres" / "pgsql" / "bin"
                or (self.database, self.port) != (OI_DATABASE, OI_PORT)
                or not isinstance(self.slots, _WindowsSlots)
            ):
                raise OIDatabaseUnavailable()
        elif (
            not isinstance(self.test_id, UUID)
            or self.root
            != Path(tempfile.gettempdir()).resolve() / ("auvexo-oi-db-test-" + self.test_id.hex)
            or self.database != "auvexo_test_oi" + self.test_id.hex
            or type(self.port) is not int
            or not 55500 <= self.port <= 55999
            or isinstance(self.slots, _WindowsSlots)
        ):
            raise OIDatabaseUnavailable()
        _safe_path(self.root)

    @property
    def local(self) -> Path:
        return self.root / ".local"

    @property
    def data(self) -> Path:
        return self.local / "oi-postgres"

    @property
    def state(self) -> Path:
        return self.local / "oi-database-state.json"

    @property
    def log(self) -> Path:
        return self.local / "oi-postgres.log"

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        self._guard_target()
        for path in (self.root, self.local, self.data, self.state, self.log):
            _safe_path(path)
        self.local.mkdir(parents=True, exist_ok=True)
        lock = self.local / "oi-database.lock"
        _safe_path(lock)
        token = uuid4().hex.encode("ascii")
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except OSError:
            raise OIDatabaseUnavailable() from None
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(token)
                file.flush()
                os.fsync(file.fileno())
            yield
        finally:
            _safe_path(lock)
            if lock.read_bytes() != token:
                raise OIDatabaseUnavailable()
            lock.unlink()

    def _toolchain(self) -> dict[str, str]:
        hashes = {}
        for name in ("initdb", "pg_ctl", "postgres"):
            path = self.pg / (name + (".exe" if os.name == "nt" else ""))
            _safe_path(path)
            version = _run(path, ["--version"]).decode("ascii").strip()
            if version.split()[-1] != _VERSION:
                raise OIDatabaseUnavailable()
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        return hashes

    def _exe(self, name: str) -> Path:
        return self.pg / (name + (".exe" if os.name == "nt" else ""))

    def _clock(self) -> None:
        self._guard_target()
        if self.test_id is not None:
            return
        if sys.platform != "win32":
            raise OIDatabaseUnavailable()
        from auvexo_alpha.infrastructure.oi_runtime import inspect_clock, w32tm_executable

        try:
            # Absolute system path: a bare name is searched in the current directory first.
            source = subprocess.check_output(
                [str(w32tm_executable()), "/query", "/source"],
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).strip()
            inspect_clock(source)
        except Exception:
            raise OIDatabaseUnavailable() from None

    def _url(self, role: str, password: str, *, database: str | None = None) -> URL:
        if role not in (OI_ADMIN, *_ROLES):
            raise OIDatabaseUnavailable()
        return URL.create(
            "postgresql+psycopg",
            username=role,
            password=password,
            host="127.0.0.1",
            port=self.port,
            database=database or self.database,
        )

    def _connect(
        self, password: str, *, database: str | None = None
    ) -> psycopg.Connection[tuple[Any, ...]]:
        return psycopg.connect(
            host="127.0.0.1",
            port=self.port,
            dbname=database or self.database,
            user=OI_ADMIN,
            password=password,
            connect_timeout=3,
            options="-c statement_timeout=10000 -c lock_timeout=3000",
            autocommit=True,
        )

    def _record(self, status: str, hashes: dict[str, str]) -> None:
        payload = {
            "version": 1,
            "status": status,
            "database": self.database,
            "port": self.port,
            "root": str(self.root),
            "postgres_version": _VERSION,
            "tools": hashes,
        }
        if (self.data / "postgresql.conf").exists():
            payload["configuration"] = {
                name: hashlib.sha256((self.data / name).read_bytes()).hexdigest()
                for name in _CONFIGURATION
            }
        temporary = self.state.with_suffix(".new")
        _safe_path(temporary)
        with temporary.open("x", encoding="utf8") as file:
            json.dump(payload, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, self.state)

    def _attest_files(self, *, allow_recovery: bool = False) -> None:
        for path in (
            self.state,
            self.data,
            self.data / "PG_VERSION",
            *(self.data / name for name in _CONFIGURATION),
        ):
            _safe_path(path)
        record = json.loads(self.state.read_text(encoding="utf8"))
        if (
            record
            != {
                "version": 1,
                "status": record.get("status") if allow_recovery else "READY",
                "database": self.database,
                "port": self.port,
                "root": str(self.root),
                "postgres_version": _VERSION,
                "tools": self._toolchain(),
                "configuration": {
                    name: hashlib.sha256((self.data / name).read_bytes()).hexdigest()
                    for name in _CONFIGURATION
                },
            }
            or record.get("status") not in ("READY", "RECOVERY_REQUIRED")
            or (self.data / "PG_VERSION").read_text().strip() != "17"
        ):
            raise OIDatabaseUnavailable()

    def _verify_identity(
        self, connection: psycopg.Connection[tuple[Any, ...]], database: str
    ) -> None:
        actual = connection.execute(
            "SELECT current_user,current_database(),host(inet_server_addr()),"
            "inet_server_port(),current_setting('server_version_num'),"
            "current_setting('data_directory'),current_setting('listen_addresses'),"
            "current_setting('hba_file'),current_setting('password_encryption'),"
            "current_setting('log_statement'),current_setting('log_min_error_statement'),"
            "current_setting('log_parameter_max_length'),"
            "current_setting('log_parameter_max_length_on_error')"
        ).fetchone()
        if (
            actual is None
            or actual[:5] != (OI_ADMIN, database, "127.0.0.1", self.port, "170011")
            or Path(actual[5]).resolve() != self.data
            or actual[6] != "127.0.0.1"
            or Path(actual[7]).resolve() != self.data / "pg_hba.conf"
            or actual[8:] != ("scram-sha-256", "none", "panic", "0", "0")
        ):
            raise OIDatabaseUnavailable()
        rules = connection.execute("SELECT auth_method,error FROM pg_hba_file_rules").fetchall()
        if not rules or any(
            method != "scram-sha-256" or error is not None for method, error in rules
        ):
            raise OIDatabaseUnavailable()

    def _verify_server(
        self, passwords: _Passwords, review_authority: OIReviewAuthority | None = None
    ) -> None:
        with self._connect(passwords.admin) as connection:
            self._verify_identity(connection, self.database)
            if connection.execute("SELECT version_num FROM alembic_version").fetchone() != (
                _REVISION,
            ):
                raise OIDatabaseUnavailable()
            if connection.execute(
                "SELECT execution_enabled,binance_live_derivatives FROM foundation_policy"
            ).fetchall() != [(False, "BLOCKED_BY_POLICY")]:
                raise OIDatabaseUnavailable()
            identities = connection.execute(
                "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,"
                "rolbypassrls,rolcanlogin FROM pg_roles WHERE rolname IN "
                "('auvexo_app','auvexo_data_writer','auvexo_ingest') ORDER BY rolname"
            ).fetchall()
            if identities != [
                ("auvexo_app", False, False, False, False, False, True),
                ("auvexo_data_writer", False, False, False, False, False, True),
                ("auvexo_ingest", False, False, False, False, False, False),
            ]:
                raise OIDatabaseUnavailable()
            memberships = connection.execute(
                "SELECT member.rolname,parent.rolname,m.admin_option,m.inherit_option,"
                "m.set_option FROM pg_auth_members m "
                "JOIN pg_roles member ON member.oid=m.member "
                "JOIN pg_roles parent ON parent.oid=m.roleid "
                "WHERE member.rolname IN ('auvexo_app','auvexo_data_writer','auvexo_ingest') "
                "ORDER BY 1,2"
            ).fetchall()
            if memberships != [("auvexo_data_writer", "auvexo_ingest", False, True, False)]:
                raise OIDatabaseUnavailable()
        # Reuse the collector's exact source-dedication rules without filesystem effects.
        from auvexo_alpha.infrastructure.oi_store import attest_oi_database

        engine = create_engine(
            self._url("auvexo_data_writer", passwords.writer),
            poolclass=NullPool,
            hide_parameters=True,
            connect_args={"connect_timeout": 3},
        )
        try:
            with engine.connect() as connection:
                attest_oi_database(connection, review_authority)
        finally:
            engine.dispose()
        for role, password in zip(_ROLES, (passwords.app, passwords.writer), strict=True):
            with psycopg.connect(
                host="127.0.0.1",
                port=self.port,
                dbname=self.database,
                user=role,
                password=password,
                connect_timeout=3,
            ) as connection:
                if connection.execute("SELECT current_user").fetchone() != (role,):
                    raise OIDatabaseUnavailable()
                if connection.execute(
                    "SELECT has_schema_privilege(current_user,'public','CREATE'),"
                    "has_table_privilege(current_user,'foundation_policy','INSERT,UPDATE,DELETE'),"
                    "has_table_privilege(current_user,'paper_intent','INSERT,UPDATE,DELETE'),"
                    "has_table_privilege(current_user,'research_study','INSERT,UPDATE,DELETE')"
                ).fetchone() != (False, False, False, False):
                    raise OIDatabaseUnavailable()
                for table in (
                    "data_manifest",
                    "data_event",
                    "data_checkpoint",
                    "data_source_review",
                    "data_spec",
                ):
                    result = connection.execute(
                        "SELECT has_table_privilege(current_user,%s,'SELECT'),"
                        "has_table_privilege(current_user,%s,'INSERT'),"
                        "has_table_privilege(current_user,%s,'UPDATE,DELETE,TRUNCATE')",
                        (table, table, table),
                    ).fetchone()
                    if result != (True, role == "auvexo_data_writer", False):
                        raise OIDatabaseUnavailable()
                permissions = connection.execute(
                    "SELECT c.relname,has_table_privilege(current_user,c.oid,'SELECT'),"
                    "has_table_privilege(current_user,c.oid,'INSERT'),"
                    "has_table_privilege(current_user,c.oid,'UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'),"
                    "has_any_column_privilege(current_user,c.oid,'SELECT'),"
                    "has_any_column_privilege(current_user,c.oid,'INSERT'),"
                    "has_any_column_privilege(current_user,c.oid,'UPDATE,REFERENCES') "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')"
                ).fetchall()
                data_tables = {
                    "data_manifest",
                    "data_event",
                    "data_checkpoint",
                    "data_source_review",
                    "data_spec",
                }
                readable = data_tables | {"foundation_policy", "alembic_version"}
                if role == "auvexo_app":
                    readable.add("developer_event")
                for name, *permission in permissions:
                    read = name in readable
                    insert = role == "auvexo_data_writer" and name in data_tables
                    if permission != [read, insert, False, read, insert, False]:
                        raise OIDatabaseUnavailable()
                unexpected_sequences = connection.execute(
                    "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND c.relkind='S' "
                    "AND has_sequence_privilege(current_user,c.oid,'USAGE,SELECT,UPDATE')"
                ).fetchall()
                unexpected_functions = connection.execute(
                    "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "WHERE n.nspname='public' AND p.prosecdef "
                    "AND has_function_privilege(current_user,p.oid,'EXECUTE')"
                ).fetchall()
                if (
                    unexpected_sequences
                    or unexpected_functions
                    or connection.execute(
                        "SELECT has_database_privilege("
                        "current_user,current_database(),'CREATE,TEMP'),"
                        "has_database_privilege(current_user,'postgres','CONNECT')"
                    ).fetchone()
                    != (False, False)
                ):
                    raise OIDatabaseUnavailable()
            # Actual wrong-password rejection also catches stale loaded trust rules.
            rejected = False
            try:
                unexpected_connection = psycopg.connect(
                    host="127.0.0.1",
                    port=self.port,
                    dbname=self.database,
                    user=role,
                    password=secrets.token_urlsafe(48),
                    connect_timeout=3,
                )
            except psycopg.OperationalError as failure:
                rejected = "password authentication failed" in str(failure).casefold()
            else:
                unexpected_connection.close()
            if not rejected:
                raise OIDatabaseUnavailable()

    def provision(self) -> None:
        """Future explicit commissioning only; all cleanup stays under the owned lock."""
        try:
            self._clock()
            with self._exclusive():
                self._provision_locked()
        except (Exception, KeyboardInterrupt):
            raise OIDatabaseUnavailable() from None

    def _provision_locked(self) -> None:
        """Future explicit commissioning only; no persistent target is used by tests."""
        started = False
        owned = False
        start_attempted = False
        try:
            if self.state.exists() or self.data.exists() or self.log.exists():
                raise OIDatabaseUnavailable()
            self.slots.require_absent()
            hashes = self._toolchain()
            with socket.socket() as check:
                check.bind(("127.0.0.1", self.port))
            passwords = _Passwords.generate()
            self._record("PROVISIONING", hashes)
            owned = True
            _run(
                self._exe("initdb"),
                [
                    "-D",
                    str(self.data),
                    "-U",
                    OI_ADMIN,
                    "--pwprompt",
                    "--auth=scram-sha-256",
                    "--encoding=UTF8",
                    "--locale=C",
                ],
                password=passwords.admin,
            )
            with (self.data / "postgresql.conf").open("a", encoding="utf8") as file:
                file.write(
                    "\nlisten_addresses='127.0.0.1'\nport=" + str(self.port) + "\n"
                    "shared_buffers='32MB'\nmax_connections=10\n"
                    "password_encryption='scram-sha-256'\n"
                    "log_statement='none'\nlog_min_error_statement='panic'\n"
                    "log_parameter_max_length=0\nlog_parameter_max_length_on_error=0\n"
                    "logging_collector=off\n"
                )
            start_attempted = True
            _run(
                self._exe("pg_ctl"),
                [
                    "-D",
                    str(self.data),
                    "-l",
                    str(self.log),
                    "-w",
                    "-t",
                    "30",
                    "start",
                ],
            )
            started = True
            with self._connect(passwords.admin, database="postgres") as connection:
                # Attest the actual server BEFORE the first credential-bearing DDL.
                self._verify_identity(connection, "postgres")
                for role, password in zip(_ROLES, (passwords.app, passwords.writer), strict=True):
                    connection.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
                            "NOCREATEROLE NOREPLICATION NOBYPASSRLS INHERIT"
                        ).format(sql.Identifier(role), sql.Literal(password))
                    )
                connection.execute("REVOKE ALL ON DATABASE postgres,template1 FROM PUBLIC")
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database))
                )
                connection.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(
                        sql.Identifier(self.database)
                    )
                )
                connection.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO auvexo_app,auvexo_data_writer").format(
                        sql.Identifier(self.database)
                    )
                )
            engine = create_engine(
                self._url(OI_ADMIN, passwords.admin),
                poolclass=NullPool,
                hide_parameters=True,
                connect_args={"connect_timeout": 3},
            )
            try:
                with engine.begin() as connection:
                    migrate_oi_database(
                        connection,
                        self.source,
                        _test_id=self.test_id,
                        _test_port=self.port if self.test_id else None,
                    )
                    connection.execute(
                        text(
                            "GRANT auvexo_ingest TO auvexo_data_writer "
                            "WITH ADMIN FALSE, INHERIT TRUE, SET FALSE"
                        )
                    )
                    connection.execute(text("REVOKE CREATE ON SCHEMA public FROM PUBLIC"))
            finally:
                engine.dispose()
            self._verify_server(passwords)
            self.slots.store(passwords)
            self._record("READY", hashes)
        except (Exception, KeyboardInterrupt):
            try:
                if start_attempted and not started:
                    # A failed start may have launched a server. Stop only if the exact
                    # new UUID/fixed owned data directory and endpoint are proven live.
                    try:
                        with self._connect(passwords.admin, database="postgres") as connection:
                            self._verify_identity(connection, "postgres")
                        started = True
                    except Exception:
                        raise OIDatabaseUnavailable() from None
                if started:
                    # Only the process launched against this newly created owned directory.
                    try:
                        _run(
                            self._exe("pg_ctl"),
                            ["-D", str(self.data), "-m", "fast", "-w", "-t", "30", "stop"],
                        )
                    except Exception:
                        # Do not claim cleanup: original PROVISIONING means recovery required.
                        raise OIDatabaseUnavailable() from None
            finally:
                # Recovery-receipt failure must never prevent owned-process cleanup.
                if owned:
                    try:
                        self._record("RECOVERY_REQUIRED", hashes)
                    except (Exception, KeyboardInterrupt):
                        raise OIDatabaseUnavailable() from None
            raise OIDatabaseUnavailable() from None

    def verify(self, *, review_authority: OIReviewAuthority | None = None) -> None:
        try:
            with self._exclusive():
                self._attest_files()
                self._verify_server(self.slots.load(), review_authority)
        except Exception:
            raise OIDatabaseUnavailable() from None

    def start(self, *, review_authority: OIReviewAuthority | None = None) -> None:
        try:
            self._clock()
            with self._exclusive():
                self._start_locked(review_authority)
        except (Exception, KeyboardInterrupt):
            raise OIDatabaseUnavailable() from None

    def _start_locked(self, review_authority: OIReviewAuthority | None) -> None:
        started = False
        start_attempted = False
        try:
            self._attest_files()
            hashes = json.loads(self.state.read_text(encoding="utf8"))["tools"]
            passwords = self.slots.load()
            if (self.data / "postmaster.pid").exists():
                self._verify_server(passwords, review_authority)
                return
            with socket.socket() as check:
                check.bind(("127.0.0.1", self.port))
            start_attempted = True
            _run(
                self._exe("pg_ctl"),
                ["-D", str(self.data), "-l", str(self.log), "-w", "-t", "30", "start"],
            )
            started = True
            self._verify_server(passwords, review_authority)
        except (Exception, KeyboardInterrupt):
            try:
                if start_attempted and not started:
                    try:
                        with self._connect(passwords.admin) as connection:
                            self._verify_identity(connection, self.database)
                        started = True
                    except Exception:
                        raise OIDatabaseUnavailable() from None
                if started:
                    try:
                        _run(
                            self._exe("pg_ctl"),
                            ["-D", str(self.data), "-m", "fast", "-w", "-t", "30", "stop"],
                        )
                    except Exception:
                        raise OIDatabaseUnavailable() from None
            finally:
                # Recovery-receipt failure must never prevent owned-process cleanup.
                if start_attempted:
                    try:
                        self._record("RECOVERY_REQUIRED", hashes)
                    except (Exception, KeyboardInterrupt):
                        raise OIDatabaseUnavailable() from None
            raise OIDatabaseUnavailable() from None

    def stop(self) -> None:
        try:
            with self._exclusive():
                self._attest_files(allow_recovery=True)
                # Stopping a proven owned server is containment, not qualification.
                # Foreign rows/grant drift must not prevent this owner safety action.
                with self._connect(self.slots.load_admin()) as connection:
                    self._verify_identity(connection, self.database)
                _run(
                    self._exe("pg_ctl"),
                    ["-D", str(self.data), "-m", "fast", "-w", "-t", "30", "stop"],
                )
        except Exception:
            raise OIDatabaseUnavailable() from None
