import { describe, expect, it, vi } from "vitest";
import schema from "../contract.schema.json";
import {
  apiOrigin,
  ReadFailure,
  readSnapshot,
  tokenProblem,
} from "../src/client";
import { ENUMS, KEYS, PATTERNS, parseSnapshot } from "../src/contracts";
import populated from "./synthetic-populated-snapshot.json";
import fixture from "./synthetic-snapshot.json";

const syntheticToken = "synthetic-test-diagnostics-only-0000";
type Json = Record<string, unknown>;
type Property = {
  const?: unknown;
  enum?: unknown[];
  anyOf?: Property[];
  prefixItems?: Property[];
};
type Definition = {
  properties: Record<string, Property>;
  required?: string[];
};
const definitions: Record<string, Definition> = {
  ...(schema.$defs as Record<string, Definition>),
  TerminalSnapshot: schema as unknown as Definition,
};
const isStatement = (name: string) =>
  name.startsWith("Reviewed") && name !== "ReviewedSummary";
function allowed(property: Property): unknown[] | null {
  if ("const" in property) return [property.const];
  if (property.enum) return property.enum;
  for (const option of property.anyOf ?? []) {
    const values = allowed(option);
    if (values) return values;
  }
  if (property.prefixItems)
    return [
      ...new Set(property.prefixItems.flatMap((item) => allowed(item) ?? [])),
    ];
  return null;
}
// Every object node of a value, as a path of keys and array indexes.
function objectPaths(value: unknown, path: (string | number)[] = []) {
  const found: (string | number)[][] = [];
  if (Array.isArray(value))
    value.forEach((item, index) => {
      found.push(...objectPaths(item, [...path, index]));
    });
  else if (value && typeof value === "object") {
    found.push(path);
    for (const [key, item] of Object.entries(value))
      found.push(...objectPaths(item, [...path, key]));
  }
  return found;
}
function at(root: unknown, path: (string | number)[]): Json {
  let node = root as Json;
  for (const step of path) node = node[step as string] as Json;
  return node;
}

describe("contract schema drift", () => {
  it("parser key tables equal every schema object's properties", () => {
    for (const [name, definition] of Object.entries(definitions)) {
      const keys = isStatement(name)
        ? KEYS.ReviewedStatement
        : KEYS[name as keyof typeof KEYS];
      expect(keys, name).toBeDefined();
      expect([...keys].sort(), name).toEqual(
        Object.keys(definition.properties).sort(),
      );
      for (const required of definition.required ?? [])
        expect(keys, `${name}.${required}`).toContain(required);
    }
    expect(Object.keys(KEYS).sort()).toEqual(
      [
        ...new Set(
          Object.keys(definitions).map((name) =>
            isStatement(name) ? "ReviewedStatement" : name,
          ),
        ),
      ].sort(),
    );
  });
  it("parser enum tables equal every schema enum and const", () => {
    const seen = new Set<string>();
    for (const [name, definition] of Object.entries(definitions))
      for (const [property, spec] of Object.entries(definition.properties)) {
        const values = allowed(spec);
        if (values === null) continue;
        if (values.some((value) => typeof value !== "string")) {
          // The single non-string constant: execution can never be enabled.
          expect(`${name}.${property}`).toBe("SystemView.execution_enabled");
          expect(values).toEqual([false]);
          continue;
        }
        const key =
          isStatement(name) && property !== "status"
            ? `ReviewedStatement.${property}`
            : `${name}.${property}`;
        expect(ENUMS[key as keyof typeof ENUMS], key).toEqual(values);
        seen.add(key);
      }
    expect([...seen].sort()).toEqual(Object.keys(ENUMS).sort());
  });
  it("parser patterns equal the schema patterns", () => {
    const patterns = new Set<string>();
    JSON.stringify(schema, (key, value) => {
      if (key === "pattern") patterns.add(value);
      return value;
    });
    expect([...patterns].sort()).toEqual(
      Object.values(PATTERNS)
        .map((pattern) => pattern.source)
        .sort(),
    );
  });
  it("refuses any missing or additional key at every object", () => {
    const paths = objectPaths(populated);
    expect(paths.length).toBeGreaterThan(30);
    for (const path of paths) {
      const extra = structuredClone(populated);
      at(extra, path).unexpected = "synthetic";
      expect(() => parseSnapshot(extra), path.join(".")).toThrow(
        "INVALID_CONTRACT",
      );
      for (const key of Object.keys(at(populated, path))) {
        const missing = structuredClone(populated);
        delete at(missing, path)[key];
        expect(() => parseSnapshot(missing), [...path, key].join(".")).toThrow(
          "INVALID_CONTRACT",
        );
      }
    }
  });
});

describe("presentation contract", () => {
  it("validates exact backend-generated unconnected DTO", () => {
    const data = parseSnapshot(fixture);
    expect(data.paper.balance).toBeNull();
    expect(data.qualification.phase4_days).toBeNull();
    expect(data.reviewed.ds03.status).toBe("ENGINEERING_ONLY_NO_ACCOUNT");
    expect(data.reviewed.phase4_observation.operational).toBe("UNKNOWN");
    expect(data.research.outcomes).toEqual([
      "INCONCLUSIVE",
      "INCONCLUSIVE",
      "INCONCLUSIVE",
      "INCONCLUSIVE",
    ]);
  });
  it("validates exact backend-generated populated DTO", () => {
    const data = parseSnapshot(populated);
    expect(data).toEqual(populated);
    expect(data.paper.kill).toBe("K4");
    expect(data.paper.reconciled).toBe(false);
    expect(data.paper.unknown_orders).toBe(true);
    expect(data.paper.positions).toHaveLength(2);
    expect(data.paper.reservations).toHaveLength(2);
    expect(data.paper.pending.map((x) => x.state)).toEqual(
      ENUMS["PendingView.state"],
    );
    expect(data.journal.events.map((x) => x.reason)).toEqual(
      ENUMS["JournalEvent.reason"],
    );
  });
  it.each(["K0", "K1", "K2", "K3", "K4"])("accepts kill level %s", (kill) => {
    const x = structuredClone(populated);
    x.paper.kill = kill;
    expect(parseSnapshot(x).paper.kill).toBe(kill);
  });
  it.each(["UNKNOWN", "UNAVAILABLE"])(
    "refuses reservations in %s projection",
    (state) => {
      const x = structuredClone(fixture);
      x.paper.freshness.state = state;
      (x.paper as Json).reservations = [
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
    [
      "schema version",
      (x: Json) => Object.assign(x, { contract_version: "2" }),
    ],
    ["extra field", (x: Json) => Object.assign(x, { dsn: "synthetic-secret" })],
    [
      "execution authority",
      (x: Json) => Object.assign(x.system as Json, { execution_enabled: true }),
    ],
    [
      "LIVE mode",
      (x: Json) => Object.assign(x.system as Json, { mode: "LIVE" }),
    ],
    [
      "DEMO mode",
      (x: Json) => Object.assign(x.system as Json, { mode: "DEMO" }),
    ],
    [
      "markup mode",
      (x: Json) =>
        Object.assign(x.system as Json, { mode: "<script>bad</script>" }),
    ],
    ["amount", (x: Json) => Object.assign(x.paper as Json, { balance: "NaN" })],
    ["kill level", (x: Json) => Object.assign(x.paper as Json, { kill: "K5" })],
    [
      "evidence hash",
      (x: Json) =>
        Object.assign(at(x, ["journal", "events", 0]), {
          evidence_hash: "not-a-hash",
        }),
    ],
    [
      "retired journal reason",
      (x: Json) =>
        Object.assign(at(x, ["journal", "events", 0]), {
          reason: "KILL_CHANGED",
        }),
    ],
    [
      "retired decision hash",
      (x: Json) =>
        Object.assign(at(x, ["journal", "events", 0]), { decision_hash: null }),
    ],
    [
      "operational claim in reviewed block",
      (x: Json) =>
        Object.assign(at(x, ["reviewed", "phase4_observation"]), {
          operational: "ACTIVE",
        }),
    ],
    [
      "retired active observation literal",
      (x: Json) =>
        Object.assign(at(x, ["reviewed", "phase4_observation"]), {
          status: "OBSERVATION_ACTIVE_OPERATIONAL_OPEN",
        }),
    ],
    [
      "measured provenance on reviewed wording",
      (x: Json) =>
        Object.assign(at(x, ["reviewed", "ds03"]), {
          provenance: "LOCAL_DIAGNOSTICS",
        }),
    ],
    [
      "reviewed date",
      (x: Json) => Object.assign(at(x, ["reviewed", "ds03"]), { as_of: "now" }),
    ],
    [
      "calendar",
      (x: Json) =>
        Object.assign(at(x, ["system", "freshness"]), {
          observed_at: "2026-02-30T12:00:00Z",
        }),
    ],
    [
      "time",
      (x: Json) =>
        Object.assign(at(x, ["system", "freshness"]), {
          observed_at: "yesterday",
        }),
    ],
    [
      "non-UTC time",
      (x: Json) =>
        Object.assign(at(x, ["system", "freshness"]), {
          observed_at: "2026-01-01T05:00:00+05:00",
        }),
    ],
  ])("refuses malformed %s", (_name, change) => {
    const x = structuredClone(populated) as Json;
    change(x);
    expect(() => parseSnapshot(x)).toThrow("INVALID_CONTRACT");
  });
});

describe("read client", () => {
  it.each([
    "http://localhost:8765",
    "https://127.0.0.1:8765",
    "http://192.168.1.10:8765",
    "http://[::1]:8765",
    "http://127.0.0.1.evil.example:8765",
    "http://evil.example",
    "null",
  ])("apiOrigin refuses %s and never fetches", async (origin) => {
    vi.stubEnv("DEV", false);
    vi.stubGlobal("location", { origin });
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    expect(() => apiOrigin()).toThrow(ReadFailure);
    await expect(
      readSnapshot(syntheticToken, new AbortController().signal),
    ).rejects.toMatchObject({ code: "ORIGIN_REFUSED", status: null });
    expect(fetcher).not.toHaveBeenCalled();
  });
  it.each(["http://127.0.0.1:8765", "http://127.0.0.1:9000"])(
    "apiOrigin accepts exact loopback %s",
    (origin) => {
      vi.stubEnv("DEV", false);
      vi.stubGlobal("location", { origin });
      expect(apiOrigin()).toBe(origin);
    },
  );
  it.each([
    [401, "UNAUTHORIZED"],
    [403, "ORIGIN_REFUSED"],
    [400, "UNAVAILABLE"],
    [404, "UNAVAILABLE"],
    [500, "UNAVAILABLE"],
    [503, "UNAVAILABLE"],
  ])("maps HTTP %i to %s without backend text", async (status, code) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("private DSN", { status })),
    );
    const failure = await readSnapshot(
      syntheticToken,
      new AbortController().signal,
    ).catch((e: unknown) => e);
    expect(failure).toBeInstanceOf(ReadFailure);
    expect(failure).toMatchObject({ code, status });
    expect(String(failure)).not.toContain("private DSN");
    expect(String(failure)).not.toContain(syntheticToken);
  });
  it("maps a network failure to DISCONNECTED", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("sensitive internal text")),
    );
    await expect(
      readSnapshot(syntheticToken, new AbortController().signal),
    ).rejects.toMatchObject({ code: "DISCONNECTED", status: null });
  });
  it.each([
    ["not json", "<html>proxy page</html>"],
    ["wrong shape", JSON.stringify({ ...fixture, dsn: "x" })],
    ["older contract", JSON.stringify({ ...fixture, reviewed: undefined })],
    ["oversized", " ".repeat(1048577)],
  ])("maps a %s 200 payload to INVALID_CONTRACT", async (_name, body) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(body, { status: 200 })),
    );
    await expect(
      readSnapshot(syntheticToken, new AbortController().signal),
    ).rejects.toMatchObject({ code: "INVALID_CONTRACT" });
  });
  it("sends the token only in the Authorization header", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(fixture)));
    vi.stubGlobal("fetch", fetcher);
    await readSnapshot(syntheticToken, new AbortController().signal);
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8765/api/v1/terminal/snapshot");
    expect(options.method).toBe("GET");
    expect(options.headers).toEqual({
      Authorization: `Bearer ${syntheticToken}`,
    });
    expect(options.credentials).toBe("omit");
    expect(options.cache).toBe("no-store");
    expect(options.redirect).toBe("error");
    expect(options.body).toBeUndefined();
  });
  it("validates token characters before any request", () => {
    expect(tokenProblem("")).toMatch(/Enter your runtime token/);
    for (const bad of [
      "tok☃en",
      "токен",
      "line\nbreak",
      "nul\u0000",
      "\u{1f642}",
    ])
      expect(tokenProblem(bad), bad).toMatch(/cannot be sent/);
    for (const good of [syntheticToken, "A-Za-z0-9._~+/=", "latin-é-ÿ"])
      expect(tokenProblem(good), good).toBeNull();
  });
});
