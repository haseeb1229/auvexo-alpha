"""Direct, isolated PAPER LOGIN attestation; no administrative runtime sessions."""

import json
import re
from weakref import WeakKeyDictionary

import psycopg
from sqlalchemy import Engine, event
from sqlalchemy.exc import SQLAlchemyError

GROUP_TAGS = {
    "auvexo_paper": "pw",
    "auvexo_paper_truth": "pt",
    "auvexo_paper_owner": "po",
}
_ATTESTED: WeakKeyDictionary[Engine, str] = WeakKeyDictionary()


def _catalog_rows_sql(query: str, width: int, order: tuple[int, ...] = ()) -> str:
    """Encode original catalog rows without dropping duplicates, NULLs or ordering."""
    columns = [f"v{index}" for index in range(width)]
    values = ",".join(f"q.{column}" for column in columns)
    ordering = " ORDER BY " + ",".join(f"q.v{index}" for index in order) if order else ""
    return (
        "(SELECT COALESCE(jsonb_agg(jsonb_build_array("
        + values
        + ")"
        + ordering
        + "),'[]'::jsonb) FROM ("
        + query
        + ") AS q("
        + ",".join(columns)
        + "))"
    )


# One coherent catalog snapshot is read on EVERY checkout. Only SQL text and fixed
# allowlists are reused; no identity, grant or ownership result is cached.
# The existing PUBLIC pg_settings UPDATE exception concerns authorized session
# parameters only; it does not permit writes to application or catalog data.
_CATALOG_SQL = "SELECT " + ",".join(
    (
        _catalog_rows_sql(
            "SELECT "
            "current_user,session_user,current_database(),r.rolsuper,r.rolcreatedb,r.rolcreaterole,r.rolreplication,r.rolbypassrls,r.rolcanlogin,(r.rolvaliduntil"
            " IS NULL OR r.rolvaliduntil>clock_timestamp()) FROM pg_roles r WHERE "
            "r.rolname=current_user",
            10,
            (),
        ),
        _catalog_rows_sql(
            "SELECT "
            "rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolcanlogin "
            "FROM pg_roles WHERE rolname<>current_user AND pg_has_role(current_user,oid,'MEMBER') "
            "ORDER BY rolname",
            7,
            (0,),
        ),
        _catalog_rows_sql(
            "SELECT admin_option,inherit_option,set_option FROM pg_auth_members WHERE "
            "member=current_user::regrole AND roleid=to_regrole(%s)",
            3,
            (),
        ),
        _catalog_rows_sql(
            "SELECT EXISTS(SELECT FROM pg_namespace n WHERE "
            "has_schema_privilege(current_user,n.oid,'CREATE')),pg_has_role(current_user,'auvexo_admin','MEMBER'),has_database_privilege(current_user,current_database(),'CREATE'),has_database_privilege(current_user,current_database(),'TEMP'),EXISTS(SELECT"
            " FROM pg_class WHERE pg_has_role(current_user,relowner,'USAGE')),EXISTS(SELECT FROM "
            "pg_namespace WHERE pg_has_role(current_user,nspowner,'USAGE')),EXISTS(SELECT FROM "
            "pg_proc WHERE pg_has_role(current_user,proowner,'USAGE')),EXISTS(SELECT FROM "
            "pg_database WHERE pg_has_role(current_user,datdba,'USAGE')),current_schemas(false)",
            9,
            (),
        ),
        _catalog_rows_sql(
            "SELECT EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace CROSS"
            " JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) p(privilege) WHERE"
            " t.relkind IN ('r','p','v','m','f') AND "
            "(has_table_privilege(current_user,t.oid,p.privilege||' WITH GRANT OPTION') OR "
            "(has_table_privilege(current_user,t.oid,p.privilege) AND NOT ((p.privilege='SELECT' "
            "AND n.nspname IN ('pg_catalog','information_schema')) OR (p.privilege='UPDATE' AND "
            "n.nspname='pg_catalog' AND t.relname='pg_settings') OR (n.nspname='public' AND "
            "COALESCE((%s::jsonb->t.relname)?p.privilege,false))))))",
            1,
            (),
        ),
        _catalog_rows_sql(
            "SELECT EXISTS(SELECT FROM pg_class t JOIN pg_namespace n ON n.oid=t.relnamespace WHERE"
            " t.relkind IN ('r','p','v','m','f') AND "
            "(has_table_privilege(current_user,t.oid,'REFERENCES,TRIGGER') OR "
            "has_any_column_privilege(current_user,t.oid,'REFERENCES,SELECT WITH GRANT "
            "OPTION,INSERT WITH GRANT OPTION,UPDATE WITH GRANT OPTION') OR EXISTS(SELECT FROM "
            "unnest(ARRAY['SELECT','INSERT','UPDATE']) p(privilege) WHERE "
            "has_any_column_privilege(current_user,t.oid,p.privilege) AND NOT "
            "((p.privilege='SELECT' AND n.nspname IN ('pg_catalog','information_schema')) OR "
            "(p.privilege='UPDATE' AND n.nspname='pg_catalog' AND t.relname='pg_settings') OR "
            "(n.nspname='public' AND COALESCE((%s::jsonb->t.relname)?p.privilege,false))))))",
            1,
            (),
        ),
        _catalog_rows_sql(
            "SELECT "
            "bool_and(COALESCE(has_table_privilege(current_user,to_regclass('public.'||quote_ident(t.key)),p.privilege),false))"
            " FROM jsonb_each(%s::jsonb) t CROSS JOIN LATERAL jsonb_array_elements_text(t.value) "
            "p(privilege)",
            1,
            (),
        ),
        _catalog_rows_sql(
            "SELECT "
            "n.nspname,c.relname,has_sequence_privilege(current_user,c.oid,'USAGE'),has_sequence_privilege(current_user,c.oid,'SELECT'),has_sequence_privilege(current_user,c.oid,'UPDATE'),has_sequence_privilege(current_user,c.oid,'USAGE"
            " WITH GRANT OPTION,SELECT WITH GRANT OPTION,UPDATE WITH GRANT OPTION') FROM pg_class c"
            " JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='S' AND "
            "has_sequence_privilege(current_user,c.oid,'USAGE,SELECT,UPDATE') ORDER BY 1,2",
            6,
            (0, 1),
        ),
        _catalog_rows_sql(
            # JSON otherwise renders OIDs as strings; bigint preserves the full
            # OID range and the integer types returned by the original queries.
            "SELECT "
            "p.oid::bigint,n.nspname,p.proname,p.proargtypes::oid[]::bigint[],p.prorettype::bigint,p.proconfig,r.rolname,r.rolsuper,r.rolcreatedb,r.rolcreaterole,l.lanname,(SELECT"
            " COALESCE(jsonb_agg(jsonb_build_array(CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE "
            "acl_role.rolname END,a.privilege_type,a.is_grantable) ORDER BY CASE WHEN a.grantee=0 "
            "THEN 'PUBLIC' ELSE acl_role.rolname END,a.privilege_type,a.is_grantable),'[]'::jsonb) "
            "FROM aclexplode(COALESCE(p.proacl,acldefault('f',p.proowner))) a LEFT JOIN pg_roles "
            "acl_role ON acl_role.oid=a.grantee) FROM pg_proc p JOIN pg_namespace n ON "
            "n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner JOIN pg_language l ON "
            "l.oid=p.prolang WHERE p.prosecdef AND "
            "has_function_privilege(current_user,p.oid,'EXECUTE') ORDER BY 2,3",
            12,
            (1, 2),
        ),
    )
)


class PaperIdentityError(ValueError):
    """A redacted, fail-closed local PAPER identity/configuration refusal."""


def enforce_paper_engine(
    engine: Engine,
    group: str,
    *,
    expected_login: str | None = None,
    expected_database: str | None = None,
) -> None:
    """Attest each checkout, including already-pooled connections after rollback.

    The authenticated LOGIN has only one scoped NOLOGIN group. There is no elevated
    session identity to recover through RESET ROLE, rollback or reconnect.
    """
    url = engine.url
    database = url.database or ""
    match = re.fullmatch(r"auvexo_(?:test|restore)_([a-f0-9]{20})", database)
    tag = GROUP_TAGS.get(group)
    if match is None or tag is None:
        raise PaperIdentityError("PAPER_IDENTITY_DATABASE_OR_GROUP_DENIED")
    login = f"auvexo_{tag}_{match[1]}"
    if (
        url.drivername != "postgresql+psycopg"
        or url.host != "127.0.0.1"
        or url.port != 55432
        or bool(url.query)
        or url.username != login
        or (expected_login is not None and expected_login != login)
        or (expected_database is not None and expected_database != database)
        or not url.password
    ):
        raise PaperIdentityError("PAPER_IDENTITY_ENDPOINT_OR_LOGIN_DENIED")
    prior = _ATTESTED.get(engine)
    if prior is not None and prior != group:
        raise PaperIdentityError("PAPER_IDENTITY_ENGINE_SCOPE_DENIED")

    permitted_writes = {
        "auvexo_paper": {
            "paper_account": {"UPDATE"},
            "paper_intent": {"INSERT"},
            "paper_authorization": {"INSERT"},
            "paper_reservation": {"INSERT", "UPDATE"},
            "paper_outbox": {"INSERT", "UPDATE"},
            "paper_journal": {"INSERT"},
            "paper_denial": {"INSERT"},
        },
        "auvexo_paper_truth": {"paper_truth_event": {"INSERT"}},
        "auvexo_paper_owner": {
            "paper_account": {"INSERT", "UPDATE"},
            "paper_policy": {"INSERT"},
            "paper_release": {"INSERT"},
            "paper_production_release": {"INSERT"},
            "paper_lifecycle": {"INSERT"},
            "paper_production_lifecycle": {"INSERT"},
            "paper_journal": {"INSERT"},
        },
    }[group]
    permitted_reads = {
        "auvexo_paper": {
            "paper_policy",
            "paper_release",
            "paper_production_release",
            "paper_production_lifecycle",
            "paper_account",
            "paper_lifecycle",
            "paper_intent",
            "paper_authorization",
            "paper_reservation",
            "paper_outbox",
            "paper_journal",
            "paper_denial",
            "paper_truth_event",
            "foundation_policy",
            "alembic_version",
        },
        "auvexo_paper_truth": {"paper_truth_event"},
        "auvexo_paper_owner": {
            "paper_account",
            "paper_journal",
            "paper_truth_event",
            "paper_outbox",
            "paper_reservation",
            "paper_intent",
            "paper_policy",
            "paper_release",
            "paper_production_release",
            "paper_production_lifecycle",
            "paper_lifecycle",
        },
    }[group]
    full_rights = {table: set(operations) for table, operations in permitted_writes.items()}
    for table in permitted_reads:
        full_rights.setdefault(table, set()).add("SELECT")
    encoded_rights = json.dumps({table: sorted(ops) for table, ops in full_rights.items()})
    expected_sequences = {
        "auvexo_paper": {
            "paper_journal_sequence_seq",
            "paper_lifecycle_sequence_seq",
        },
        "auvexo_paper_truth": {"paper_truth_event_sequence_seq"},
        "auvexo_paper_owner": {
            "paper_journal_sequence_seq",
            "paper_lifecycle_sequence_seq",
            "paper_production_lifecycle_sequence_seq",
        },
    }[group]
    expected_sequence_rows = [
        ("public", name, True, True, False, False) for name in sorted(expected_sequences)
    ]

    def verify(connection: object, record: object, proxy: object) -> None:
        if not isinstance(connection, psycopg.Connection):
            raise PaperIdentityError("PAPER_IDENTITY_DRIVER_DENIED")
        info = connection.info
        if (info.host, info.port, info.dbname, info.user) != (
            "127.0.0.1",
            55432,
            database,
            login,
        ):
            raise PaperIdentityError("PAPER_IDENTITY_CONNECTED_ENDPOINT_DENIED")
        if info.parameter_status("TimeZone") != "UTC":
            raise PaperIdentityError("PAPER_IDENTITY_SESSION_TIMEZONE_DENIED")
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    _CATALOG_SQL, (group, encoded_rights, encoded_rights, encoded_rights)
                )
                catalog = cursor.fetchone()
                if catalog is None or len(catalog) != 9:
                    raise PaperIdentityError("PAPER_IDENTITY_SESSION_OR_ATTRIBUTES_DENIED")
                identity_rows = catalog[0]
                identity = tuple(identity_rows[0]) if len(identity_rows) == 1 else None
                if identity != (
                    login,
                    login,
                    database,
                    False,
                    False,
                    False,
                    False,
                    False,
                    True,
                    True,
                ):
                    raise PaperIdentityError("PAPER_IDENTITY_SESSION_OR_ATTRIBUTES_DENIED")
                if [tuple(row) for row in catalog[1]] != [
                    (group, False, False, False, False, False, False)
                ]:
                    raise PaperIdentityError("PAPER_IDENTITY_MEMBERSHIP_DENIED")
                if [tuple(row) for row in catalog[2]] != [(False, True, False)]:
                    raise PaperIdentityError("PAPER_IDENTITY_MEMBERSHIP_OPTIONS_DENIED")
                if [tuple(row) for row in catalog[3]] != [
                    (False, False, False, False, False, False, False, False, ["public"])
                ]:
                    raise PaperIdentityError("PAPER_IDENTITY_NAMESPACE_OR_OWNERSHIP_DENIED")
                if [tuple(row) for row in catalog[4]] != [(False,)]:
                    raise PaperIdentityError("PAPER_IDENTITY_CROSS_SCOPE_GRANT_DENIED")
                if [tuple(row) for row in catalog[5]] != [(False,)]:
                    raise PaperIdentityError("PAPER_IDENTITY_COLUMN_OR_TRIGGER_GRANT_DENIED")
                if [tuple(row) for row in catalog[6]] != [(True,)]:
                    raise PaperIdentityError("PAPER_IDENTITY_REQUIRED_GRANT_MISSING")
                if [tuple(row) for row in catalog[7]] != expected_sequence_rows:
                    raise PaperIdentityError("PAPER_IDENTITY_SEQUENCE_GRANT_DENIED")
                functions = catalog[8]
                signatures = {"paper_lock_truth": [25], "paper_fence_truth": [25, 20, 25, 25, 1184]}
                if (group != "auvexo_paper_truth" and functions) or (
                    group == "auvexo_paper_truth" and len(functions) != 2
                ):
                    raise PaperIdentityError("PAPER_IDENTITY_SECURITY_DEFINER_DENIED")
                for function in functions:
                    (
                        _oid,
                        schema,
                        name,
                        args,
                        result,
                        config,
                        owner,
                        superuser,
                        createdb,
                        createrole,
                        language,
                        acl_rows,
                    ) = function
                    normalized = [item.replace(" ", "") for item in config or []]
                    if (
                        schema != "public"
                        or name not in signatures
                        or args != signatures[name]
                        or result != 16
                        or normalized != ["search_path=pg_catalog,public"]
                        or owner != "auvexo_admin"
                        or not (superuser and createdb and createrole)
                        or language != "plpgsql"
                    ):
                        raise PaperIdentityError("PAPER_IDENTITY_SECURITY_DEFINER_DENIED")
                    acl = [tuple(row) for row in acl_rows]
                    if (
                        len(acl) != 2
                        or {(row[0], row[1]) for row in acl}
                        != {
                            ("auvexo_admin", "EXECUTE"),
                            ("auvexo_paper_truth", "EXECUTE"),
                        }
                        or any(row[2] for row in acl if row[0] != "auvexo_admin")
                    ):
                        raise PaperIdentityError("PAPER_IDENTITY_SECURITY_DEFINER_DENIED")
        finally:
            connection.rollback()

    if prior is None:
        event.listen(engine, "checkout", verify)
        _ATTESTED[engine] = group
    try:
        with engine.connect():
            pass
    except SQLAlchemyError:
        engine.dispose()
        raise PaperIdentityError("PAPER_IDENTITY_CONNECTION_UNAVAILABLE") from None
