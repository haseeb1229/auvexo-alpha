// Presentation validation only; no risk or trading decisions.
type Obj = Record<string, unknown>;
function object(value: unknown, fields: string[]): Obj {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("INVALID_CONTRACT");
  const result = value as Obj;
  if (Object.keys(result).sort().join("|") !== fields.sort().join("|"))
    throw Error("INVALID_CONTRACT");
  return result;
}
function choice<const T extends string>(
  value: unknown,
  choices: readonly T[],
): T {
  if (typeof value !== "string" || !choices.includes(value as T))
    throw Error("INVALID_CONTRACT");
  return value as T;
}
function string(value: unknown, pattern: RegExp): string {
  if (typeof value !== "string" || value.length > 128 || !pattern.test(value))
    throw Error("INVALID_CONTRACT");
  return value;
}
function optional<T>(value: unknown, parse: (v: unknown) => T): T | null {
  return value === null ? null : parse(value);
}
function bool(value: unknown): boolean {
  if (typeof value !== "boolean") throw Error("INVALID_CONTRACT");
  return value;
}
function count(value: unknown): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 0 ||
    value > 10000
  )
    throw Error("INVALID_CONTRACT");
  return value;
}
function sequence(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0)
    throw Error("INVALID_CONTRACT");
  return value;
}
function array<T>(value: unknown, parse: (v: unknown) => T): T[] {
  if (!Array.isArray(value) || value.length > 100)
    throw Error("INVALID_CONTRACT");
  return value.map(parse);
}
function time(value: unknown): string {
  const s = string(
    value,
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/,
  );
  const parsed = Date.parse(s);
  if (
    !Number.isFinite(parsed) ||
    new Date(parsed).toISOString().slice(0, 19) !== s.slice(0, 19)
  )
    throw Error("INVALID_CONTRACT");
  return s;
}
const amount = (v: unknown) =>
  string(v, /^-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?$/);
const hash = (v: unknown) => string(v, /^[0-9a-f]{64}$/);
function freshness(value: unknown) {
  const x = object(value, ["state", "observed_at", "provenance", "reason"]);
  return {
    state: choice(x.state, ["AVAILABLE", "UNKNOWN", "UNAVAILABLE", "STALE"]),
    observed_at: optional(x.observed_at, time),
    provenance: choice(x.provenance, [
      "LOCAL_DIAGNOSTICS",
      "UNCONNECTED",
      "ISOLATED_SYNTHETIC_PAPER",
      "REVIEWED_ENGINEERING",
    ]),
    reason: choice(x.reason, [
      "CURRENT",
      "NOT_CONNECTED",
      "READ_UNAVAILABLE",
      "SOURCE_STALE",
      "REVIEWED_SUMMARY",
    ]),
  };
}
export function parseSnapshot(value: unknown) {
  const x = object(value, [
    "contract_version",
    "system",
    "qualification",
    "paper",
    "research",
    "journal",
  ]);
  const s = object(x.system, [
    "contract_version",
    "version",
    "build",
    "mode",
    "policy",
    "execution_enabled",
    "live_authority",
    "api",
    "database",
    "source",
    "gateway",
    "freshness",
  ]);
  const q = object(x.qualification, [
    "phase2",
    "phase2_days",
    "phase4",
    "phase4_days",
    "task",
    "phase5",
    "ds03",
    "freshness",
  ]);
  const p = object(x.paper, [
    "freshness",
    "balance",
    "equity",
    "currency",
    "kill",
    "reconciled",
    "unknown_orders",
    "active_reservations",
    "reservations",
    "positions",
    "pending",
  ]);
  const r = object(x.research, [
    "outcomes",
    "oos",
    "candidate",
    "champion",
    "scope",
  ]);
  const j = object(x.journal, ["freshness", "events"]);
  if (s.execution_enabled !== false) throw Error("INVALID_CONTRACT");
  if (
    (p.freshness as { state?: unknown })?.state === "UNKNOWN" ||
    (p.freshness as { state?: unknown })?.state === "UNAVAILABLE"
  ) {
    if (
      [
        p.balance,
        p.equity,
        p.currency,
        p.kill,
        p.reconciled,
        p.unknown_orders,
        p.active_reservations,
      ].some((v) => v !== null) ||
      !Array.isArray(p.positions) ||
      p.positions.length ||
      !Array.isArray(p.pending) ||
      p.pending.length ||
      !Array.isArray(p.reservations) ||
      p.reservations.length
    )
      throw Error("INVALID_CONTRACT");
  }
  const outcomes = array(r.outcomes, (v) => choice(v, ["INCONCLUSIVE"]));
  if (outcomes.length !== 4) throw Error("INVALID_CONTRACT");
  return {
    contract_version: choice(x.contract_version, ["1"]),
    system: {
      contract_version: choice(s.contract_version, ["1"]),
      version: string(s.version, /^[0-9.]+$/),
      build: choice(s.build, ["PHASE7_READ_ONLY_FOUNDATION"]),
      mode: choice(s.mode, [
        "RESEARCH",
        "BACKTEST",
        "PAPER",
        "DEMO",
        "SHADOW",
        "LIVE_LIMITED",
        "LIVE",
      ]),
      policy: choice(s.policy, ["phase1.disabled.v1"]),
      execution_enabled: false,
      live_authority: choice(s.live_authority, ["LOCKED"]),
      api: choice(s.api, ["ALIVE"]),
      database: choice(s.database, ["READY", "NOT_READY"]),
      source: choice(s.source, ["UNKNOWN"]),
      gateway: choice(s.gateway, ["SYNTHETIC_OFFLINE_ACCEPTED"]),
      freshness: freshness(s.freshness),
    },
    qualification: {
      phase2: choice(q.phase2, ["OPERATIONAL_OPEN"]),
      phase2_days: optional(q.phase2_days, count),
      phase4: choice(q.phase4, ["OBSERVATION_ACTIVE_OPERATIONAL_OPEN"]),
      phase4_days: optional(q.phase4_days, count),
      task: choice(q.task, ["UNKNOWN"]),
      phase5: choice(q.phase5, ["OFFLINE_ACCEPTED_COMMISSIONING_NOT_STARTED"]),
      ds03: choice(q.ds03, ["BLOCKED"]),
      freshness: freshness(q.freshness),
    },
    paper: {
      freshness: freshness(p.freshness),
      balance: optional(p.balance, amount),
      equity: optional(p.equity, amount),
      currency: optional(p.currency, (v) => choice(v, ["USD", "UNCLASSIFIED"])),
      kill: optional(p.kill, (v) => choice(v, ["K0", "K1", "K2", "K3", "K4"])),
      reconciled: optional(p.reconciled, bool),
      unknown_orders: optional(p.unknown_orders, bool),
      active_reservations: optional(p.active_reservations, count),
      reservations: array(p.reservations, (v) => {
        const a = object(v, [
          "intent_hash",
          "state",
          "instrument",
          "quantity",
          "notional",
          "modeled_loss",
        ]);
        return {
          intent_hash: hash(a.intent_hash),
          state: choice(a.state, ["ACTIVE", "PARTIAL", "UNKNOWN", "RELEASED"]),
          instrument: choice(a.instrument, [
            "BTCUSDT",
            "ETHUSDT",
            "UNCLASSIFIED",
          ]),
          quantity: amount(a.quantity),
          notional: amount(a.notional),
          modeled_loss: amount(a.modeled_loss),
        };
      }),
      positions: array(p.positions, (v) => {
        const a = object(v, [
          "position_hash",
          "instrument",
          "quantity",
          "entry_price",
          "mark_price",
        ]);
        return {
          position_hash: hash(a.position_hash),
          instrument: choice(a.instrument, [
            "BTCUSDT",
            "ETHUSDT",
            "UNCLASSIFIED",
          ]),
          quantity: amount(a.quantity),
          entry_price: amount(a.entry_price),
          mark_price: amount(a.mark_price),
        };
      }),
      pending: array(p.pending, (v) => {
        const a = object(v, ["intent_hash", "state"]);
        return {
          intent_hash: hash(a.intent_hash),
          state: choice(a.state, [
            "RESERVED",
            "SENT_PENDING",
            "ACKNOWLEDGED",
            "UNKNOWN",
            "PARTIALLY_FILLED",
          ]),
        };
      }),
    },
    research: {
      outcomes,
      oos: choice(r.oos, ["BOTH_CONSUMED_FOREVER"]),
      candidate: choice(r.candidate, ["NONE"]),
      champion: choice(r.champion, ["NONE"]),
      scope: choice(r.scope, ["REVIEWED_NONPRODUCTION_SUMMARY"]),
    },
    journal: {
      freshness: freshness(j.freshness),
      events: array(j.events, (v) => {
        const a = object(v, [
          "sequence",
          "observed_at",
          "reason",
          "intent_hash",
          "evidence_hash",
          "decision_hash",
        ]);
        return {
          sequence: sequence(a.sequence),
          observed_at: time(a.observed_at),
          reason: choice(a.reason, [
            "AUTHORIZED",
            "DENIED",
            "RECONCILED",
            "KILL_CHANGED",
            "OTHER_RECORDED_EVENT",
          ]),
          intent_hash: optional(a.intent_hash, hash),
          evidence_hash: hash(a.evidence_hash),
          decision_hash: optional(a.decision_hash, hash),
        };
      }),
    },
  };
}
export type Snapshot = ReturnType<typeof parseSnapshot>;
