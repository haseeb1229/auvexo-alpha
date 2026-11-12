# Local state

Everything under `.local/` in each checkout is ignored by Git and by the documentation
check. Some of it is evidence, some is secret, most is disposable.

## Operational checkout: keep

| Path under `.local/` | Contents |
| --- | --- |
| `postgres-data/` | The PostgreSQL cluster. Irreplaceable until a backup exists. |
| `market/`, `observation/` | Hash-verified data artifacts referenced by manifests. |
| `scheduled-data/` | Public-data wrapper summaries and logs. Logs older than 14 days are pruned by the wrapper; summaries are kept. |
| `phase4/checkpoint-b/acceptance-prestart/runtime/` | The PAPER campaign envelope used by the task. |
| `dev-secrets.json`, `data-secrets.json`, `paper-identities/` | Local database credentials. Secret. |
| `python/`, `toolchains/`, `.venv` at the checkout root | Interpreter and tools the tasks run with. The Development environment also uses this interpreter. |
| `PHASE_*_HANDOFF.md` and dated evidence directories | Historical delivery records. |

Do not delete, move or edit anything in the Operational checkout.

## Development checkout: disposable unless noted

| Path under `.local/` | Contents |
| --- | --- |
| `uv-cache/`, `npm-cache/`, `wheels/` | Download caches. Safe to delete; slow to refill on this network. |
| `d3a-*`, `d3f-*`, `p6f-*`, `p6r-*`, `p6v-*`, `clean-clone-*` | Old fresh-clone verification copies, each with its own environment. Safe to delete. |
| `phase2/`, `phase5/`, `phase6/`, `phase7/`, `source-review/` | Local receipts from earlier work: CI logs, scan reports, handoffs. Keep while they are cited; they are not in Git. |
| `phase6/engineering/pg-55433/` | A disposable test cluster. Not production. |
| `toolchains/postgres/` | PostgreSQL binaries for local drills. |

## User profile

DPAPI-protected files live under `%LOCALAPPDATA%\AuvexoAlpha\`, with owner-and-SYSTEM
access only:

- `phase6\` open-interest database role secrets, once created;
- `phase2\ds03\` the DS-03 read-only password and encrypted account metadata, once created;
- `test-<uuid>` leaves created and removed by native tests.

None of the production slots exists yet.

## What must never be in Git

Anything under `.local/`, any credential, any account identifier or its digest, raw
broker data, experiment outputs and machine or user identifiers.
