# Exness DEMO source preparation — still blocked

No onboarding approval, dedicated DEMO terminal attestation or encrypted broker secret
store has been verified. BTC/ETH/XAU broker symbols, contracts, lots, tick values,
spreads, sessions/financing and available history remain UNKNOWN. Binance spot data
does not substitute for those facts. No broker SDK/session is installed by this sprint.

Proposed next step, requiring separate owner approval: prepare a dedicated Windows
identity/process and isolated DEMO-only MT5 installation/profile; establish Windows
Credential Manager/DPAPI-backed storage and ACL/IPC boundaries; review current Exness
terms, MT5 SDK/runtime compatibility and the actual capability boundary. Then the
owner logs into a dedicated DEMO terminal through the supported local GUI. No account
number, password, recovery material or session belongs in chat, source or a receipt.

Before any connector starts, genuinely attest account type/server locally, redact
identity in exported evidence and fail closed on REAL/unknown/swapped accounts. Use
a narrow separate data process with an explicit read-call interface and forbidden-call
tests. A vendor SDK with trade methods is not a broker-level read-only entitlement;
a module name or boolean does not enforce isolation. Assess terminal trade settings,
process/network/IPC capabilities and account-switch failure before adopting an SDK.

There are no order tests against any terminal in Phase 2. Phase 5 owns later DEMO orders.
The existing unconditional connector refusal remains until separately authorized secure
onboarding and its independent review. Canonical deferral needs an explicit founder
scope decision and reviewer acceptance; this proposal does not mark DS-03 complete.
