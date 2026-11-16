// RADD-1528: what the browser reports, and how often.
//   node --test web/scripts/report-error.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { evaluateTs } from "./lib/load-ts.mjs";

// The module imports the host's constants alias, which node cannot resolve — supplied by name.
const { describeClientError, admitClientError, CLIENT_ERROR_MAX_REPORTS } = evaluateTs(
  readFileSync("web/src/lib/report-error.ts", "utf8"),
  { API_BASE: "/api/v1" },
  ["describeClientError", "admitClientError", "CLIENT_ERROR_MAX_REPORTS"],
);

test("a report carries the path, never the query string, and is bounded", () => {
  const error = new TypeError("x".repeat(2000));
  const report = describeClientError(error, "route", { route: "/search?q=secret#frag", build: "index-abc" });
  assert.equal(report.route, "/search");
  assert.equal(report.message.length, 500);
  assert.ok(report.message.startsWith("TypeError: "));
  assert.equal(report.build, "index-abc");
  assert.equal(describeClientError("plain string", "window", { route: "/", build: "" }).message, "plain string");
  assert.equal(describeClientError(undefined, "rejection", { route: "/", build: "" }).message, "unknown error");
});

test("a render loop is one report, and a tab goes quiet after its allowance", () => {
  const sent = new Set();
  const report = (message, plugin = "") => describeClientError(new Error(message), "slot", { route: "/", build: "", plugin });
  assert.equal(admitClientError(sent, report("boom")), true);
  assert.equal(admitClientError(sent, report("boom")), false, "the same error twice is one report");
  assert.equal(admitClientError(sent, report("boom", "ai")), true, "another plugin's is its own");
  for (let index = sent.size; index < CLIENT_ERROR_MAX_REPORTS; index++) {
    assert.equal(admitClientError(sent, report(`other ${index}`)), true);
  }
  assert.equal(admitClientError(sent, report("one too many")), false);
});
