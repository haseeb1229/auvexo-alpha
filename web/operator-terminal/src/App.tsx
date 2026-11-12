import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ReadFailure,
  type ReadFailureCode,
  readSnapshot,
  tokenProblem,
} from "./client";
import type { Freshness, JournalReason, Snapshot } from "./contracts";

export const areas = [
  "Command Center",
  "Risk / PAPER",
  "Research",
  "Journal / evidence",
  "System Health",
] as const;
export type Area = (typeof areas)[number];

export const POLL_MS = 30_000;
export const STALE_MS = 45_000;
export const IDLE_MS = 15 * 60_000;
export const IDLE_WARNING_MS = 60_000;

// LOADING until the first attempt completes; STALE when the last attempt succeeded
// but no read has succeeded within STALE_MS; otherwise the last attempt's result.
export type ReadStatus =
  | "LOADING"
  | "CONNECTED"
  | "STALE"
  | Exclude<ReadFailureCode, "UNAUTHORIZED">;
const READ_LABEL: Record<ReadStatus, string> = {
  LOADING: "LOADING",
  CONNECTED: "CONNECTED",
  STALE: "STALE",
  DISCONNECTED: "DISCONNECTED",
  UNAVAILABLE: "BACKEND READ UNAVAILABLE",
  INVALID_CONTRACT: "CONTRACT MISMATCH",
  ORIGIN_REFUSED: "ORIGIN REFUSED",
};

const words = (text: string) => text.replaceAll("_", " ");
const two = (value: number) => String(value).padStart(2, "0");
export function utcClock(at: number): string {
  const d = new Date(at);
  return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())} UTC`;
}
export function elapsed(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  if (seconds < 0) return "ahead of this clock";
  if (seconds < 120) return `${seconds} s ago`;
  if (seconds < 7200) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 172800) return `${Math.floor(seconds / 3600)} h ago`;
  return `${Math.floor(seconds / 86400)} d ago`;
}
function Stamp({ iso, now }: { iso: string | null; now: number }) {
  if (iso === null) return <>UNKNOWN</>;
  const at = Date.parse(iso);
  // Older than a day: the date is shown as well, so a clock time is never ambiguous.
  const day = now - at >= 86_400_000 ? `${iso.slice(0, 10)} ` : "";
  return (
    <time dateTime={iso} title={iso}>
      {day}
      {utcClock(at)} ({elapsed(now - at)})
    </time>
  );
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="facts">
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

type Reviewed = Snapshot["reviewed"];
type ReviewedItem = Reviewed[Exclude<keyof Reviewed, "scope">];
// Plain wording for each reviewed status code. Static presentation text only.
const REVIEWED_TEXT: Record<ReviewedItem["status"], string> = {
  OPERATIONAL_ACCEPTANCE_OPEN: "Operational acceptance OPEN (not accepted)",
  ENGINEERING_ACCEPTED_OPERATIONAL_ACCEPTANCE_OPEN:
    "Engineering accepted; operational acceptance OPEN (not accepted)",
  OFFLINE_ACCEPTED_COMMISSIONING_NOT_STARTED:
    "Offline engineering accepted; commissioning NOT STARTED",
  ENGINEERING_ONLY_NO_ACCOUNT:
    "Engineering only: read-only adapter code exists; no account, session, rights or qualification",
  SYNTHETIC_OFFLINE_ONLY:
    "Synthetic and offline only; not connected to any broker",
  NONE: "NONE: does not exist",
  BLOCKED_BY_POLICY: "BLOCKED BY POLICY",
};
function ReviewedTag({ item }: { item: ReviewedItem }) {
  return (
    <span className="tag">reviewed static summary · as of {item.as_of}</span>
  );
}
function ReviewedList({
  rows,
  measured,
}: {
  rows: [string, ReviewedItem, string?][];
  measured: boolean;
}) {
  return (
    <ul className="reviewed">
      {rows.map(([subject, item, text]) => (
        <li key={subject}>
          <strong>{subject}</strong>
          <span>{text ?? REVIEWED_TEXT[item.status]}</span>
          {measured && (
            <span>
              Operational status {item.operational} (not connected; not measured
              by this terminal)
            </span>
          )}
          <ReviewedTag item={item} />
        </li>
      ))}
    </ul>
  );
}

type JournalGroup = "KILL" | "RECONCILE" | "DECISION";
const JOURNAL_GROUP: Record<JournalReason, JournalGroup | null> = {
  KILL_STATE: "KILL",
  LOSS_LATCH: "KILL",
  OWNER_RESUME: "KILL",
  WRITER_ACQUIRED: "KILL",
  RECONCILIATION: "RECONCILE",
  UNKNOWN_ORDER: "RECONCILE",
  MARK_HEALTH: "RECONCILE",
  AUTHORIZED: "DECISION",
  DENIED: "DECISION",
  DISPATCH_ATTEMPT: "DECISION",
  OWNER_PIN: null,
  EDGE_STATE: null,
  DAY_ROLLOVER: null,
  INITIALIZED: null,
  OTHER: null,
};
// Text markers, so the three safety events never depend on colour or position.
const JOURNAL_MARKER: Partial<Record<JournalReason, string>> = {
  KILL_STATE: "KILL EVENT",
  UNKNOWN_ORDER: "UNKNOWN OUTCOME",
  LOSS_LATCH: "LOSS BREACH",
};
const JOURNAL_FILTERS = [
  ["All", null],
  ["Kill", "KILL"],
  ["Reconcile", "RECONCILE"],
  ["Decisions", "DECISION"],
] as const;
type JournalFilter = (typeof JOURNAL_FILTERS)[number][1];

export function Terminal({
  data,
  area,
  retained = false,
  now = Date.now(),
  heading,
  children,
}: {
  data: Snapshot | null;
  area: Area;
  retained?: boolean;
  now?: number;
  heading?: RefObject<HTMLHeadingElement | null>;
  children?: ReactNode;
}) {
  const [filter, setFilter] = useState<JournalFilter>(null);
  // A retained snapshot is never current: every freshness reads STALE.
  const state = (f: Freshness) => (retained ? "STALE" : f.state);
  const source = (f: Freshness) =>
    `${state(f)} · ${words(f.provenance)} · ${retained ? "RETAINED SNAPSHOT" : words(f.reason)}`;
  return (
    <section aria-labelledby="view-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">OWNER VISIBILITY</span>
          <h1 id="view-title" tabIndex={-1} ref={heading}>
            {area}
          </h1>
        </div>
        <span className="pill">READ ONLY</span>
      </div>
      {children}
      {data && area === "Command Center" && (
        <CommandCenter data={data} state={state} />
      )}
      {data && area === "Risk / PAPER" && (
        <Risk data={data} now={now} state={state} source={source} />
      )}
      {data && area === "Research" && <Research data={data} />}
      {data && area === "Journal / evidence" && (
        <Journal
          data={data}
          now={now}
          state={state}
          source={source}
          filter={filter}
          setFilter={setFilter}
        />
      )}
      {data && area === "System Health" && (
        <Health
          data={data}
          now={now}
          retained={retained}
          state={state}
          source={source}
        />
      )}
    </section>
  );
}

type ViewProps = { data: Snapshot; state: (f: Freshness) => string };
type SourcedProps = ViewProps & {
  now: number;
  source: (f: Freshness) => string;
};

function CommandCenter({ data, state }: ViewProps) {
  const q = data.qualification;
  const v = data.reviewed;
  return (
    <>
      <div className="cards">
        <article>
          <span className="eyebrow">ENGINEERING</span>
          <h2>Reviewed static summary</h2>
          <p>
            Engineering statements below are reviewed wording, not measurements.
            They grant no operational readiness.
          </p>
        </article>
        <article>
          <span className="eyebrow">OPERATIONAL QUALIFICATION</span>
          <h2>Operational status {state(q.freshness)}</h2>
          <p>
            {words(q.freshness.provenance)} · {words(q.freshness.reason)}
          </p>
          <p>Phase 4 genuine dates: {q.phase4_days ?? "UNKNOWN"}</p>
          <p>Phase 2 genuine dates: {q.phase2_days ?? "UNKNOWN"}</p>
          <p>Observation task: {q.task}</p>
        </article>
        <article>
          <span className="eyebrow">FINANCIAL AUTHORITY</span>
          <h2>Execution DISABLED</h2>
          <p>LIVE {data.system.live_authority} · no money capability</p>
        </article>
      </div>
      <Facts
        rows={[
          ["Build", `${data.system.version} · ${words(data.system.build)}`],
          ["Configured mode (label only)", data.system.mode],
          ["Policy", data.system.policy],
          ["Source freshness", data.system.source],
          ["Qualification projection", state(q.freshness)],
        ]}
      />
      <h2>Reviewed engineering summary</h2>
      <p className="notice">
        {words(v.scope)}. Static wording with its review date. Nothing in this
        block is read from an operational system.
      </p>
      <ReviewedList
        measured
        rows={[
          ["Phase 2", v.phase2],
          ["Phase 4 observation", v.phase4_observation],
          ["Phase 5", v.phase5],
          ["Offline gateway", v.gateway],
        ]}
      />
      <h2>Blocked and not authorised</h2>
      <ReviewedList
        measured={false}
        rows={[
          ["Broker order transport", v.broker_transport],
          ["Permit issuer", v.permit_issuer],
          ["Binance live derivatives", v.binance_live_derivatives],
          ["DS-03", v.ds03],
          ["Phase 5 commissioning", v.phase5, "NOT STARTED"],
        ]}
      />
    </>
  );
}

function Risk({ data, now, state, source }: SourcedProps) {
  const p = data.paper;
  const current = state(p.freshness) === "AVAILABLE";
  return (
    <>
      <p className="notice">Virtual PAPER projection · {source(p.freshness)}</p>
      <Facts
        rows={[
          ["Balance", p.balance ?? "UNKNOWN"],
          ["Equity", p.equity ?? "UNKNOWN"],
          ["Currency", p.currency ?? "UNKNOWN"],
          ["Kill level", p.kill ?? "UNKNOWN"],
          [
            "Reconciled",
            p.reconciled === null ? "UNKNOWN" : p.reconciled ? "YES" : "NO",
          ],
          [
            "Unresolved orders",
            p.unknown_orders === null
              ? "UNKNOWN"
              : p.unknown_orders
                ? "UNKNOWN OUTCOMES PRESENT"
                : "NONE REPORTED",
          ],
          ["Active reservations", String(p.active_reservations ?? "UNKNOWN")],
          [
            "Observed at",
            <Stamp key="at" iso={p.freshness.observed_at} now={now} />,
          ],
        ]}
      />
      <h2>Positions</h2>
      {p.positions.length ? (
        <div className="table-scroll">
          <table>
            <caption>Read-only virtual positions</caption>
            <thead>
              <tr>
                <th scope="col">Instrument</th>
                <th scope="col">Quantity</th>
                <th scope="col">Entry</th>
                <th scope="col">Mark</th>
              </tr>
            </thead>
            <tbody>
              {p.positions.map((x) => (
                <tr key={x.position_hash}>
                  <td>{x.instrument}</td>
                  <td>{x.quantity}</td>
                  <td>{x.entry_price}</td>
                  <td>{x.mark_price}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>
          {current
            ? "No positions reported by projection."
            : "Position state UNKNOWN; no current projection."}
        </p>
      )}
      <h2>Reservations</h2>
      {p.reservations.length ? (
        <div className="table-scroll">
          <table>
            <caption>Active virtual reservations</caption>
            <thead>
              <tr>
                <th scope="col">Instrument</th>
                <th scope="col">State</th>
                <th scope="col">Quantity</th>
                <th scope="col">Notional</th>
                <th scope="col">Modeled loss</th>
              </tr>
            </thead>
            <tbody>
              {p.reservations.map((x) => (
                <tr key={x.intent_hash}>
                  <td>{x.instrument}</td>
                  <td>{x.state}</td>
                  <td>{x.quantity}</td>
                  <td>{x.notional}</td>
                  <td>{x.modeled_loss}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p>
          {current
            ? "No active reservations reported."
            : "Reservation state UNKNOWN; no current projection."}
        </p>
      )}
      <h2>Pending / UNKNOWN</h2>
      {p.pending.length ? (
        <ul className="rows">
          {p.pending.map((x) => (
            <li key={x.intent_hash}>
              {x.state === "UNKNOWN" && (
                <span className="marker">UNKNOWN OUTCOME</span>
              )}
              <strong>{words(x.state)}</strong>
              <span className="hash">Intent {x.intent_hash}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p>
          {current
            ? "No pending or UNKNOWN orders reported."
            : "Pending order state UNKNOWN; no current projection."}
        </p>
      )}
    </>
  );
}

function Research({ data }: { data: Snapshot }) {
  return (
    <>
      <p className="notice">
        Reviewed nonproduction summary · no performance or return claim
      </p>
      <div className="cards">
        {[
          { id: "a", index: 0 },
          { id: "b", index: 1 },
          { id: "c", index: 2 },
          { id: "d", index: 3 },
        ].map((slot) => (
          <article key={slot.id}>
            <span className="eyebrow">REVIEWED RESULT {slot.index + 1}</span>
            <h2>{data.research.outcomes[slot.index]}</h2>
          </article>
        ))}
      </div>
      <Facts
        rows={[
          ["OOS holdouts", words(data.research.oos)],
          ["Candidate", data.research.candidate],
          ["Champion", data.research.champion],
          ["Scope", words(data.research.scope)],
        ]}
      />
    </>
  );
}

function Journal({
  data,
  now,
  state,
  source,
  filter,
  setFilter,
}: SourcedProps & {
  filter: JournalFilter;
  setFilter: (next: JournalFilter) => void;
}) {
  const j = data.journal;
  const inGroup = (group: JournalFilter) =>
    j.events.filter((x) => group === null || JOURNAL_GROUP[x.reason] === group);
  const shown = inGroup(filter);
  return (
    <>
      <p className="notice">
        {source(j.freshness)} · safe reason codes and evidence hashes only
        {j.freshness.observed_at && (
          <>
            {" "}
            · read <Stamp iso={j.freshness.observed_at} now={now} />
          </>
        )}
      </p>
      {j.events.length ? (
        <>
          <fieldset className="chips">
            <legend>Filter journal events</legend>
            {JOURNAL_FILTERS.map(([label, group]) => (
              <button
                type="button"
                key={label}
                aria-pressed={filter === group}
                onClick={() => setFilter(group)}
              >
                {label} ({inGroup(group).length})
              </button>
            ))}
          </fieldset>
          <p className="muted">
            Showing {shown.length} of the {j.events.length} most recent recorded
            events (at most 100 are read).
          </p>
          {shown.length ? (
            <ol className="timeline">
              {shown.map((x) => (
                <li
                  key={x.sequence}
                  data-marked={JOURNAL_MARKER[x.reason] ? "true" : undefined}
                >
                  <span className="sequence">#{x.sequence}</span>
                  <Stamp iso={x.observed_at} now={now} />
                  {JOURNAL_MARKER[x.reason] && (
                    <span className="marker">{JOURNAL_MARKER[x.reason]}</span>
                  )}
                  <strong>
                    {x.reason === "OTHER"
                      ? "OTHER RECORDED EVENT"
                      : words(x.reason)}
                  </strong>
                  <span className="hash">Evidence {x.evidence_hash}</span>
                  {x.intent_hash && (
                    <span className="hash">Intent {x.intent_hash}</span>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p>No events in this filter among those read.</p>
          )}
        </>
      ) : (
        <p>
          {state(j.freshness) === "AVAILABLE"
            ? "Journal connected; no events recorded."
            : state(j.freshness) === "UNAVAILABLE"
              ? "Journal UNAVAILABLE; the read failed and events are UNKNOWN."
              : state(j.freshness) === "STALE"
                ? "Journal STALE; events are UNKNOWN."
                : "Journal UNKNOWN; no connected evidence projection."}
        </p>
      )}
    </>
  );
}

function Health({
  data,
  now,
  retained,
  source,
}: SourcedProps & { retained: boolean }) {
  const p = data.paper;
  const kept = (value: string) =>
    retained ? `STALE (last read ${value})` : value;
  return (
    <>
      <Facts
        rows={[
          ["API liveness", kept(data.system.api)],
          ["Database readiness", kept(words(data.system.database))],
          ["Source health", data.system.source],
          ["Observation task", data.qualification.task],
          ["Qualification projection", source(data.qualification.freshness)],
          ["PAPER projection", source(p.freshness)],
          ["Journal projection", source(data.journal.freshness)],
          [
            "Kill / reconciliation",
            kept(
              `${p.kill ?? "UNKNOWN"} / ${p.reconciled === null ? "UNKNOWN" : p.reconciled ? "RECONCILED" : "NOT RECONCILED"}`,
            ),
          ],
          [
            "Offline gateway engineering",
            <span key="gateway">
              {REVIEWED_TEXT[data.reviewed.gateway.status]}{" "}
              <ReviewedTag item={data.reviewed.gateway} />
            </span>,
          ],
          [
            "Diagnostics observed at",
            <Stamp
              key="at"
              iso={data.system.freshness.observed_at}
              now={now}
            />,
          ],
        ]}
      />
      <p className="notice">
        Diagnostics readiness is not trading readiness. Task and source
        integration are not connected in this foundation.
      </p>
    </>
  );
}

function accountClass(data: Snapshot | null): string {
  if (!data) return "UNKNOWN";
  const f = data.paper.freshness;
  if (f.provenance === "ISOLATED_SYNTHETIC_PAPER")
    return f.state === "AVAILABLE"
      ? "VIRTUAL PAPER · SYNTHETIC"
      : `VIRTUAL PAPER · SYNTHETIC · ${f.state}`;
  if (f.provenance === "UNCONNECTED") return "UNCONNECTED · no account";
  return `UNKNOWN · ${words(f.reason)}`;
}

function StatusBar({
  data,
  status,
  retained,
  lastSuccess,
  staleSince,
  idleLeft,
  now,
}: {
  data: Snapshot | null;
  status: ReadStatus;
  retained: boolean;
  lastSuccess: number | null;
  staleSince: number | null;
  idleLeft: number;
  now: number;
}) {
  const p = data?.paper;
  const kept = (value: string) => (retained ? `${value} (STALE)` : value);
  const reconciled =
    p == null || p.reconciled === null
      ? "RECONCILIATION UNKNOWN"
      : p.reconciled
        ? "RECONCILED"
        : "NOT RECONCILED";
  const unknownOrders =
    p == null || p.unknown_orders === null
      ? "UNKNOWN-ORDER STATE UNKNOWN"
      : p.unknown_orders
        ? "UNKNOWN ORDERS PRESENT"
        : "NO UNKNOWN ORDERS";
  const age =
    lastSuccess === null ? "" : elapsed(Math.max(0, now - lastSuccess));
  const read =
    lastSuccess === null
      ? "no snapshot read"
      : status === "CONNECTED"
        ? `snapshot read ${age}`
        : `last successful read ${utcClock(lastSuccess)} (${age})`;
  const segments: [string, ReactNode, boolean][] = [
    ["Configured mode", data ? kept(data.system.mode) : "UNKNOWN", false],
    ["Account class", kept(accountClass(data)), false],
    [
      "Kill level",
      kept(p?.kill ?? "UNKNOWN"),
      p?.kill != null && p.kill !== "K0",
    ],
    [
      "Orders",
      kept(`${reconciled} · ${unknownOrders}`),
      p?.reconciled === false || p?.unknown_orders === true,
    ],
    [
      "Read status",
      <>
        <span role="status">{READ_LABEL[status]}</span> · {read}
      </>,
      status !== "CONNECTED",
    ],
    [
      "Authority",
      data
        ? `Execution DISABLED · LIVE ${data.system.live_authority}`
        : "UNKNOWN (no snapshot) · this terminal has no execution controls",
      false,
    ],
  ];
  return (
    <section className="statusbar" aria-label="Safety status">
      <dl>
        {segments.map(([label, value, attention]) => (
          <div key={label} data-attention={attention ? "true" : undefined}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {retained && staleSince !== null && (
        <p className="band">
          RETAINED SNAPSHOT — STALE since {utcClock(staleSince)}
        </p>
      )}
      {idleLeft <= IDLE_WARNING_MS && (
        <p className="band idle">
          <span role="status">
            Idle sign-out pending. Any key or pointer input keeps the session.
          </span>{" "}
          <span role="timer" aria-live="off">
            Signing out in {Math.max(0, Math.ceil(idleLeft / 1000))} s
          </span>
        </p>
      )}
    </section>
  );
}

function failureMessage(
  status: ReadStatus,
  httpStatus: number | null,
  hasData: boolean,
): string {
  const tail = hasData
    ? " The retained snapshot is STALE; current state is UNKNOWN."
    : " No snapshot has been read; current state is UNAVAILABLE / UNKNOWN.";
  const http = httpStatus === null ? "" : ` (HTTP ${httpStatus})`;
  switch (status) {
    case "DISCONNECTED":
      return `DISCONNECTED: no response from the local backend (network failure or timeout).${tail}`;
    case "UNAVAILABLE":
      return `BACKEND READ UNAVAILABLE${http}: the backend answered but could not serve the read.${tail}`;
    case "INVALID_CONTRACT":
      return `CONTRACT MISMATCH: the backend payload failed validation. UI and backend versions differ; rebuild the UI.${tail}`;
    case "ORIGIN_REFUSED": {
      const port = window.location.port ? `:${window.location.port}` : "";
      return `ORIGIN REFUSED${http}: origin or host refused; open http://127.0.0.1${port} exactly. You remain signed in.${tail}`;
    }
    case "STALE":
      return `STALE: no successful read within ${STALE_MS / 1000} s.${tail}`;
    default:
      return "";
  }
}

type ReadState = {
  // Result of the last completed attempt; PENDING until one completes.
  outcome: "PENDING" | "OK" | Exclude<ReadFailureCode, "UNAUTHORIZED">;
  httpStatus: number | null;
  lastSuccess: number | null;
  failedSince: number | null;
};
const NO_READ: ReadState = {
  outcome: "PENDING",
  httpStatus: null,
  lastSuccess: null,
  failedSince: null,
};

export default function App() {
  const [connection, setConnection] = useState<{
    token: string;
    revision: number;
  } | null>(null);
  const signedIn = connection !== null;
  const input = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [data, setData] = useState<Snapshot | null>(null);
  const [area, setArea] = useState<Area>("Command Center");
  const [read, setRead] = useState<ReadState>(NO_READ);
  const [clock, setClock] = useState({ now: Date.now(), idleLeft: IDLE_MS });
  const [notice, setNotice] = useState("");
  const generation = useRef(0);
  const lastActivity = useRef(0);
  const wasSignedIn = useRef(false);

  const signout = useCallback((message = "") => {
    generation.current++;
    setConnection(null);
    setData(null);
    setRead(NO_READ);
    setArea("Command Center");
    setNotice(message);
  }, []);

  useEffect(() => {
    if (!connection) return;
    const activeConnection = connection;
    const current = ++generation.current;
    let controller: AbortController | undefined;
    let disposed = false;
    async function load() {
      controller?.abort();
      const mine = new AbortController();
      controller = mine;
      const superseded = () =>
        disposed || generation.current !== current || controller !== mine;
      try {
        const next = await readSnapshot(activeConnection.token, mine.signal);
        if (superseded()) return;
        const at = Date.now();
        setData(next);
        setRead({
          outcome: "OK",
          httpStatus: null,
          lastSuccess: at,
          failedSince: null,
        });
        setClock((c) => ({ ...c, now: at }));
      } catch (e) {
        if (superseded()) return;
        const failure =
          e instanceof ReadFailure ? e : new ReadFailure("DISCONNECTED");
        if (failure.code === "UNAUTHORIZED") {
          signout(
            "Access denied (HTTP 401): the token was refused. Enter a valid runtime token.",
          );
          return;
        }
        const code = failure.code;
        const at = Date.now();
        setRead((r) => ({
          ...r,
          outcome: code,
          httpStatus: failure.status,
          failedSince: r.failedSince ?? at,
        }));
        setClock((c) => ({ ...c, now: at }));
      }
    }
    void load();
    const poll = window.setInterval(() => void load(), POLL_MS);
    return () => {
      disposed = true;
      controller?.abort();
      window.clearInterval(poll);
    };
  }, [connection, signout]);

  // One-second clock for ages and staleness, and the idle sign-out.
  useEffect(() => {
    if (!signedIn) return;
    lastActivity.current = Date.now();
    setClock({ now: lastActivity.current, idleLeft: IDLE_MS });
    const active = () => {
      lastActivity.current = Date.now();
    };
    const options = { capture: true, passive: true } as const;
    const events = [
      "keydown",
      "pointerdown",
      "pointermove",
      "wheel",
      "scroll",
      "touchstart",
    ] as const;
    for (const name of events) window.addEventListener(name, active, options);
    const tick = window.setInterval(() => {
      const now = Date.now();
      const idleLeft = IDLE_MS - (now - lastActivity.current);
      if (idleLeft <= 0)
        signout("Signed out after 15 minutes without interaction.");
      else setClock({ now, idleLeft });
    }, 1000);
    return () => {
      for (const name of events)
        window.removeEventListener(name, active, options);
      window.clearInterval(tick);
    };
  }, [signedIn, signout]);

  // Focus follows the session: token field on sign-out, view heading on sign-in
  // and on every area change.
  // biome-ignore lint/correctness/useExhaustiveDependencies: an area change moves focus
  useEffect(() => {
    if (signedIn) heading.current?.focus();
    else if (wasSignedIn.current) input.current?.focus();
    wasSignedIn.current = signedIn;
  }, [signedIn, area]);

  if (!signedIn)
    return (
      <main className="sign-in">
        <span className="brand">
          AUVEXO <span>ALPHA</span>
        </span>
        <h1>Owner terminal</h1>
        <p>Local read-only access</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const secret = (input.current?.value ?? "").trim();
            if (input.current) input.current.value = "";
            const problem = tokenProblem(secret);
            if (problem) {
              setNotice(problem);
              input.current?.focus();
              return;
            }
            setNotice("");
            setConnection({ token: secret, revision: 0 });
          }}
        >
          <label htmlFor="owner-token">Runtime access token</label>
          <input
            id="owner-token"
            ref={input}
            type="password"
            autoComplete="one-time-code"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            data-1p-ignore="true"
            data-lpignore="true"
            data-bwignore="true"
            data-form-type="other"
            aria-describedby="owner-token-help"
            required
          />
          <button type="submit">Connect locally</button>
        </form>
        {notice && <p role="alert">{notice}</p>}
        <p className="muted" id="owner-token-help">
          The token stays in memory for this session only and is never saved.
          The session ends after 15 minutes without interaction.
        </p>
      </main>
    );

  const sinceSuccess =
    read.lastSuccess === null ? null : clock.now - read.lastSuccess;
  const status: ReadStatus =
    read.outcome === "PENDING"
      ? "LOADING"
      : read.outcome !== "OK"
        ? read.outcome
        : sinceSuccess !== null && sinceSuccess > STALE_MS
          ? "STALE"
          : "CONNECTED";
  const retained = data !== null && status !== "CONNECTED";
  const staleSince =
    read.failedSince ??
    (read.lastSuccess === null ? null : read.lastSuccess + STALE_MS);
  const message = failureMessage(status, read.httpStatus, data !== null);
  return (
    <div className="terminal">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <header className="topbar">
        <div>
          <span className="brand">
            AUVEXO <span>ALPHA</span>
          </span>
          <span className="eyebrow">PRIVATE OWNER TERMINAL · LOOPBACK</span>
        </div>
        <div className="actions">
          <button
            type="button"
            onClick={() =>
              setConnection((x) =>
                x ? { ...x, revision: x.revision + 1 } : null,
              )
            }
          >
            Refresh reads
          </button>
          <button type="button" onClick={() => signout()}>
            Sign out
          </button>
        </div>
      </header>
      <nav aria-label="Terminal areas">
        <div className="tabs">
          {areas.map((name) => (
            <button
              type="button"
              key={name}
              aria-current={area === name ? "page" : undefined}
              onClick={() => setArea(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <p className="sidebar-note">
          Read-only foundation
          <br />
          No execution controls
        </p>
      </nav>
      <div className="workspace">
        <StatusBar
          data={data}
          status={status}
          retained={retained}
          lastSuccess={read.lastSuccess}
          staleSince={staleSince}
          idleLeft={clock.idleLeft}
          now={clock.now}
        />
        <main id="workspace" tabIndex={-1}>
          {message && (
            <p role="alert" className="notice danger">
              {message}
            </p>
          )}
          <Terminal
            data={data}
            area={area}
            retained={retained}
            now={clock.now}
            heading={heading}
          >
            {!data && (
              <p role="status">
                {status === "LOADING"
                  ? "Loading read-only snapshot..."
                  : "UNAVAILABLE / UNKNOWN: no snapshot has been read."}
              </p>
            )}
          </Terminal>
        </main>
        <footer>
          Presentation only · engineering evidence does not grant financial
          authority
        </footer>
      </div>
    </div>
  );
}
