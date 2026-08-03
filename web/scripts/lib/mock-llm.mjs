/**
 * A stand-in OpenAI-compatible chat endpoint, for proving OUR AI orchestration.
 *
 * The thing under test in `ai-surface-proof` is the chain we own — stream in,
 * splice over the selection, hand the new document to the diff plugin, render a
 * review — not a model's opinion about grammar. Depending on a real provider
 * makes the proof fail whenever someone else's GPU is off, which is how a proof
 * stops being run.
 *
 * It streams a FIXED correction, so the diff is deterministic and the assertion
 * can name the words that changed.
 */
import { createServer } from "node:http";

export const MOCK_REPLY =
  "The cache is invalidated on write and never on read, which is fine.";

export function startMockLlm(port = 8111, reply = MOCK_REPLY) {
  const server = createServer((req, res) => {
    if (req.url?.startsWith("/v1/models")) {
      res.writeHead(200, { "content-type": "application/json" });
      res.end(JSON.stringify({ data: [{ id: "mock-1", object: "model" }] }));
      return;
    }
    if (!req.url?.startsWith("/v1/chat/completions")) {
      res.writeHead(404).end();
      return;
    }
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      const streaming = /"stream"\s*:\s*true/.test(body);
      if (!streaming) {
        res.writeHead(200, { "content-type": "application/json" });
        res.end(JSON.stringify({
          choices: [{ message: { role: "assistant", content: reply }, finish_reason: "stop" }],
        }));
        return;
      }
      res.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
      });
      // A word at a time, so the proof exercises accumulation rather than a
      // single frame that would pass even if chunks were being dropped.
      const words = reply.split(" ");
      let i = 0;
      const tick = setInterval(() => {
        if (i >= words.length) {
          clearInterval(tick);
          res.write("data: [DONE]\n\n");
          res.end();
          return;
        }
        const delta = (i === 0 ? "" : " ") + words[i++];
        res.write(`data: ${JSON.stringify({ choices: [{ delta: { content: delta } }] })}\n\n`);
      }, 30);
    });
  });
  return new Promise((resolve) => {
    server.listen(port, "127.0.0.1", () => resolve({ server, port, close: () => server.close() }));
  });
}
