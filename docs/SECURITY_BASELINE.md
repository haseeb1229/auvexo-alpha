# Security baseline

Status: FROZEN requirements; library and credential mechanisms qualified in Phase 1/5/8.

Phase 1 implements only authenticated loopback diagnostics, redacted strict configuration,
Windows ACL-protected local development credentials and least-privilege DB reads;
see [current scope and limitations](phase1/SETUP.md). Passkeys, OS encrypted credential storage,
service identity and live activation below remain unimplemented future gates.

One owner, no public signup. Private repository visibility is not an application security
control. Local-first services bind loopback with authenticated requests; broker gateway has
its own identity, token/certificate audience and narrow command allowlist. A local hostile
process is within the threat model. Windows user compromise remains a residual risk.

| Threat | Control and proof |
| --- | --- |
| Stolen owner session | Mature WebAuthn/passkey library, secure session cookies, short idle expiry, CSRF/origin checks; test stolen/expired/replayed session rejection |
| Dangerous activation | Fresh step-up authentication, action-specific nonce/intent digest, <=5 min activation window, no reusable blanket approval; test replay, account and hash mismatch |
| Gateway/agent impersonation | Per-service least privilege, authenticated local IPC, audience/epoch checks, reject unsigned/expired risk authorization |
| Secret theft | Windows Credential Manager/DPAPI-backed store for initial gateway; equivalent OS secret store for later hosts; secrets never in Git/browser/model context/logs |
| Prompt injection | Untrusted retrieved text, schema validation, tools outside model authority, allowlisted URLs, no shell or production writes |
| Supply-chain compromise | Locked dependencies, verified source/hash, SBOM, dependency audit and secret scan; pinned CI action SHAs when added; no arbitrary plugins |
| Audit tampering | Restricted append-only roles, hash chain, signed independent checkpoints/backup; validate on restore; disclose admin threat limitation |
| Data poisoning/stale quotes | Source provenance, availability timestamps, quarantine, freshness/quality gates, independent comparisons where possible |
| Cross-environment mistake | Separate credentials/config, real-account attestation, mode/permit agreement, negative tests and startup refusal |
| Remote compromise | Private-network/identity-aware access, TLS, device revocation, no public DB or MT5 port; obscurity/domain name provides no trust |

Use passkeys as preferred owner authentication when the client exists; optional TOTP is a
documented fallback, never a silent downgrade for live activation. Offline recovery codes
must be encrypted/physically controlled separately from the laptop. For early CLI-only
development, an OS-protected local admin session may administer non-trading setup; it is
not sufficient evidence for a future LiveTradingPermit. No home-grown cryptography.

Secrets: separate development/demo/shadow/live namespaces; execution credentials only at
gateway; data API keys only in collectors; owner broker portal credentials never ingested.
Disable withdrawal permission on exchange API keys, restrict IP where practical and verify
effective rights. MT5 terminal credentials may not expose API-style scopes; evaluate actual
broker permissions without claiming unsupported restrictions. Deny any adapter requiring
withdrawal capability. Rotate on exposure and revoke before replacing; rewriting Git alone
does not repair a leaked secret. .gitignore is defense-in-depth, not secret scanning.

Policy/permit signing key lives outside runtime workers; a compromised LLM cannot sign.
Owner activation binds account, server, product, strategy/build/config hashes, limits and
expiry. Application roles cannot write the allowlist or clear a kill switch. Developer
administrative access is documented as privileged, audited and separated from unattended
runtime. No production auto-deploy or model-generated release approval.

Backups encrypted at rest, keys separate, restores tested in isolated non-trading mode.
Break-glass: owner enters K4, uses broker terminal directly if safe, revokes credentials,
preserves evidence, restores known-good release, reconciles all positions and re-enrolls
authentication. Recovery never silently re-enables live. See operations runbooks.

Phase 1 checks secrets/dependencies in local tooling and CI where quota permits; no paid
GitHub security entitlement is assumed. Before demo: auth negatives, service isolation,
credential redaction and malicious-tool tests. Before live: independent security review,
backup drill, owner recovery rehearsal, current dependency scan and release integrity.
Auth/library selection must use maintained official documentation when implemented.

## Phase 2 data boundary

Public sources use an explicit GET-only host/path allowlist, no credentials, no
redirects and bounded untrusted input parsing. Separate ingestion DB privileges do
not grant foundation-policy writes. [Setup](phase2/SETUP_AND_RECOVERY.md) documents
the local development writer credential and residual owner/admin access. No broker
secret store, terminal account, SDK or order path is adopted. Exness remains disabled
until encrypted OS storage, isolation and genuine demo attestation can be proved.

## Public-source and release integrity gates

The owner-approved temporary PUBLIC source exception is review-due 2026-10-24; private-first
remains the baseline. Public history/copies cannot be revoked. No broker credentials/sessions
or owner-private data may enter public Git history. Before broker credential/session integration
or proprietary alpha work, independent review must resolve return to PRIVATE under separate
owner instruction or an owner-approved superseding permanent-public ADR. This amendment changes
no visibility, billing, runner or permissions and infers no permanent public approval.

Before Phase 8, require protected main/release or equivalent independently reviewed integrity
control, a CI-bound release manifest/tag, exact approved hashes and no unreviewed release.
Current branch settings are not claimed to implement this future gate. See [operations](OPERATIONS_AND_RECOVERY.md).
