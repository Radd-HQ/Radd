import { ApiError } from "./api";
import { API_BASE } from "./constants";

/**
 * POST an API path and consume the `text/event-stream` reply as an async
 * string generator (spec 103: the editor AI stream). Plain fetch for the same
 * reason as attachments.ts — the typed client is JSON-in/JSON-out; everything
 * else (cookies, the pre-stream error shape: ApiError, so `isAiGone()` and
 * `aiErrorText()` keep working) matches it.
 *
 * Frame contract: a plain `data: {"t": …}` frame yields its `t`; a terminal
 * `event: done` ends the stream; an in-band `event: error` throws its detail
 * (the HTTP status was already 200 by then — mid-stream provider failures
 * can only arrive in-band).
 */
export async function* streamSse(
  path: string,
  body: unknown,
  signal: AbortSignal,
): AsyncGenerator<string> {
  for await (const payload of streamSseFrames(path, body, signal)) {
    const parsed = parseFramePayload(payload) as { t?: unknown };
    if (typeof parsed?.t === "string") yield parsed.t;
  }
}

/** Like `streamSse`, but yields each data frame's parsed JSON OBJECT — for
 * streams whose frames are structured records (similar-reasons: one
 * `{key, score, reason}` per candidate) rather than text chunks. */
export async function* streamSseJson(
  path: string,
  body: unknown,
  signal: AbortSignal,
): AsyncGenerator<Record<string, unknown>> {
  for await (const payload of streamSseFrames(path, body, signal)) {
    const parsed = parseFramePayload(payload);
    if (parsed !== undefined) yield parsed as Record<string, unknown>;
  }
}

function parseFramePayload(payload: string): unknown {
  try {
    const parsed: unknown = JSON.parse(payload);
    return parsed !== null && typeof parsed === "object" ? parsed : undefined;
  } catch {
    return undefined; // malformed data frame — skip rather than kill the stream
  }
}

async function* streamSseFrames(
  path: string,
  body: unknown,
  signal: AbortSignal,
): AsyncGenerator<string> {
  const response = await fetch(API_BASE + path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    let detail: unknown = response.statusText;
    try {
      detail = ((await response.json()) as { detail?: unknown }).detail ?? detail;
    } catch {
      // non-JSON error body — keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  if (!response.body) throw new ApiError(response.status, "Empty stream response");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return; // stream closed without `event: done` — treat as complete
      buffer += decoder.decode(value, { stream: true });
      let boundary: number;
      while ((boundary = buffer.indexOf(FRAME_SEPARATOR)) !== -1) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + FRAME_SEPARATOR.length);
        const chunk = dispatchFrame(frame);
        if (chunk === END_OF_STREAM) return;
        if (chunk !== undefined) yield chunk;
      }
    }
  } finally {
    // An early generator close (consumer abort/return) must also drop the
    // network read, not leave the response streaming into a dead buffer.
    void reader.cancel().catch(() => undefined);
  }
}

/** Wire event names the backend stream emits (default/unnamed = a data chunk). */
const SseEvent = {
  done: "done",
  error: "error",
} as const;

const FRAME_SEPARATOR = "\n\n";
const END_OF_STREAM = Symbol("end of SSE stream");

/**
 * One raw frame → its data payload string, END_OF_STREAM, or undefined
 * (ignorable frame). An `event: error` frame throws its JSON `detail`.
 */
function dispatchFrame(frame: string): string | typeof END_OF_STREAM | undefined {
  let event = "";
  const data: string[] = [];
  for (const rawLine of frame.split("\n")) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith("event:")) event = line.slice("event:".length).trim();
    // Per the SSE spec: join multi `data:` lines with \n, strip one leading space.
    else if (line.startsWith("data:")) data.push(line.slice("data:".length).replace(/^ /, ""));
  }
  if (event === SseEvent.done) return END_OF_STREAM;
  const payload = data.join("\n");
  if (event === SseEvent.error) throw new Error(errorDetail(payload));
  if (event !== "" || payload === "") return undefined; // unknown event / comment frame
  return payload;
}

const STREAM_FAILED_MESSAGE = "AI stream failed.";

function errorDetail(payload: string): string {
  try {
    const parsed = JSON.parse(payload) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
  } catch {
    // fall through to the generic message
  }
  return STREAM_FAILED_MESSAGE;
}
