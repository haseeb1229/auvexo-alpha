# Status history log

Before 2026-11-12 ten documents each began with a stack of dated "current status" blocks,
followed by older undated status paragraphs. The copies contradicted each other and the
repository. They were removed from the canonical documents and are kept here unchanged so
that no historical statement is lost or rewritten.

[STATUS](../STATUS.md) is the only place that states current status.

## Files

- [status-blocks-2026-11.txt](status-blocks-2026-11.txt): the four dated blocks
  (2026-11-03 implementation status, then the 2026-11-03, 2026-11-02 and 2026-10-27
  supersessions), one verbatim copy. sha256 of the copied text: `8679fb06b23f04317ff475785a4c716cb4c6db26771718b1705ee14e6883d4e5`.
- [legacy-status-paragraphs.txt](legacy-status-paragraphs.txt): the undated status
  paragraphs, one verbatim section per source range.

Both are plain text so that links inside the old wording are not treated as live links.

## Provenance of the dated blocks

| Block | Lines in each file | Introduced by commit |
| --- | --- | --- |
| Current implementation status, 2026-11-03 | 3-16 | `2833fc1` |
| Status supersession, 2026-11-03 | 17-63 | `f9a8609` |
| Status supersession, 2026-11-02 | 64-107 | `f78d50f` |
| Status supersession, 2026-10-27 | 108-119 | `887b6ac` |

Lines 3-119 were byte-identical in `README.md`, `AGENTS.md`, `CLAUDE.md`,
`docs/ARCHITECTURE.md`, `docs/OPEN_DECISIONS.md`, `docs/PRODUCT_CONSTITUTION.md`,
`docs/README.md` and `docs/ROADMAP.md`. `docs/SECURITY_BASELINE.md` carried lines 3-107
and `docs/phase2/DS03_IMPLEMENTATION.md` carried lines 3-63 of the same text. Removing
the stack from `docs/phase2/DS03_IMPLEMENTATION.md` restores the bytes accepted at
`ba66f44`.

## Provenance of the legacy paragraphs

Line numbers refer to commit `b743fc6ee8da3ba39435d9a4a3d4464bca547d5c`.

| Source file | Lines | sha256 of the range |
| --- | --- | --- |
| `README.md` | 121-192 | `66db7ed7be7d35bb68ab18f17ec54d7f79cfd1cf031d27c2bbcb698b98791ebe` |
| `README.md` | 206-211 | `7b03b860424e6f70b0f6c2806bd4de35996e3b22328a1add3db989fac76e6e9d` |
| `CLAUDE.md` | 121-268 | `9fde03599a9536839c91e65f49566359a6b70b1e1d5e0573648ab18ca9fa05f8` |
| `docs/PRODUCT_CONSTITUTION.md` | 121-138 | `b4db0f399ea2f172be737be03eb88ef170ade819cb85b5a7378fde911ea63bef` |
| `docs/PRODUCT_CONSTITUTION.md` | 173-187 | `0210cb6fda691b1fdd4fabcb60eb23b13a333f522b091664b4c95a85dcbbcc1e` |
| `docs/ARCHITECTURE.md` | 121-147 | `4e44b7f7af6201a5968aab915aafccd86c40943fa275b16a8d61069f71351d36` |
| `docs/ROADMAP.md` | 121-201 | `f2dafb51ddc979c4e050593258c32242a36e6eb3dca68d63f88facc89b128b91` |
| `docs/ROADMAP.md` | 429-430 | `b38b4124b94a3239c877f0cd30ebc347d08cd0a9a29991032438208e4802c04a` |
| `docs/OPEN_DECISIONS.md` | 121-188 | `f4fc341308d55179df8a1c4ee27c28f3326bd670b1869631048339afa028a021` |
| `docs/OPEN_DECISIONS.md` | 218-254 | `54bcd365fb86835711c88f66385d1ea147084f51449d6fd32dc6083490daa6ce` |
| `docs/README.md` | 121-190 | `b59f22a6f19d048d19601031bf5735a2265200dc7394f89d6105c7814a39fae0` |
| `docs/README.md` | 230-255 | `ec7c59331a82354f7bbab9fd445507025df1e12f575131205d4285c0f15e9d54` |
| `docs/SECURITY_BASELINE.md` | 110-113 | `d91c0898bf794835ff288f517e5d02b664c5169d76c10e646db5c50f8b2826e4` |
| `docs/SECURITY_BASELINE.md` | 169-180 | `1730e271dcc53442d74c5d29b08b2d2b21ed7c10c6da188b307d496b7c3e4782` |

## Reading these records

Several statements in the log were false when written or have since been overtaken, for
example a block that calls the repository verified PRIVATE directly beneath one that
calls it PUBLIC. They are evidence of what was claimed at the time, not of what was true.
The [rebaseline audit](../reviews/AUVEXO_FULL_A_TO_Z_REBASELINE_2026-11-12.md) lists the
contradictions that were found.
