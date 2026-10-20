import { parseSnapshot } from "./contracts";
export class ReadFailure extends Error {
  constructor(
    readonly code: "UNAUTHORIZED" | "UNAVAILABLE" | "INVALID_CONTRACT",
  ) {
    super(code);
  }
}
export function apiOrigin(): string {
  const origin = import.meta.env.DEV
    ? "http://127.0.0.1:8765"
    : window.location.origin;
  const url = new URL(origin);
  if (
    url.hostname !== "127.0.0.1" ||
    url.protocol !== "http:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new ReadFailure("UNAVAILABLE");
  return url.origin;
}
export async function readSnapshot(token: string, signal: AbortSignal) {
  let response: Response;
  try {
    response = await fetch(`${apiOrigin()}/api/v1/terminal/snapshot`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal: AbortSignal.any([signal, AbortSignal.timeout(5000)]),
    });
  } catch {
    throw new ReadFailure("UNAVAILABLE");
  }
  if (response.status === 401 || response.status === 403)
    throw new ReadFailure("UNAUTHORIZED");
  if (!response.ok) throw new ReadFailure("UNAVAILABLE");
  try {
    const text = await response.text();
    if (text.length > 1048576) throw Error();
    return parseSnapshot(JSON.parse(text));
  } catch {
    throw new ReadFailure("INVALID_CONTRACT");
  }
}
