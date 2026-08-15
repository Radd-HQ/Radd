<!-- Thanks! Two mechanical things reviews always check first: -->

**Issue.** `[RADD-###]` in the commit message (or describe the problem fully
here and a maintainer will file it — see docs/contributing.md).

**Gates run locally** (CI does not run on fork PRs — your word here is what
review starts from):

- [ ] `cd server && uv run pytest -q`
- [ ] `cd web && ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build`
- [ ] UI change? Looked at the rendered result (see `web/scripts/render-proof.mjs`)

**What changes and why** — including the option you rejected, if you weighed
one.

**Sign-off.** `git commit -s` certifies the Developer Certificate of Origin.
