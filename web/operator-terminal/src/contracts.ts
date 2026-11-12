// Presentation validation only; no risk or trading decisions.
// KEYS, ENUMS and PATTERNS mirror contract.schema.json exactly. A test walks the
// committed schema against these tables, so backend drift fails before it renders.
export const KEYS = {
  TerminalSnapshot: [
    "contract_version",
    "system",
    "qualification",
    "reviewed",
    "paper",
    "research",
    "journal",
  ],
  Freshness: ["state", "observed_at", "provenance", "reason"],
  SystemView: [
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
    "freshness",
  ],
  QualificationView: ["phase2_days", "phase4_days", "task", "freshness"],
  ReviewedSummary: [
    "scope",
    "phase2",
    "phase4_observation",
    "phase5",
    "ds03",
    "gateway",
    "broker_transport",
    "permit_issuer",
    "binance_live_derivatives",
  ],
  ReviewedStatement: ["operational", "provenance", "reason", "as_of", "status"],
  PaperView: [
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
  ],
  ReservationView: [
    "intent_hash",
    "state",
    "instrument",
    "quantity",
    "notional",
    "modeled_loss",
  ],
  PositionView: [
    "position_hash",
    "instrument",
    "quantity",
    "entry_price",
    "mark_price",
  ],
  PendingView: ["intent_hash", "state"],
  ResearchView: ["outcomes", "oos", "candidate", "champion", "scope"],
  JournalView: ["freshness", "events"],
  JournalEvent: [
    "sequence",
    "observed_at",
    "reason",
    "intent_hash",
    "evidence_hash",
  ],
} as const;

export const ENUMS = {
  "TerminalSnapshot.contract_version": ["1"],
  "Freshness.state": ["AVAILABLE", "UNKNOWN", "UNAVAILABLE", "STALE"],
  "Freshness.provenance": [
    "LOCAL_DIAGNOSTICS",
    "UNCONNECTED",
    "ISOLATED_SYNTHETIC_PAPER",
    "REVIEWED_ENGINEERING",
  ],
  "Freshness.reason": [
    "CURRENT",
    "NOT_CONNECTED",
    "READ_UNAVAILABLE",
    "SOURCE_STALE",
    "REVIEWED_SUMMARY",
    "NO_EVENTS",
  ],
  "SystemView.contract_version": ["1"],
  "SystemView.build": ["PHASE7_READ_ONLY_FOUNDATION"],
  "SystemView.mode": ["RESEARCH", "BACKTEST", "PAPER"],
  "SystemView.policy": ["phase1.disabled.v1"],
  "SystemView.live_authority": ["LOCKED"],
  "SystemView.api": ["ALIVE"],
  "SystemView.database": ["READY", "NOT_READY"],
  "SystemView.source": ["UNKNOWN"],
  "QualificationView.task": ["UNKNOWN"],
  "ReviewedSummary.scope": ["STATIC_REVIEWED_ENGINEERING_SUMMARY_NOT_MEASURED"],
  "ReviewedStatement.operational": ["UNKNOWN"],
  "ReviewedStatement.provenance": ["REVIEWED_ENGINEERING"],
  "ReviewedStatement.reason": ["REVIEWED_SUMMARY"],
  "ReviewedPhase2.status": ["OPERATIONAL_ACCEPTANCE_OPEN"],
  "ReviewedPhase4Observation.status": [
    "ENGINEERING_ACCEPTED_OPERATIONAL_ACCEPTANCE_OPEN",
  ],
  "ReviewedPhase5.status": ["OFFLINE_ACCEPTED_COMMISSIONING_NOT_STARTED"],
  "ReviewedDs03.status": ["ENGINEERING_ONLY_NO_ACCOUNT"],
  "ReviewedGateway.status": ["SYNTHETIC_OFFLINE_ONLY"],
  "ReviewedBrokerTransport.status": ["NONE"],
  "ReviewedPermitIssuer.status": ["NONE"],
  "ReviewedBinanceLiveDerivatives.status": ["BLOCKED_BY_POLICY"],
  "PaperView.currency": ["USD", "UNCLASSIFIED"],
  "PaperView.kill": ["K0", "K1", "K2", "K3", "K4"],
  "ReservationView.state": ["ACTIVE", "PARTIAL", "UNKNOWN", "RELEASED"],
  "ReservationView.instrument": ["BTCUSDT", "ETHUSDT", "UNCLASSIFIED"],
  "PositionView.instrument": ["BTCUSDT", "ETHUSDT", "UNCLASSIFIED"],
  "PendingView.state": [
    "RESERVED",
    "SENT_PENDING",
    "ACKNOWLEDGED",
    "UNKNOWN",
    "PARTIALLY_FILLED",
  ],
  "ResearchView.outcomes": ["INCONCLUSIVE"],
  "ResearchView.oos": ["BOTH_CONSUMED_FOREVER"],
  "ResearchView.candidate": ["NONE"],
  "ResearchView.champion": ["NONE"],
  "ResearchView.scope": ["REVIEWED_NONPRODUCTION_SUMMARY"],
  "JournalEvent.reason": [
    "AUTHORIZED",
    "DENIED",
    "KILL_STATE",
    "RECONCILIATION",
    "UNKNOWN_ORDER",
    "LOSS_LATCH",
    "DISPATCH_ATTEMPT",
    "OWNER_RESUME",
    "MARK_HEALTH",
    "WRITER_ACQUIRED",
    "OWNER_PIN",
    "EDGE_STATE",
    "DAY_ROLLOVER",
    "INITIALIZED",
    "OTHER",
  ],
} as const;

export const PATTERNS = {
  amount: /^-?(0|[1-9][0-9]{0,17})(\.[0-9]{1,18})?$/,
  hash: /^[0-9a-f]{64}$/,
  version: /^[0-9.]+$/,
  reviewedDate: /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/,
} as const;

type Obj = Record<string, unknown>;
function object(value: unknown, fields: readonly string[]): Obj {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("INVALID_CONTRACT");
  const result = value as Obj;
  if (Object.keys(result).sort().join("|") !== [...fields].sort().join("|"))
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
function string(value: unknown, pattern: RegExp, limit = 128): string {
  if (typeof value !== "string" || value.length > limit || !pattern.test(value))
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
const amount = (v: unknown) => string(v, PATTERNS.amount);
const hash = (v: unknown) => string(v, PATTERNS.hash);
function freshness(value: unknown) {
  const x = object(value, KEYS.Freshness);
  return {
    state: choice(x.state, ENUMS["Freshness.state"]),
    observed_at: optional(x.observed_at, time),
    provenance: choice(x.provenance, ENUMS["Freshness.provenance"]),
    reason: choice(x.reason, ENUMS["Freshness.reason"]),
  };
}
// One static reviewed engineering statement. Never a measurement: the operational
// status is always UNKNOWN and the wording carries its reviewed as-of date.
function reviewed<const T extends string>(
  value: unknown,
  statuses: readonly T[],
) {
  const x = object(value, KEYS.ReviewedStatement);
  return {
    status: choice(x.status, statuses),
    operational: choice(x.operational, ENUMS["ReviewedStatement.operational"]),
    provenance: choice(x.provenance, ENUMS["ReviewedStatement.provenance"]),
    reason: choice(x.reason, ENUMS["ReviewedStatement.reason"]),
    as_of: string(x.as_of, PATTERNS.reviewedDate),
  };
}
export function parseSnapshot(value: unknown) {
  const x = object(value, KEYS.TerminalSnapshot);
  const s = object(x.system, KEYS.SystemView);
  const q = object(x.qualification, KEYS.QualificationView);
  const v = object(x.reviewed, KEYS.ReviewedSummary);
  const p = object(x.paper, KEYS.PaperView);
  const r = object(x.research, KEYS.ResearchView);
  const j = object(x.journal, KEYS.JournalView);
  if (s.execution_enabled !== false) throw Error("INVALID_CONTRACT");
  const paperFreshness = freshness(p.freshness);
  if (
    paperFreshness.state === "UNKNOWN" ||
    paperFreshness.state === "UNAVAILABLE"
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
      ].some((item) => item !== null) ||
      !Array.isArray(p.positions) ||
      p.positions.length ||
      !Array.isArray(p.pending) ||
      p.pending.length ||
      !Array.isArray(p.reservations) ||
      p.reservations.length
    )
      throw Error("INVALID_CONTRACT");
  }
  const outcomes = array(r.outcomes, (item) =>
    choice(item, ENUMS["ResearchView.outcomes"]),
  );
  if (outcomes.length !== 4) throw Error("INVALID_CONTRACT");
  return {
    contract_version: choice(
      x.contract_version,
      ENUMS["TerminalSnapshot.contract_version"],
    ),
    system: {
      contract_version: choice(
        s.contract_version,
        ENUMS["SystemView.contract_version"],
      ),
      version: string(s.version, PATTERNS.version, 32),
      build: choice(s.build, ENUMS["SystemView.build"]),
      mode: choice(s.mode, ENUMS["SystemView.mode"]),
      policy: choice(s.policy, ENUMS["SystemView.policy"]),
      execution_enabled: false,
      live_authority: choice(
        s.live_authority,
        ENUMS["SystemView.live_authority"],
      ),
      api: choice(s.api, ENUMS["SystemView.api"]),
      database: choice(s.database, ENUMS["SystemView.database"]),
      source: choice(s.source, ENUMS["SystemView.source"]),
      freshness: freshness(s.freshness),
    },
    qualification: {
      phase2_days: optional(q.phase2_days, count),
      phase4_days: optional(q.phase4_days, count),
      task: choice(q.task, ENUMS["QualificationView.task"]),
      freshness: freshness(q.freshness),
    },
    reviewed: {
      scope: choice(v.scope, ENUMS["ReviewedSummary.scope"]),
      phase2: reviewed(v.phase2, ENUMS["ReviewedPhase2.status"]),
      phase4_observation: reviewed(
        v.phase4_observation,
        ENUMS["ReviewedPhase4Observation.status"],
      ),
      phase5: reviewed(v.phase5, ENUMS["ReviewedPhase5.status"]),
      ds03: reviewed(v.ds03, ENUMS["ReviewedDs03.status"]),
      gateway: reviewed(v.gateway, ENUMS["ReviewedGateway.status"]),
      broker_transport: reviewed(
        v.broker_transport,
        ENUMS["ReviewedBrokerTransport.status"],
      ),
      permit_issuer: reviewed(
        v.permit_issuer,
        ENUMS["ReviewedPermitIssuer.status"],
      ),
      binance_live_derivatives: reviewed(
        v.binance_live_derivatives,
        ENUMS["ReviewedBinanceLiveDerivatives.status"],
      ),
    },
    paper: {
      freshness: paperFreshness,
      balance: optional(p.balance, amount),
      equity: optional(p.equity, amount),
      currency: optional(p.currency, (item) =>
        choice(item, ENUMS["PaperView.currency"]),
      ),
      kill: optional(p.kill, (item) => choice(item, ENUMS["PaperView.kill"])),
      reconciled: optional(p.reconciled, bool),
      unknown_orders: optional(p.unknown_orders, bool),
      active_reservations: optional(p.active_reservations, count),
      reservations: array(p.reservations, (item) => {
        const a = object(item, KEYS.ReservationView);
        return {
          intent_hash: hash(a.intent_hash),
          state: choice(a.state, ENUMS["ReservationView.state"]),
          instrument: choice(a.instrument, ENUMS["ReservationView.instrument"]),
          quantity: amount(a.quantity),
          notional: amount(a.notional),
          modeled_loss: amount(a.modeled_loss),
        };
      }),
      positions: array(p.positions, (item) => {
        const a = object(item, KEYS.PositionView);
        return {
          position_hash: hash(a.position_hash),
          instrument: choice(a.instrument, ENUMS["PositionView.instrument"]),
          quantity: amount(a.quantity),
          entry_price: amount(a.entry_price),
          mark_price: amount(a.mark_price),
        };
      }),
      pending: array(p.pending, (item) => {
        const a = object(item, KEYS.PendingView);
        return {
          intent_hash: hash(a.intent_hash),
          state: choice(a.state, ENUMS["PendingView.state"]),
        };
      }),
    },
    research: {
      outcomes,
      oos: choice(r.oos, ENUMS["ResearchView.oos"]),
      candidate: choice(r.candidate, ENUMS["ResearchView.candidate"]),
      champion: choice(r.champion, ENUMS["ResearchView.champion"]),
      scope: choice(r.scope, ENUMS["ResearchView.scope"]),
    },
    journal: {
      freshness: freshness(j.freshness),
      events: array(j.events, (item) => {
        const a = object(item, KEYS.JournalEvent);
        return {
          sequence: sequence(a.sequence),
          observed_at: time(a.observed_at),
          reason: choice(a.reason, ENUMS["JournalEvent.reason"]),
          intent_hash: optional(a.intent_hash, hash),
          evidence_hash: hash(a.evidence_hash),
        };
      }),
    },
  };
}
export type Snapshot = ReturnType<typeof parseSnapshot>;
export type Freshness = Snapshot["system"]["freshness"];
export type JournalReason = Snapshot["journal"]["events"][number]["reason"];
