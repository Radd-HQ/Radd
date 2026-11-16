// RADD-1529: what the password forms refuse before sending.
//   node --test web/scripts/password-panel.test.mjs   (from the repo root)
import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import { test } from "node:test";

// The rule is a pure function in a component file whose imports node cannot resolve;
// it is lifted out by name, and must agree with the server's bound.
const source = readFileSync("web/src/components/settings/PasswordPanel.tsx", "utf8");
const min = Number(source.match(/PASSWORD_MIN_LENGTH = (\d+)/)[1]);
const serverMin = Number(
  readFileSync("server/src/radd/modules/auth/schemas.py", "utf8").match(/_NewPassword = Field\(min_length=(\d+)/)[1],
);

test("the form's minimum is the server's", () => {
  assert.equal(min, serverMin, "PASSWORD_MIN_LENGTH drifted from auth/schemas.py _NewPassword");
});
