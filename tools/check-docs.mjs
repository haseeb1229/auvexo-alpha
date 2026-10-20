import { readFileSync, readdirSync, existsSync, statSync } from 'node:fs';
import { resolve, dirname, relative, extname } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';

// Documentation QA only; no network, package dependencies or trading operations.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const errors = [];
const check = (condition, message) => { if (!condition) errors.push(message); };
const read = (path) => readFileSync(resolve(root, path), 'utf8');
const required = [
  'README.md', 'AGENTS.md', 'CLAUDE.md', '.gitignore', '.gitattributes',
  'docs/README.md', 'docs/PRODUCT_CONSTITUTION.md', 'docs/REQUIREMENTS_REGISTER.md',
  'docs/ARCHITECTURE.md', 'docs/AGENT_ARCHITECTURE.md', 'docs/RESEARCH_AND_VALIDATION.md',
  'docs/RISK_AND_CAPITAL_POLICY.md', 'docs/EXECUTION_AND_VENUE_POLICY.md',
  'docs/DATA_ARCHITECTURE.md', 'docs/DATA_SOURCE_REGISTER.md', 'docs/SECURITY_BASELINE.md',
  'docs/engineering/ENGINEERING_RULES.md', 'docs/PERFORMANCE_AND_RELIABILITY.md',
  'docs/OPERATIONS_AND_RECOVERY.md', 'docs/OPEN_SOURCE_REUSE_REVIEW.md',
  'docs/ROADMAP.md', 'docs/OPEN_DECISIONS.md', 'docs/adr/README.md',
  'docs/HANDOFF_TEMPLATE.md', 'docs/PHASE_0_HANDOFF.md', 'docs/PHASE_0_SELF_REVIEW.md',
  'docs/CLIENT_AND_UX_DIRECTION.md', 'docs/validation/PHASE_0_CHECKS.md',
  'docs/reference/PHASE_0_BRIEF.txt', 'tools/check-docs.mjs',
  'docs/reference/PHASE_1_BRIEF.txt', 'docs/phase1/ACCEPTANCE_TESTS.md',
  'docs/phase1/SETUP.md', 'docs/phase1/TOOLCHAIN.md', 'docs/phase1/IMPLEMENTATION.md',
  'docs/phase1/VERIFICATION.md', 'docs/phase1/HANDOFF.md', 'pyproject.toml', 'uv.lock',
  'docs/reference/PHASE_2_BRIEF.txt', 'docs/phase2/ACCEPTANCE_TESTS.md',
  'docs/phase2/IMPLEMENTATION.md', 'docs/phase2/SOURCES_AND_RIGHTS.md',
  'docs/phase2/QUALITY_AND_COVERAGE.md', 'docs/phase2/SETUP_AND_RECOVERY.md',
  'docs/phase2/VERIFICATION.md', 'docs/phase2/HANDOFF.md',
  'docs/reference/BASELINE_CORRECTION_BRIEF.txt',
  'docs/adr/013-source-specific-acceptance.md',
  'docs/amendments/BASELINE_CORRECTION_HANDOFF.md',
  'docs/amendments/DEPENDENCY_MATURITY.md', 'docs/amendments/SCHEDULER_2300.md',
  'docs/reference/PHASE_3_BRIEF.txt', 'docs/reference/PHASE_3_RESUME_BRIEF.txt',
  'docs/phase3/ACCEPTANCE_TESTS.md', 'docs/phase3/DATA_PLAN.md', 'docs/phase3/DATA_PLAN_V2.md',
  'docs/phase3/evidence/provider-outage-diagnosis.json', 'docs/adr/014-nonproduction-research.md',
  'docs/phase3/IMPLEMENTATION.md', 'docs/phase3/VERIFICATION.md', 'docs/phase3/HANDOFF.md',
  'docs/reviews/PHASE_3_INDEPENDENT_ACCEPTANCE.md',
  'docs/phase4/ACCEPTANCE_TESTS.md', 'docs/adr/015-paper-risk-core.md',
  'docs/adr/022-paper-performance-slo.md',
  'docs/reference/PHASE_4_PERFORMANCE_GOVERNANCE_BRIEF.txt',
  'docs/reference/PHASE_4_ACCEPTANCE_TESTS_ORIGINAL_20261018.txt',
  'docs/adr/023-paper-observation-qualification.md',
  'docs/phase4/OBSERVATION_ACCEPTANCE.md', 'docs/phase4/OBSERVATION_RUNBOOK.md',
  'docs/reviews/PHASE_4_CHECKPOINT_A_INDEPENDENT_ACCEPTANCE.md',
  'docs/reference/PHASE_4_CHECKPOINT_B_BRIEF.txt',
];
for (const path of required) check(existsSync(resolve(root, path)), `Missing: ${path}`);
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
check(read('AGENTS.md') === read('CLAUDE.md'), 'AGENTS.md and CLAUDE.md differ');
for (const [path, expected] of [
  ['docs/adr/023-paper-observation-qualification.md', 'a3d478abe514f9ac9ba041aa71337fbb6950f5320791f5f1f598e278dba63bb4'],
  ['docs/phase4/OBSERVATION_ACCEPTANCE.md', '429ac2af998951945ca3694502550b58dd77534bb31ba206a509fbc0169ca684'],
  ['docs/phase4/OBSERVATION_RUNBOOK.md', '1a949ced0028568a7d0823299904c1288d8e564f4fadb80b3ea9f3d8afce22a8'],
]) {
  check(createHash('sha256').update(readFileSync(resolve(root, path))).digest('hex') === expected,
    `Frozen Checkpoint B requirement changed; explicit amendment required: ${path}`);
}
// ADR-022 explicitly supersedes the transaction hard-MAX interpretation. Keep the
// original freeze byte-verified as well as the dated amended child requirement.
check(createHash('sha256').update(readFileSync(resolve(root, 'docs/reference/PHASE_4_ACCEPTANCE_TESTS_ORIGINAL_20261018.txt'))).digest('hex') === '051da385ebc22f1c5eb98933c876a2338b7e4005f23913e8ffd0ffa070cf1d1a', 'Original Phase 4 freeze changed');
check(createHash('sha256').update(readFileSync(resolve(root, 'docs/phase4/ACCEPTANCE_TESTS.md'))).digest('hex') === 'c21f27087bbf79ad5dbcaefb792cbe55f57b567fe7549481a9302e12a1dba213', 'ADR-022 amended Phase 4 requirements changed; explicit amendment required');
check(createHash('sha256').update(readFileSync(resolve(root, 'tools/benchmark_paper.py'))).digest('hex') === '7c1da5f753dd899a430e3a713f06d79d049eae491b9d9715cb9e761f663bd4fd', 'Historical PAPER benchmark v1 changed; no rerun/workload amendment authorized');
check(createHash('sha256').update(readFileSync(resolve(root, 'docs/phase3/DATA_PLAN.md'))).digest('hex') === '82d189d51b01457e8141455d02addafcdbd690e8a73f4f4996eefcc7fbd2b8a4', 'Historical Phase 3 V1 plan changed');
check(createHash('sha256').update(readFileSync(resolve(root, 'docs/phase3/DATA_PLAN_V2.md'))).digest('hex') === '4e073254600d499421893c4823426980756f6f31ea745c0805de9f25b0681cce', 'Frozen Phase 3 V2 amendment changed');
const digest = createHash('sha256').update(readFileSync(resolve(root, 'docs/reference/PHASE_0_BRIEF.txt'))).digest('hex');
check(digest === '1a3ffff5ed19d09ea48e80d4591ccaddfb09e9da64bde1ce3ce31fbd69b70fb2', 'Archived brief hash changed');
check(createHash('sha256').update(readFileSync(resolve(root, 'docs/reference/PHASE_1_BRIEF.txt'))).digest('hex') === 'c67380a3ead8744b85f30447b8cd00b362813abe185610221f975306d840b98b', 'Archived Phase 1 brief hash changed');

check(createHash('sha256').update(readFileSync(resolve(root, 'docs/reference/PHASE_2_BRIEF.txt'))).digest('hex') === 'f730821f0bc78faf90cb598579b1c1e93109c3d9b59bdda6b2395300062a85a5', 'Archived Phase 2 brief hash changed');

const files = [];
function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (['.git', '.local', '.venv', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.hypothesis', 'build', 'dist'].includes(entry.name) || entry.name.endsWith('.egg-info')) continue;
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) walk(full);
    else files.push(relative(root, full).replaceAll('\\', '/'));
  }
}
walk(root);
const markdown = files.filter(p => p.endsWith('.md'));
let links = 0;
for (const path of markdown) {
  const content = read(path);
  check(content.startsWith('# '), `Missing title: ${path}`);
  check(!content.includes('\uFFFD'), `Invalid UTF-8 replacement character: ${path}`);
  check(!/\b(?:TBD|FIXME|PLACEHOLDER)\b/.test(content.replaceAll('TODO/FIXME', 'tracked-work')), `Unresolved placeholder: ${path}`);
  check((content.match(/^```/gm) ?? []).length % 2 === 0, `Unbalanced code fence: ${path}`);
  for (const match of content.matchAll(/\[[^\]\n]+\]\(([^)\n]+)\)/g)) {
    const target = match[1].replace(/^<|>$/g, '').split('#')[0];
    if (!target || /^[a-z]+:/i.test(target)) continue;
    const full = resolve(dirname(resolve(root, path)), decodeURIComponent(target));
    const rel = relative(root, full);
    check(!rel.startsWith('..') && !resolve(full).startsWith('\\\\'), `Link leaves repo: ${path}: ${target}`);
    check(existsSync(full), `Broken local link: ${path}: ${target}`);
    links++;
  }
}
const register = read('docs/REQUIREMENTS_REGISTER.md');
const phase3 = read('docs/phase3/ACCEPTANCE_TESTS.md');
const phase4 = read('docs/phase4/ACCEPTANCE_TESTS.md');
for (const id of ['R-002-P4-01', 'R-022-P4-01', 'R-022-P4-02', 'R-022-P4-03', 'R-021-P4-01', 'R-021-P4-02', 'R-006-P4-01', 'R-006-P4-02', 'R-022-P4-04', 'R-008-P4-01', 'R-023-P4-01', 'R-024-P4-01', 'R-025-P4-01']) {
  check(phase4.includes(`| ${id} |`), `Missing frozen Phase 4 child: ${id}`);
}
for (const id of ['R-014-P3-01', 'R-014-P3-02', 'R-005-P3-01', 'R-005-P3-02', 'R-006-P3-01', 'R-005-P3-03', 'R-007-P3-01', 'R-015-P3-01', 'R-025-P3-01', 'R-022-P3-01']) {
  check(phase3.includes(`| ${id} |`), `Missing stable Phase 3 child: ${id}`);
}
for (let i = 0; i < 40; i++) {
  const id = `R-${String(i).padStart(3, '0')}`;
  check(register.includes(`| ${id} / ${i} |`), `Missing brief section mapping: ${id}`);
}
for (const id of ['R-035-BA-01', 'R-014-BA-01', 'R-014-BA-02', 'R-015-BA-01', 'R-018-BA-01', 'R-031-BA-01', 'R-029-BA-01']) {
  check(register.includes(`| ${id} |`), `Missing amendment mapping: ${id}`);
}
const decisions = read('docs/OPEN_DECISIONS.md');
for (let i = 1; i <= 15; i++) check(decisions.includes(`| OD-${String(i).padStart(2, '0')} |`), `Missing OD-${i}`);
const adrFiles = files.filter(p => /^docs\/adr\/\d{3}-.*\.md$/.test(p));
check(adrFiles.length >= 10, 'Expected original ten ADRs plus any phase decisions');
for (const path of adrFiles) {
  for (const field of ['Status:', 'Requirements:', '## Context', '## Decision', '## Alternatives', '## Consequences', '## Validation', '## Review point']) {
    check(read(path).includes(field), `ADR missing ${field}: ${path}`);
  }
}
const roadmap = read('docs/ROADMAP.md');
for (let i = 0; i <= 9; i++) {
  const phase = roadmap.split(`## Phase ${i} `)[1]?.split('\n## Phase ')[0] ?? '';
  check(phase.length > 0, `Missing Phase ${i}`);
  for (const field of ['Purpose/scope:', 'Non-scope:', 'Dependencies:', 'Outputs:', 'Tests/security:', 'Real-environment proof:', 'Exit:', 'Rollback/recovery:']) {
    check(phase.includes(field), `Phase ${i} missing ${field}`);
  }
}
for (const path of files) {
  const allowed = ['.md', '.txt', '.py', '.toml', '.ps1', '.json', '.yml', '.yaml', '.ini', '.mako'].includes(extname(path)) || ['.gitignore', '.gitattributes', '.python-version', 'uv.lock', 'tools/check-docs.mjs', 'src/auvexo_alpha/py.typed'].includes(path);
  check(allowed, `Unexpected repository file: ${path}`);
  check(statSync(resolve(root, path)).size < 1_000_000, `Unexpected large file: ${path}`);
  if (['.md', '.txt'].includes(extname(path))) {
    // High-signal patterns only; this does not replace a full secret scanner in Phase 1.
    check(!/(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|AKIA[A-Z0-9]{16})/.test(read(path)), `Possible secret: ${path}`);
  }
}
if (errors.length) {
  console.error(`FAIL: ${errors.length} issue(s)\n${errors.join('\n')}`);
  process.exit(1);
}
console.log(`PASS: ${files.length} repository files; ${markdown.length} Markdown files; ${links} local links; 40 brief mappings; 15 open decisions; ${adrFiles.length} ADRs; 10 roadmap phases.`);
console.log('PASS: aligned agent instructions, exact brief hash, document structure, scope allowlist and high-signal secret patterns.');
console.log('LIMIT: no external-link, full secret/security, runtime, trading, performance or profitability certification.');
