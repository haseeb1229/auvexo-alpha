# DS-03 Exness rights: owner decision packet, 2026-11-13

> Dated record. The current state is in [STATUS](../STATUS.md). This packet describes what
> the documents say. It is not legal advice and it decides nothing.

## Status

**DS03_RIGHTS_UNRESOLVED.** The read-only MT5 adapter exists as engineering only
([ADR-029](../adr/029-ds03-mt5-readonly-adapter.md), [ADR-030](../adr/030-ds03-adapter-independent-review-corrections.md)).
No account, session, credential or onboarding exists, and none is authorized. Nothing in
this packet changes that.

The intended use: an Exness MT5 **demo** account, logged in with the read-only (investor)
password, read by a local program that stores quotes, bars, ticks and account facts
privately for research. No trading.

## What was retrieved

Official Exness and MetaQuotes sources, fetched 2026-11-13 without signing in or
accepting anything.

| Document | Version | SHA-256 |
| --- | --- | --- |
| Exness (SC) Ltd Client Agreement | 24 July 2026 /039 | `d54bd9f46201ed82b4f470b3c871a8740d885261179919694c8d149782ef77bb` |
| Exness (VG) Ltd Client Agreement | 24 July 2026 /028 | `e33ca34d3145ec0d5c14d94b649e604b0cbbcaf02bca79b5f9866f090e2b3e5d` |
| Exness (SC) General Business Terms | 12 August 2025 /021 | `a8e8e0942d402c415770943283ef2f44b4d680339530d28b167fc79928174b11` |
| Exness (VG) General Business Terms | 12 August 2025 /014 | `e6294cf454a915a1c3689c646c07b79afa2d5c9d3689e831dbeefd14c3c3a826` |
| MetaQuotes MetaTrader 5 end-user licence | Undated | `b494eccd01f6afc18a1d05b56a10c5e238ca55be35d9629bf595e2078d640832` |
| Exness help-centre articles on read-only passwords, demo accounts, archived accounts, regulation and the Exness API | Edited 2026-03 to 2026-11 | Kept locally with hashes |

The SC and VG Client Agreements have the same Parts C and D apart from spelling.

**Not retrieved:** the Exness "API Terms of Use", which the Client Agreement incorporates
(Part A 1.3). The legal pages are behind a challenge page and no official copy could be
fetched. Its text is unknown.

## What the text says

Clause numbers are from the SC agreement; VG matches.

**Permits:**

- Part C 4.3: "The Client is permitted to store, display, analyze, modify, reformat and
  print the information made available to him through the Website or the Trading Platform
  or the API. The Client is not permitted to publish, transmit, or otherwise reproduce that
  information ... to any third party without the Company's express written consent."
- Help centre: the read-only password gives view-only access with trading disabled.

**Restricts:**

- Part C 2.3: "It is absolutely prohibited to ... (G) Use ... any software, program,
  application or other device, directly or indirectly, to access or obtain information
  through the Trading Platform or automate the process of accessing or obtaining such
  information." The Trading Platform and Client Terminal definitions include MT5 and the
  information it provides. A local program reading MT5 data falls within this wording.
- Part C 2.3(A): no software "which applies artificial intelligence analysis to the
  Company's system and/or Trading Platform". Whether offline analysis of stored data is
  covered is not stated.
- Part C 2.5 lists as a prohibited technique "accessing, collecting, scraping,
  extracting, copying, storing ... the Company's market data, price feeds, quotes or other
  platform data for any purpose other than the Client's own genuine trading with the
  Company". Remedies include blocking accounts and revoking access. Research with no
  trading is not trading with the Company.
- Part A 14.1(N): bid and offer prices only "for its own trading purposes", "except if
  otherwise previously agreed between the parties".
- Part D 6.6: "Unless expressly authorised in writing by the Company", indicators and
  platform data are for personal visualisation within the platform and may not be used
  for "integration with external systems, software, or APIs" or "machine-driven or
  automated decision-making".

Part C 4.3 pulls one way; Parts C 2.3(G), C 2.5, A 14.1(N) and D 6.6 pull the other. The
agreement states no rule for which prevails. Three of the restricting clauses themselves
mention prior agreement or written authorization by Exness.

**Silent or unknown:**

- Neither Client Agreement mentions demo accounts. Whether it governs one is not stated.
- Demo accounts are deleted, irreversibly, after an unspecified period without trading or
  balance operations, which a read-only reader never performs.
- Which Exness entity contracts with a given client is shown only in the footer of that
  client's Personal Area. No public source maps Pakistan residents to SC or VG.

## Options for the owner

| Option | What it means |
| --- | --- |
| **E1. Keep DS-03 blocked** (current state) | No change. The adapter stays engineering-only. |
| **E2. Ask Exness for written consent** | The agreement's own wording (A 14.1(N), C 4.3, D 6.6) names prior or written authorization. A written statement that automated read-only collection and private storage from a demo account is permitted would address the restricting clauses directly. This is an owner action; this run contacted no one. |
| **E3. Use a different source** for whatever research need DS-03 was meant to meet, one whose terms expressly permit automated collection and private storage. |
| **E4. Owner accepts the risk without consent** | Not recommended by this packet. The restricting clauses are worded "absolutely prohibited", carry account remedies, and the API Terms of Use could not be read. |

Engineering recommendation: **E1 now, E2 if DS-03 is still wanted.** Any onboarding also
still needs the ADR-030 preconditions, including the PRIVATE repository return, before an
account or credential appears anywhere.

## What onboarding would additionally require

If the owner ever obtains consent: identify the contracting entity from the Personal Area
footer, retrieve and review the API Terms of Use, record the consent and the documents by
hash in a rights record with a due date, and complete every ADR-030 precondition. None of
that is authorized now.
