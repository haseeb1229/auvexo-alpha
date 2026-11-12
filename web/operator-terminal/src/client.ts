import { parseSnapshot } from "./contracts";

// UNAUTHORIZED     401: the bearer was refused; the only code that ends the session.
// ORIGIN_REFUSED   403, or this page was not opened at http://127.0.0.1:<port>.
// DISCONNECTED     no HTTP response: network failure, refused connection or timeout.
// UNAVAILABLE      the backend answered but could not serve the read (503, other).
// INVALID_CONTRACT the payload failed validation: UI and backend versions differ.
export type ReadFailureCode =
  | "UNAUTHORIZED"
  | "ORIGIN_REFUSED"
  | "DISCONNECTED"
  | "UNAVAILABLE"
  | "INVALID_CONTRACT";
export class ReadFailure extends Error {
  constructor(
    readonly code: ReadFailureCode,
    readonly status: number | null = null,
  ) {
    super(code);
  }
}
export function apiOrigin(): string {
  const origin = import.meta.env.DEV
    ? "http://127.0.0.1:8765"
    : window.location.origin;
  let url: URL;
  try {
    url = new URL(origin);
  } catch {
    throw new ReadFailure("ORIGIN_REFUSED");
  }
  if (
    url.hostname !== "127.0.0.1" ||
    url.protocol !== "http:" ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new ReadFailure("ORIGIN_REFUSED");
  return url.origin;
}
// A header value must be Latin-1 without control characters, otherwise fetch throws
// before any request exists. Refuse such input up front with a clear message.
export function tokenProblem(token: string): string | null {
  if (!token) return "Enter your runtime token.";
  if (!/^[\x20-\x7e\xa0-\xff]+$/.test(token))
    return "Token contains characters that cannot be sent in a request header. Paste the runtime token exactly as issued, without line breaks or non-Latin characters.";
  return null;
}
export async function readSnapshot(token: string, signal: AbortSignal) {
  const origin = apiOrigin();
  let response: Response;
  try {
    response = await fetch(`${origin}/api/v1/terminal/snapshot`, {
      method: "GET",
      headers: { Authorization: `Bearer ${token}` },
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
      signal: AbortSignal.any([signal, AbortSignal.timeout(5000)]),
    });
  } catch {
    throw new ReadFailure("DISCONNECTED");
  }
  if (response.status === 401) throw new ReadFailure("UNAUTHORIZED", 401);
  if (response.status === 403) throw new ReadFailure("ORIGIN_REFUSED", 403);
  if (!response.ok) throw new ReadFailure("UNAVAILABLE", response.status);
  let text: string;
  try {
    text = await response.text();
  } catch {
    throw new ReadFailure("DISCONNECTED");
  }
  try {
    if (text.length > 1048576) throw Error();
    return parseSnapshot(JSON.parse(text));
  } catch {
    throw new ReadFailure("INVALID_CONTRACT", response.status);
  }
}
