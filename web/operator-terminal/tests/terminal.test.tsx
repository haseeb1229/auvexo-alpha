import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { describe, expect, it, vi } from "vitest";
import App, { Terminal } from "../src/App";
import { ReadFailure, readSnapshot } from "../src/client";
import { parseSnapshot } from "../src/contracts";
import fixture from "./synthetic-snapshot.json";

const syntheticToken = "synthetic-test-diagnostics-only-0000";
const answer = () => new Response(JSON.stringify(fixture), { status: 200 });
async function connect() {
  const user = userEvent.setup();
  await user.type(
    screen.getByLabelText("Runtime access token"),
    syntheticToken,
  );
  await user.click(screen.getByRole("button", { name: /Connect locally/ }));
  return user;
}
describe("presentation contract", () => {
  it("validates exact backend-generated synthetic DTO", () => {
    const data = parseSnapshot(fixture);
    expect(data.paper.balance).toBeNull();
    expect(data.qualification.phase4_days).toBeNull();
    expect(data.research.outcomes).toEqual([
      "INCONCLUSIVE",
      "INCONCLUSIVE",
      "INCONCLUSIVE",
      "INCONCLUSIVE",
    ]);
  });
  it.each(["UNKNOWN", "UNAVAILABLE"])(
    "refuses reservations in %s projection",
    (state) => {
      const x = structuredClone(fixture);
      x.paper.freshness.state = state;
      (x.paper as Record<string, unknown>).reservations = [
        {
          intent_hash: "a".repeat(64),
          state: "ACTIVE",
          instrument: "BTCUSDT",
          quantity: "1",
          notional: "100",
          modeled_loss: "1",
        },
      ];
      expect(() => parseSnapshot(x)).toThrow("INVALID_CONTRACT");
    },
  );
  it.each([
    "schema",
    "authority",
    "field",
    "amount",
    "hash",
    "time",
    "calendar",
  ])("refuses malformed %s", (kind) => {
    const x = structuredClone(fixture) as Record<string, unknown>;
    if (kind === "schema") x.contract_version = "2";
    if (kind === "field") x.dsn = "synthetic-secret";
    if (kind === "authority")
      (x.system as Record<string, unknown>).execution_enabled = true;
    if (kind === "amount") (x.paper as Record<string, unknown>).balance = "NaN";
    if (kind === "hash")
      (x.journal as Record<string, unknown>).events = [
        {
          sequence: 1,
          observed_at: "2026-01-01T00:00:00Z",
          reason: "AUTHORIZED",
          intent_hash: null,
          evidence_hash: "not-a-hash",
          decision_hash: null,
        },
      ];
    if (kind === "calendar")
      (
        (x.system as Record<string, unknown>).freshness as Record<
          string,
          unknown
        >
      ).observed_at = "2026-02-30T12:00:00Z";
    if (kind === "time")
      (
        (x.system as Record<string, unknown>).freshness as Record<
          string,
          unknown
        >
      ).observed_at = "yesterday";
    expect(() => parseSnapshot(x)).toThrow("INVALID_CONTRACT");
  });
});
describe("owner bootstrap and token", () => {
  it("loads data-free sign-in without any API request", () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    expect(
      screen.getByRole("heading", { name: "Owner terminal" }),
    ).toBeTruthy();
    expect(screen.queryByText(/Execution DISABLED/)).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
  });
  it("sends token only in header and clears session on signout", async () => {
    const fetcher = vi.fn().mockImplementation(answer);
    vi.stubGlobal("fetch", fetcher);
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const log = vi.spyOn(console, "log");
    render(<App />);
    const user = await connect();
    await screen.findByRole("heading", { name: "Command Center" });
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8765/api/v1/terminal/snapshot");
    expect(url).not.toContain(syntheticToken);
    expect(options.headers).toEqual({
      Authorization: `Bearer ${syntheticToken}`,
    });
    expect(options.credentials).toBe("omit");
    expect(storage).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
    expect(window.location.href).not.toContain(syntheticToken);
    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(screen.getByLabelText("Runtime access token")).toHaveProperty(
      "value",
      "",
    );
    expect(screen.queryByText(/Mode RESEARCH/)).toBeNull();
  });
  it("shows loading before a response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise(() => {})),
    );
    render(<App />);
    await connect();
    expect(screen.getByText(/Loading read-only snapshot/)).toBeTruthy();
  });
  it("clears token and all data on unauthorized", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("", { status: 401 })),
    );
    render(<App />);
    await connect();
    await screen.findByRole("alert");
    expect(
      screen.getByRole("heading", { name: "Owner terminal" }),
    ).toBeTruthy();
    expect(screen.getByLabelText("Runtime access token")).toHaveProperty(
      "value",
      "",
    );
  });
  it("retains previous snapshot only with visible STALE after disconnect", async () => {
    const fetcher = vi
      .fn()
      .mockImplementationOnce(answer)
      .mockRejectedValue(new Error("sensitive internal text"));
    vi.stubGlobal("fetch", fetcher);
    render(<App />);
    const user = await connect();
    await screen.findByRole("heading", { name: "Command Center" });
    await user.click(screen.getByRole("button", { name: "Refresh reads" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("STALE"),
    );
    expect(screen.queryByText("sensitive internal text")).toBeNull();
    expect(
      screen.getByRole("heading", { name: "Command Center" }),
    ).toBeTruthy();
  });
  it("shows unavailable without inventing an empty current portfolio", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(Error("secret driver error")),
    );
    render(<App />);
    await connect();
    await screen.findByRole("alert");
    expect(screen.getByText(/UNAVAILABLE \/ UNKNOWN/)).toBeTruthy();
    expect(screen.queryByText("secret driver error")).toBeNull();
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
    expect(screen.queryByText(/Mode RESEARCH/)).toBeNull();
  });
});
describe("truthful views and accessibility", () => {
  it.each([
    "Command Center",
    "Risk / PAPER",
    "Research",
    "Journal / evidence",
    "System Health",
  ] as const)("renders %s", (area) => {
    render(<Terminal data={parseSnapshot(fixture)} area={area} />);
    expect(screen.getByRole("heading", { name: area })).toBeTruthy();
  });
  it("keeps four INCONCLUSIVE and no candidate/champion", () => {
    render(<Terminal data={parseSnapshot(fixture)} area="Research" />);
    expect(
      screen.getAllByRole("heading", { name: "INCONCLUSIVE" }),
    ).toHaveLength(4);
    expect(screen.getAllByText("NONE")).toHaveLength(2);
  });
  it("preserves UNKNOWN account values", () => {
    render(<Terminal data={parseSnapshot(fixture)} area="Risk / PAPER" />);
    expect(screen.getByText(/Position state UNKNOWN/)).toBeTruthy();
    expect(
      screen.queryByText("No positions reported by projection."),
    ).toBeNull();
  });
  it("is keyboard operable with a skip link", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(answer));
    render(<App />);
    const user = await connect();
    await screen.findByRole("heading", { name: "Command Center" });
    const research = screen.getByRole("button", { name: "Research" });
    research.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("heading", { name: "Research" })).toBeTruthy();
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
  it("has no axe violations in read-only terminal semantics", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(answer));
    const { container } = render(<App />);
    await connect();
    await screen.findByRole("heading", { name: "Command Center" });
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
  it("XSS-like arbitrary values fail validation before rendering", () => {
    const x = structuredClone(fixture);
    x.system.mode = "<script>bad</script>";
    expect(() => parseSnapshot(x)).toThrow();
  });
});
describe("safe HTTP errors", () => {
  it.each([403, 500, 503])(
    "redacts backend %i response text",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response("private DSN", { status })),
      );
      await expect(
        readSnapshot(syntheticToken, new AbortController().signal),
      ).rejects.toBeInstanceOf(ReadFailure);
    },
  );
});
