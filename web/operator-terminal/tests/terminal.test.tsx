import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import App, { areas, Terminal } from "../src/App";
import { parseSnapshot } from "../src/contracts";
import populated from "./synthetic-populated-snapshot.json";
import fixture from "./synthetic-snapshot.json";

const syntheticToken = "synthetic-test-diagnostics-only-0000";
const answer = (body: unknown = fixture) =>
  new Response(JSON.stringify(body), { status: 200 });
// Microtask-only response for fake-timer tests; never touches real I/O or timers.
const light = (status: number, body: unknown = fixture) =>
  ({
    status,
    ok: status >= 200 && status < 300,
    text: () => Promise.resolve(JSON.stringify(body)),
  }) as unknown as Response;
const tokenField = () => screen.getByLabelText("Runtime access token");
const statusBar = () => screen.getByRole("region", { name: "Safety status" });
async function connect() {
  const user = userEvent.setup();
  await user.type(tokenField(), syntheticToken);
  await user.click(screen.getByRole("button", { name: /Connect locally/ }));
  return user;
}
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
async function connectWithFakeTimers() {
  fireEvent.change(tokenField(), { target: { value: syntheticToken } });
  fireEvent.click(screen.getByRole("button", { name: /Connect locally/ }));
  await advance(0);
}

describe("owner bootstrap and token", () => {
  it("loads data-free sign-in without any API request", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Owner terminal" }),
    ).toBeTruthy();
    expect(screen.queryByText(/Execution DISABLED/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Safety status" })).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("discourages saving the bearer in the token field", () => {
    render(<App />);
    const field = tokenField();
    expect(field.getAttribute("type")).toBe("password");
    expect(field.getAttribute("autocomplete")).toBe("one-time-code");
    expect(field.getAttribute("data-1p-ignore")).toBe("true");
    expect(field.getAttribute("data-lpignore")).toBe("true");
    expect(field.getAttribute("data-bwignore")).toBe("true");
    expect(field.getAttribute("spellcheck")).toBe("false");
  });
  it("never writes the token to storage, cookie, history, console or DOM", async () => {
    const fetcher = vi.fn().mockImplementation(() => answer(populated));
    vi.stubGlobal("fetch", fetcher);
    const sinks = [
      vi.spyOn(Storage.prototype, "setItem"),
      vi.spyOn(Document.prototype, "cookie", "set"),
      vi.spyOn(window.history, "pushState"),
      vi.spyOn(window.history, "replaceState"),
    ];
    const consoles = (["log", "info", "warn", "error", "debug"] as const).map(
      (method) => vi.spyOn(console, method),
    );
    render(<App />);
    const user = await connect();
    await screen.findByText(/Execution DISABLED · LIVE LOCKED/);
    for (const name of areas) {
      await user.click(screen.getByRole("button", { name }));
      expect(document.documentElement.outerHTML).not.toContain(syntheticToken);
    }
    await user.click(screen.getByRole("button", { name: "Refresh reads" }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
    for (const [url, options] of fetcher.mock.calls) {
      expect(url).toBe("http://127.0.0.1:8765/api/v1/terminal/snapshot");
      expect(options.headers).toEqual({
        Authorization: `Bearer ${syntheticToken}`,
      });
      expect(options.credentials).toBe("omit");
    }
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(tokenField()).toHaveProperty("value", "");
    for (const sink of sinks) expect(sink).not.toHaveBeenCalled();
    for (const spy of consoles) expect(spy).not.toHaveBeenCalled();
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
    expect(document.cookie).toBe("");
    expect(window.location.href).toBe("http://127.0.0.1:8765/");
    expect(document.documentElement.outerHTML).not.toContain(syntheticToken);
    expect(screen.queryByRole("region", { name: "Safety status" })).toBeNull();
  });
  it("refuses a token that cannot be sent, before any request", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    const user = userEvent.setup();
    await user.type(
      tokenField(),
      "synthetic-\u0442\u043e\u043a\u0435\u043d-\u2603",
    );
    await user.click(screen.getByRole("button", { name: /Connect locally/ }));
    expect(screen.getByRole("alert").textContent).toMatch(/cannot be sent/);
    expect(fetcher).not.toHaveBeenCalled();
    expect(tokenField()).toHaveProperty("value", "");
    expect(document.activeElement).toBe(tokenField());
  });
  it("shows loading with every status segment explicit before a response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    render(<App />);
    await connect();
    expect(screen.getByText(/Loading read-only snapshot/)).toBeTruthy();
    const bar = within(statusBar());
    expect(bar.getByRole("status").textContent).toBe("LOADING");
    expect(statusBar().textContent).toContain("no snapshot read");
    expect(bar.getAllByText("UNKNOWN")).toHaveLength(3);
    expect(
      bar.getByText("RECONCILIATION UNKNOWN · UNKNOWN-ORDER STATE UNKNOWN"),
    ).toBeTruthy();
    expect(bar.getByText(/no execution controls/)).toBeTruthy();
  });
  it("clears token and all data on 401 and returns focus to the token field", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => answer(populated))
        .mockResolvedValue(new Response("", { status: 401 })),
    );
    render(<App />);
    const user = await connect();
    await screen.findByText(/Execution DISABLED · LIVE LOCKED/);
    await user.click(screen.getByRole("button", { name: "Refresh reads" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("HTTP 401"),
    );
    expect(
      screen.getByRole("heading", { name: "Owner terminal" }),
    ).toBeTruthy();
    expect(tokenField()).toHaveProperty("value", "");
    expect(document.activeElement).toBe(tokenField());
    expect(screen.queryByText(/K4/)).toBeNull();
    expect(screen.queryByRole("region", { name: "Safety status" })).toBeNull();
  });
  it.each([
    [
      "403",
      () => Promise.resolve(new Response("private", { status: 403 })),
      "ORIGIN REFUSED",
      /ORIGIN REFUSED \(HTTP 403\): origin or host refused; open http:\/\/127\.0\.0\.1:8765 exactly\. You remain signed in\./,
    ],
    [
      "503",
      () => Promise.resolve(new Response("private", { status: 503 })),
      "BACKEND READ UNAVAILABLE",
      /BACKEND READ UNAVAILABLE \(HTTP 503\)/,
    ],
    [
      "network failure",
      () => Promise.reject(new TypeError("sensitive internal text")),
      "DISCONNECTED",
      /DISCONNECTED: no response from the local backend/,
    ],
    [
      "invalid payload",
      () => Promise.resolve(answer({ ...fixture, reviewed: undefined })),
      "CONTRACT MISMATCH",
      /CONTRACT MISMATCH: .*UI and backend versions differ; rebuild the UI\./,
    ],
  ])(
    "keeps the session and names the failure on %s",
    async (_name, respond, label, message) => {
      const fetcher = vi.fn().mockImplementation(respond);
      vi.stubGlobal("fetch", fetcher);
      render(<App />);
      const user = await connect();
      await screen.findByRole("alert");
      expect(screen.getByRole("alert").textContent).toMatch(message);
      expect(screen.getByRole("alert").textContent).toContain(
        "No snapshot has been read; current state is UNAVAILABLE / UNKNOWN.",
      );
      expect(within(statusBar()).getByRole("status").textContent).toBe(label);
      expect(
        screen.getByText(/UNAVAILABLE \/ UNKNOWN: no snapshot/),
      ).toBeTruthy();
      expect(screen.queryByText(/private|sensitive internal text/)).toBeNull();
      // Not signed out: the session, its controls and the retry all remain.
      expect(screen.queryByLabelText("Runtime access token")).toBeNull();
      expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
      await user.click(screen.getByRole("button", { name: "Refresh reads" }));
      await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(2));
      expect(fetcher.mock.calls[1][1].headers).toEqual({
        Authorization: `Bearer ${syntheticToken}`,
      });
    },
  );
  it("marks a retained snapshot STALE everywhere after a disconnect", async () => {
    const fetcher = vi
      .fn()
      .mockImplementationOnce(() => answer(populated))
      .mockRejectedValue(new Error("sensitive internal text"));
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    const user = await connect();
    await screen.findByText(/Execution DISABLED · LIVE LOCKED/);
    expect(screen.queryByText(/RETAINED SNAPSHOT/)).toBeNull();
    expect(within(statusBar()).getByRole("status").textContent).toBe(
      "CONNECTED",
    );
    await user.click(screen.getByRole("button", { name: "Refresh reads" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("DISCONNECTED"),
    );
    expect(screen.getByRole("alert").textContent).toContain(
      "The retained snapshot is STALE; current state is UNKNOWN.",
    );
    expect(screen.queryByText("sensitive internal text")).toBeNull();
    const bar = within(statusBar());
    expect(bar.getByRole("status").textContent).toBe("DISCONNECTED");
    expect(
      bar.getByText(/^RETAINED SNAPSHOT — STALE since \d\d:\d\d:\d\d UTC$/),
    ).toBeTruthy();
    expect(statusBar().textContent).toMatch(
      /last successful read \d\d:\d\d:\d\d UTC \(\d+ s ago\)/,
    );
    expect(bar.getByText("K4 (STALE)")).toBeTruthy();
    expect(bar.getByText("PAPER (STALE)")).toBeTruthy();
    expect(bar.getByText("VIRTUAL PAPER · SYNTHETIC (STALE)")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "System Health" }));
    expect(screen.getByText("STALE (last read ALIVE)")).toBeTruthy();
    expect(screen.queryByText("ALIVE")).toBeNull();
    expect(
      screen.getAllByText(
        "STALE · ISOLATED SYNTHETIC PAPER · RETAINED SNAPSHOT",
      ),
    ).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "Risk / PAPER" }));
    expect(
      screen.getByText(
        "Virtual PAPER projection · STALE · ISOLATED SYNTHETIC PAPER · RETAINED SNAPSHOT",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/AVAILABLE/)).toBeNull();
  });
  it("ignores late responses after signout", async () => {
    let resolve: (value: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        () =>
          new Promise<Response>((r) => {
            resolve = r;
          }),
      ),
    );
    render(<App />);
    const user = await connect();
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    resolve(answer());
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Owner terminal" }),
      ).toBeTruthy(),
    );
    expect(screen.queryByText(/Execution DISABLED/)).toBeNull();
    expect(document.activeElement).toBe(tokenField());
  });
  it("moves focus to the view heading on sign-in and on area change", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => answer()),
    );
    render(<App />);
    const user = await connect();
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Command Center" }),
    );
    await screen.findByText(/Execution DISABLED · LIVE LOCKED/);
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Command Center" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Journal / evidence" }),
    );
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Journal / evidence" }),
    );
  });
});

describe("timers", () => {
  const start = Date.parse("2026-01-01T00:00:10Z");
  it("polls every 30 s and shows the snapshot age", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(start);
    const fetcher = vi.fn().mockImplementation(async () => light(200));
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    await connectWithFakeTimers();
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(within(statusBar()).getByRole("status").textContent).toBe(
      "CONNECTED",
    );
    await advance(12_000);
    expect(statusBar().textContent).toContain(
      "CONNECTED · snapshot read 12 s ago",
    );
    await advance(18_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(statusBar().textContent).toContain(
      "CONNECTED · snapshot read 0 s ago",
    );
    await advance(30_000);
    expect(fetcher).toHaveBeenCalledTimes(3);
    expect(screen.queryByText(/RETAINED SNAPSHOT/)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("turns STALE after 45 s without a successful read", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(start);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(async () => light(200, populated))
        .mockImplementation(() => new Promise(() => {})),
    );
    render(<App />);
    await connectWithFakeTimers();
    await advance(45_000);
    expect(within(statusBar()).getByRole("status").textContent).toBe(
      "CONNECTED",
    );
    expect(screen.queryByText(/RETAINED SNAPSHOT/)).toBeNull();
    await advance(1_000);
    const bar = within(statusBar());
    expect(bar.getByRole("status").textContent).toBe("STALE");
    expect(
      bar.getByText("RETAINED SNAPSHOT — STALE since 00:00:55 UTC"),
    ).toBeTruthy();
    expect(statusBar().textContent).toContain(
      "last successful read 00:00:10 UTC (46 s ago)",
    );
    expect(bar.getByText("K4 (STALE)")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain(
      "STALE: no successful read within 45 s.",
    );
  });
  it("signs out after 15 idle minutes with a final-minute countdown", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(start);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async () => light(200, populated)),
    );
    render(<App />);
    await connectWithFakeTimers();
    await advance(14 * 60_000 - 1_000);
    expect(screen.queryByRole("timer")).toBeNull();
    await advance(11_000);
    expect(screen.getByRole("timer").textContent).toBe("Signing out in 50 s");
    expect(screen.getByText(/Idle sign-out pending/)).toBeTruthy();
    // Interaction keeps the session and removes the countdown.
    fireEvent.keyDown(document.body, { key: "Shift" });
    await advance(1_000);
    expect(screen.queryByRole("timer")).toBeNull();
    await advance(14 * 60_000 + 30_000);
    expect(screen.getByRole("timer").textContent).toBe("Signing out in 29 s");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    await advance(29_000);
    expect(screen.getByRole("alert").textContent).toBe(
      "Signed out after 15 minutes without interaction.",
    );
    expect(screen.queryByRole("region", { name: "Safety status" })).toBeNull();
    expect(screen.queryByText(/K4/)).toBeNull();
    expect(tokenField()).toHaveProperty("value", "");
    expect(document.activeElement).toBe(tokenField());
  });
});

describe("truthful views", () => {
  const now = Date.parse("2026-01-01T00:00:10Z");
  it.each(areas)("renders %s", (area) => {
    render(<Terminal data={parseSnapshot(fixture)} area={area} />);
    expect(screen.getByRole("heading", { name: area })).toBeTruthy();
  });
  it("shows the populated status bar: mode, account, kill, orders, read, authority", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => answer(populated)),
    );
    render(<App />);
    await connect();
    await screen.findByText("Execution DISABLED · LIVE LOCKED");
    const bar = within(statusBar());
    for (const label of [
      "Configured mode",
      "Account class",
      "Kill level",
      "Orders",
      "Read status",
      "Authority",
    ])
      expect(bar.getByText(label)).toBeTruthy();
    expect(bar.getByText("PAPER")).toBeTruthy();
    expect(bar.getByText("VIRTUAL PAPER · SYNTHETIC")).toBeTruthy();
    expect(bar.getByText("K4")).toBeTruthy();
    expect(
      bar.getByText("NOT RECONCILED · UNKNOWN ORDERS PRESENT"),
    ).toBeTruthy();
    expect(bar.getByRole("status").textContent).toBe("CONNECTED");
  });
  it("shows UNKNOWN explicitly in the status bar when unconnected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => answer()),
    );
    render(<App />);
    await connect();
    await screen.findByText("Execution DISABLED · LIVE LOCKED");
    const bar = within(statusBar());
    expect(bar.getByText("RESEARCH")).toBeTruthy();
    expect(bar.getByText("UNCONNECTED · no account")).toBeTruthy();
    expect(bar.getByText("UNKNOWN")).toBeTruthy();
    expect(
      bar.getByText("RECONCILIATION UNKNOWN · UNKNOWN-ORDER STATE UNKNOWN"),
    ).toBeTruthy();
  });
  it("renders Risk with K4, unreconciled and UNKNOWN orders", () => {
    render(
      <Terminal
        data={parseSnapshot(populated)}
        area="Risk / PAPER"
        now={now}
      />,
    );
    expect(
      screen.getByText(
        "Virtual PAPER projection · AVAILABLE · ISOLATED SYNTHETIC PAPER · CURRENT",
      ),
    ).toBeTruthy();
    expect(screen.getByText("K4")).toBeTruthy();
    expect(screen.getByText("NO")).toBeTruthy();
    expect(screen.getByText("UNKNOWN OUTCOMES PRESENT")).toBeTruthy();
    expect(screen.getByText("9950.25")).toBeTruthy();
    const stamp = screen.getByText("23:59:40 UTC (30 s ago)");
    expect(stamp.tagName).toBe("TIME");
    expect(stamp.getAttribute("datetime")).toBe("2025-12-31T23:59:40Z");
    expect(stamp.getAttribute("title")).toBe("2025-12-31T23:59:40Z");
    const [positions, reservations] = screen.getAllByRole("table");
    expect(within(positions).getAllByRole("row")).toHaveLength(3);
    expect(within(reservations).getAllByRole("row")).toHaveLength(3);
    for (const header of screen.getAllByRole("columnheader"))
      expect(header.getAttribute("scope")).toBe("col");
    expect(screen.getAllByText(/^Intent [0-9a-f]{64}$/)).toHaveLength(5);
    expect(screen.getAllByText("UNKNOWN OUTCOME")).toHaveLength(1);
    expect(screen.getByText("PARTIALLY FILLED")).toBeTruthy();
    expect(screen.queryByText(/No positions reported/)).toBeNull();
  });
  it("gives Pending / UNKNOWN the same two-branch empty state", () => {
    const { unmount } = render(
      <Terminal data={parseSnapshot(fixture)} area="Risk / PAPER" />,
    );
    expect(screen.getByText(/Position state UNKNOWN/)).toBeTruthy();
    expect(screen.getByText(/Reservation state UNKNOWN/)).toBeTruthy();
    expect(screen.getByText(/Pending order state UNKNOWN/)).toBeTruthy();
    expect(screen.queryByText(/No pending or UNKNOWN orders/)).toBeNull();
    unmount();
    const empty = structuredClone(populated);
    empty.paper.pending = [];
    empty.paper.positions = [];
    empty.paper.reservations = [];
    render(<Terminal data={parseSnapshot(empty)} area="Risk / PAPER" />);
    expect(
      screen.getByText("No pending or UNKNOWN orders reported."),
    ).toBeTruthy();
    expect(
      screen.getByText("No positions reported by projection."),
    ).toBeTruthy();
    expect(screen.queryByText(/state UNKNOWN; no current/)).toBeNull();
  });
  it("renders every journal kind with markers and filter chips", async () => {
    render(
      <Terminal
        data={parseSnapshot(populated)}
        area="Journal / evidence"
        now={now}
      />,
    );
    const user = userEvent.setup();
    expect(screen.getAllByRole("listitem")).toHaveLength(15);
    expect(screen.getAllByText("KILL EVENT")).toHaveLength(1);
    expect(screen.getAllByText("UNKNOWN OUTCOME")).toHaveLength(1);
    expect(screen.getAllByText("LOSS BREACH")).toHaveLength(1);
    expect(screen.getByText("OTHER RECORDED EVENT")).toBeTruthy();
    expect(screen.getByText("23:59:30 UTC (40 s ago)").tagName).toBe("TIME");
    expect(screen.getByText(/· read/).textContent).toContain(
      "AVAILABLE · ISOLATED SYNTHETIC PAPER · CURRENT",
    );
    const chip = (name: RegExp) => screen.getByRole("button", { name });
    expect(chip(/^All \(15\)$/).getAttribute("aria-pressed")).toBe("true");
    await user.click(chip(/^Kill \(4\)$/));
    expect(chip(/^Kill/).getAttribute("aria-pressed")).toBe("true");
    expect(chip(/^All/).getAttribute("aria-pressed")).toBe("false");
    expect(
      screen
        .getAllByRole("listitem")
        .map((x) => x.querySelector("strong")?.textContent),
    ).toEqual(["KILL STATE", "LOSS LATCH", "OWNER RESUME", "WRITER ACQUIRED"]);
    await user.click(chip(/^Reconcile \(3\)$/));
    expect(
      screen
        .getAllByRole("listitem")
        .map((x) => x.querySelector("strong")?.textContent),
    ).toEqual(["RECONCILIATION", "UNKNOWN ORDER", "MARK HEALTH"]);
    await user.click(chip(/^Decisions \(3\)$/));
    expect(
      screen
        .getAllByRole("listitem")
        .map((x) => x.querySelector("strong")?.textContent),
    ).toEqual(["AUTHORIZED", "DENIED", "DISPATCH ATTEMPT"]);
    await user.click(chip(/^All/));
    expect(screen.getAllByRole("listitem")).toHaveLength(15);
  });
  it("separates an empty connected journal from an unconnected one", () => {
    const quiet = structuredClone(populated);
    quiet.journal.events = [];
    quiet.journal.freshness.reason = "NO_EVENTS";
    const { unmount } = render(
      <Terminal data={parseSnapshot(quiet)} area="Journal / evidence" />,
    );
    expect(
      screen.getByText("Journal connected; no events recorded."),
    ).toBeTruthy();
    unmount();
    render(
      <Terminal data={parseSnapshot(fixture)} area="Journal / evidence" />,
    );
    expect(
      screen.getByText("Journal UNKNOWN; no connected evidence projection."),
    ).toBeTruthy();
  });
  it("labels reviewed statements static and never asserts anything is active", () => {
    const { container } = render(
      <Terminal data={parseSnapshot(fixture)} area="Command Center" />,
    );
    expect(container.textContent).not.toMatch(/\bactive\b/i);
    expect(
      screen.getByRole("heading", { name: "Operational status UNKNOWN" }),
    ).toBeTruthy();
    expect(screen.getByText("Phase 4 genuine dates: UNKNOWN")).toBeTruthy();
    expect(
      screen.getAllByText(/^Operational status UNKNOWN \(not connected/),
    ).toHaveLength(4);
    const blocked = screen.getByRole("heading", {
      name: "Blocked and not authorised",
    }).nextElementSibling as HTMLElement;
    const rows = within(blocked).getAllByRole("listitem");
    expect(rows.map((row) => row.querySelector("strong")?.textContent)).toEqual(
      [
        "Broker order transport",
        "Permit issuer",
        "Binance live derivatives",
        "DS-03",
        "Phase 5 commissioning",
      ],
    );
    for (const row of rows)
      expect(row.textContent).toContain(
        "reviewed static summary · as of 2026-11-12",
      );
    expect(rows[0].textContent).toContain("NONE: does not exist");
    expect(rows[2].textContent).toContain("BLOCKED BY POLICY");
    expect(rows[3].textContent).toContain(
      "no account, session, rights or qualification",
    );
    expect(rows[4].textContent).toContain("NOT STARTED");
    expect(
      screen.getAllByText("reviewed static summary · as of 2026-11-12"),
    ).toHaveLength(9);
  });
  it("keeps four INCONCLUSIVE and no candidate/champion", () => {
    render(<Terminal data={parseSnapshot(fixture)} area="Research" />);
    expect(
      screen.getAllByRole("heading", { name: "INCONCLUSIVE" }),
    ).toHaveLength(4);
    expect(screen.getAllByText("NONE")).toHaveLength(2);
  });
  it.each(areas)("uses no forbidden wording in %s", (area) => {
    const { container } = render(
      <Terminal data={parseSnapshot(populated)} area={area} />,
    );
    expect(container.textContent).not.toMatch(/profit|live trading|success/i);
    expect(
      container.querySelector("script, style, [style], a[href^='http']"),
    ).toBeNull();
  });
});

describe("accessibility", () => {
  it("is keyboard operable with a skip link", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => answer()),
    );
    render(<App />);
    const user = await connect();
    await screen.findByText("Execution DISABLED · LIVE LOCKED");
    const research = screen.getByRole("button", { name: "Research" });
    research.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { name: "Research" })).toBeTruthy();
    expect(research.getAttribute("aria-current")).toBe("page");
    expect(
      screen
        .getByRole("link", { name: "Skip to workspace" })
        .getAttribute("href"),
    ).toBe("#workspace");
  });
  it("has no axe violations in sign-in semantics", async () => {
    const { container } = render(<App />);
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
  it("has no axe violations in any of the five views", async () => {
    // Only intervals are faked, so the one-second clock cannot tick during axe.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => answer(populated)),
    );
    const { container } = render(<App />);
    const user = await connect();
    await screen.findByText("Execution DISABLED · LIVE LOCKED");
    for (const name of areas) {
      await user.click(screen.getByRole("button", { name }));
      expect(screen.getByRole("heading", { name })).toBeTruthy();
      const results = await axe.run(container, {
        rules: { "color-contrast": { enabled: false } },
      });
      expect(results.violations, name).toEqual([]);
    }
  });
  it("has no axe violations in the disconnected retained state", async () => {
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementationOnce(() => answer(populated))
        .mockRejectedValue(new Error("offline")),
    );
    const { container } = render(<App />);
    const user = await connect();
    await screen.findByText("Execution DISABLED · LIVE LOCKED");
    await user.click(screen.getByRole("button", { name: "Refresh reads" }));
    await screen.findByText(/RETAINED SNAPSHOT/);
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});
