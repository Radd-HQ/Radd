/** The built SPA over a mocked API, for the fixture proofs: `web/dist` with an index.html fallback
 *  and each plugin's built remote under /plugins/<name>/. The proof's own handler goes first. */
import { existsSync, readFileSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../../../", import.meta.url));
export const DIST = resolve(root, "web/dist");
const MIME = { ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".html": "text/html",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" };

const isFile = (file) => existsSync(file) && statSync(file).isFile();

/** Send a file with the content type its extension implies. */
export function sendFile(res, file) {
  res.writeHead(200, { "content-type": MIME[extname(file)] ?? "application/octet-stream" });
  res.end(readFileSync(file));
}

/** Send JSON (`status` 200 by default). */
export function sendJson(res, data, status = 200) {
  res.writeHead(status, { "content-type": "application/json" });
  res.end(JSON.stringify(data));
}

/** The request body as text. */
export function readBody(req) {
  return new Promise((done) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => done(Buffer.concat(chunks).toString()));
  });
}

/** A plugin's built remote file, e.g. `remoteFile("slas", "remoteEntry.js")`. */
export const remoteFile = (plugin, file) => resolve(root, "server/src/radd/modules", plugin, "ui/dist", file);

/** Answer /plugins/<name>/<file> from that plugin's built remote, or 404. */
export function sendRemote(res, pathname) {
  const [, , plugin, ...rest] = pathname.split("/");
  const file = remoteFile(plugin, rest.join("/"));
  if (isFile(file)) return sendFile(res, file);
  res.writeHead(404);
  res.end();
}

/** Answer `pathname` from web/dist, or with index.html for an app route. */
export function sendSpa(res, pathname) {
  const file = resolve(DIST, `.${decodeURIComponent(pathname)}`);
  sendFile(res, file.startsWith(DIST + sep) && isFile(file) ? file : resolve(DIST, "index.html"));
}

/**
 * Listen on a free port. `handle(req, res, url)` goes first and returns truthy when it answered;
 * /plugins/* then comes from the built remotes and everything else from the SPA.
 * Returns `{ server, origin, close }`.
 */
export async function serveBuiltSpa(handle = () => false) {
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, "http://127.0.0.1");
    if (await handle(req, res, url)) return;
    if (url.pathname.startsWith("/plugins/")) sendRemote(res, url.pathname);
    else sendSpa(res, url.pathname);
  });
  await new Promise((done) => server.listen(0, "127.0.0.1", done));
  return {
    server,
    origin: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise((done) => server.close(done)),
  };
}
