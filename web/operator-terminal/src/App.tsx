import { useCallback, useEffect, useRef, useState } from "react";
import { ReadFailure, readSnapshot } from "./client";
import type { Snapshot } from "./contracts";

const areas = [
  "Command Center",
  "Risk / PAPER",
  "Research",
  "Journal / evidence",
  "System Health",
] as const;
type Area = (typeof areas)[number];
const words = (text: string) => text.replaceAll("_", " ");
function Facts({ rows }: { rows: [string, string][] }) {
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
export function Terminal({ data, area }: { data: Snapshot; area: Area }) {
  const p = data.paper,
    q = data.qualification;
  return (
    <section aria-labelledby="view-title">
      <div className="section-heading">
        <div>
          <span className="eyebrow">OWNER VISIBILITY</span>
          <h1 id="view-title">{area}</h1>
        </div>
        <span className="pill">READ ONLY</span>
      </div>
      {area === "Command Center" && (
        <>
          <div className="cards">
            <article>
              <span className="eyebrow">ENGINEERING</span>
              <h2>Offline foundation accepted</h2>
              <p>{words(q.phase5)}</p>
            </article>
            <article>
              <span className="eyebrow">OPERATIONAL QUALIFICATION</span>
              <h2>Observation active / exit open</h2>
              <p>Phase 4 genuine dates: {q.phase4_days ?? "UNKNOWN"}</p>
              <p>
                Phase 2 genuine dates: {q.phase2_days ?? "UNKNOWN"} |
                operational exit open
              </p>
            </article>
            <article>
              <span className="eyebrow">FINANCIAL AUTHORITY</span>
              <h2>Execution disabled</h2>
              <p>LIVE {data.system.live_authority} | no money capability</p>
            </article>
          </div>
          <Facts
            rows={[
              ["Build", `${data.system.version} | ${words(data.system.build)}`],
              ["Mode", data.system.mode],
              ["Policy", data.system.policy],
              ["Source freshness", data.system.source],
              ["Qualification projection", q.freshness.state],
              ["DS-03", q.ds03],
            ]}
          />
        </>
      )}
      {area === "Risk / PAPER" && (
        <>
          <p className="notice">
            Virtual PAPER projection | {p.freshness.state} |{" "}
            {words(p.freshness.provenance)}
          </p>
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
              [
                "Active reservations",
                String(p.active_reservations ?? "UNKNOWN"),
              ],
              ["Observed at", p.freshness.observed_at ?? "UNKNOWN"],
            ]}
          />
          <h2>Positions</h2>
          {p.positions.length ? (
            <div className="table-scroll">
              <table>
                <caption>Read-only virtual positions</caption>
                <thead>
                  <tr>
                    <th>Instrument</th>
                    <th>Quantity</th>
                    <th>Entry</th>
                    <th>Mark</th>
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
              {p.freshness.state === "AVAILABLE"
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
                    <th>Instrument</th>
                    <th>State</th>
                    <th>Quantity</th>
                    <th>Notional</th>
                    <th>Modeled loss</th>
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
              {p.freshness.state === "AVAILABLE"
                ? "No active reservations reported."
                : "Reservation state UNKNOWN; no current projection."}
            </p>
          )}
          <h2>Pending / UNKNOWN</h2>
          {p.pending.map((x) => (
            <p className="hash" key={x.intent_hash}>
              {x.state} | {x.intent_hash}
            </p>
          ))}
        </>
      )}
      {area === "Research" && (
        <>
          <p className="notice">
            Reviewed nonproduction summary | no profitability claim
          </p>
          <div className="cards">
            {[
              { id: "a", index: 0 },
              { id: "b", index: 1 },
              { id: "c", index: 2 },
              { id: "d", index: 3 },
            ].map((slot) => (
              <article key={slot.id}>
                <span className="eyebrow">
                  REVIEWED RESULT {slot.index + 1}
                </span>
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
      )}
      {area === "Journal / evidence" && (
        <>
          <p className="notice">
            {data.journal.freshness.state} | safe reason codes and evidence
            hashes only
          </p>
          {data.journal.events.length ? (
            <ol className="timeline">
              {data.journal.events.map((x) => (
                <li key={x.sequence}>
                  <time>{x.observed_at}</time>
                  <strong>{words(x.reason)}</strong>
                  <span className="hash">Evidence {x.evidence_hash}</span>
                  {x.intent_hash && (
                    <span className="hash">Intent {x.intent_hash}</span>
                  )}
                  {x.decision_hash && (
                    <span className="hash">Decision {x.decision_hash}</span>
                  )}
                </li>
              ))}
            </ol>
          ) : (
            <p>Journal UNKNOWN; no connected evidence projection.</p>
          )}
        </>
      )}
      {area === "System Health" && (
        <>
          <Facts
            rows={[
              ["API liveness", data.system.api],
              ["Database readiness", data.system.database],
              ["Source health", data.system.source],
              ["Observation task", q.task],
              ["PAPER projection", p.freshness.state],
              [
                "Kill / reconciliation",
                `${p.kill ?? "UNKNOWN"} / ${p.reconciled === null ? "UNKNOWN" : p.reconciled ? "RECONCILED" : "NOT RECONCILED"}`,
              ],
              ["Offline gateway engineering", words(data.system.gateway)],
              [
                "Diagnostics observed at",
                data.system.freshness.observed_at ?? "UNKNOWN",
              ],
            ]}
          />
          <p className="notice">
            Diagnostics readiness is not trading readiness. Task and source
            integration are not connected in this foundation.
          </p>
        </>
      )}
    </section>
  );
}
export default function App() {
  const [connection, setConnection] = useState<{
    token: string;
    revision: number;
  } | null>(null);
  const token = connection?.token ?? "";
  const input = useRef<HTMLInputElement>(null);
  const [data, setData] = useState<Snapshot | null>(null);
  const [area, setArea] = useState<Area>("Command Center");
  const [status, setStatus] = useState("SIGNED_OUT");
  const [error, setError] = useState("");
  const generation = useRef(0);
  const lastSuccess = useRef(0);
  const signout = useCallback((message = "") => {
    generation.current++;
    setConnection(null);
    setData(null);
    setStatus("SIGNED_OUT");
    setError(message);
    lastSuccess.current = 0;
    if (input.current) input.current.value = "";
  }, []);
  useEffect(() => {
    if (!connection) return;
    const activeConnection = connection;
    const current = ++generation.current;
    let controller: AbortController | undefined;
    let disposed = false;
    async function load() {
      controller?.abort();
      controller = new AbortController();
      setStatus(lastSuccess.current ? "REFRESHING" : "LOADING");
      try {
        const next = await readSnapshot(
          activeConnection.token,
          controller.signal,
        );
        if (disposed || generation.current !== current) return;
        setData(next);
        lastSuccess.current = Date.now();
        setError("");
        setStatus("CONNECTED");
      } catch (e) {
        if (disposed || generation.current !== current) return;
        if (e instanceof ReadFailure && e.code === "UNAUTHORIZED") {
          signout("Access denied. Enter a valid token.");
          return;
        }
        setStatus("STALE");
        setError(
          "Read unavailable. Retained data is STALE; current state is UNKNOWN.",
        );
      }
    }
    void load();
    const poll = window.setInterval(() => void load(), 30000);
    const stale = window.setInterval(() => {
      if (lastSuccess.current && Date.now() - lastSuccess.current > 45000)
        setStatus("STALE");
    }, 5000);
    return () => {
      disposed = true;
      controller?.abort();
      window.clearInterval(poll);
      window.clearInterval(stale);
    };
  }, [connection, signout]);
  if (!token)
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
            const secret = input.current?.value ?? "";
            if (!secret.trim()) {
              setError("Enter your runtime token.");
              return;
            }
            if (input.current) input.current.value = "";
            setError("");
            setConnection({ token: secret, revision: 0 });
          }}
        >
          <label htmlFor="owner-token">Runtime access token</label>
          <input
            id="owner-token"
            ref={input}
            type="password"
            autoComplete="off"
            spellCheck={false}
            required
          />
          <button type="submit">Connect locally</button>
        </form>
        {error && <p role="alert">{error}</p>}
        <p className="muted">The token stays in memory for this session.</p>
      </main>
    );
  return (
    <div className="terminal">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>
      <aside>
        <span className="brand">
          AUVEXO <span>ALPHA</span>
        </span>
        <p className="eyebrow">PRIVATE OWNER TERMINAL</p>
        <nav aria-label="Terminal areas">
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
        </nav>
        <p className="sidebar-note">
          Read-only foundation
          <br />
          No execution controls
        </p>
        <button type="button" onClick={() => signout()}>
          Sign out
        </button>
      </aside>
      <div className="workspace">
        <header>
          <div>
            <span className="connection" role="status">
              {status === "CONNECTED"
                ? "Read connection established"
                : status === "STALE"
                  ? "STALE / DISCONNECTED"
                  : words(status)}
            </span>
            <span className="muted">Loopback access</span>
          </div>
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
        </header>
        <main id="workspace" tabIndex={-1}>
          {error && (
            <p role="alert" className="notice danger">
              {error}
            </p>
          )}
          {data ? (
            <>
              <div className="authority">
                <span>Mode {data.system.mode}</span>
                <span>Execution DISABLED</span>
                <span>LIVE {data.system.live_authority}</span>
              </div>
              <Terminal data={data} area={area} />
            </>
          ) : (
            <p role="status">
              {status === "STALE"
                ? "UNAVAILABLE / UNKNOWN - no current snapshot."
                : "Loading read-only snapshot..."}
            </p>
          )}
        </main>
        <footer>
          Presentation only | engineering evidence does not grant financial
          authority
        </footer>
      </div>
    </div>
  );
}
