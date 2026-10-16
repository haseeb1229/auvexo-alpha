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
];
for (const path of required) check(existsSync(resolve(root, path)), `Missing: ${path}`);
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
check(read('AGENTS.md') === read('CLAUDE.md'), 'AGENTS.md and CLAUDE.md differ');
const digest = createHash('sha256').update(readFileSync(resolve(root, 'docs/reference/PHASE_0_BRIEF.txt'))).digest('hex');
check(digest === '1a3ffff5ed19d09ea48e80d4591ccaddfb09e9da64bde1ce3ce31fbd69b70fb2', 'Archived brief hash changed');
check(createHash('sha256').update(readFileSync(resolve(root, 'docs/reference/PHASE_1_BRIEF.txt'))).digest('hex') === 'c67380a3ead8744b85f30447b8cd00b362813abe185610221f975306d840b98b', 'Archived Phase 1 brief hash changed');

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
for (let i = 0; i < 40; i++) {
  const id = `R-${String(i).padStart(3, '0')}`;
  check(register.includes(`| ${id} / ${i} |`), `Missing brief section mapping: ${id}`);
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
