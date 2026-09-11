# Contributing

Radd is developed on a self-hosted Forgejo at **https://git.radd-hq.com/Radd/Radd**.
Anyone can sign in with Google, fork, and open a pull request. Be kind — the
[code of conduct](../CODE_OF_CONDUCT.md) applies everywhere the project talks.
Security problems go to [SECURITY.md](../SECURITY.md)'s private channel, never
a public issue.

## Licensing of contributions

Radd is AGPL-3.0-only (the SDKs are Apache-2.0 — see the README's License
section). By opening a pull request you certify the
[Developer Certificate of Origin](https://developercertificate.org/): the work
is yours to contribute, and you license it under the file's governing license.
Add a `Signed-off-by:` line (`git commit -s`) to say so explicitly. No CLA, no
copyright assignment — you keep your copyright.

## Getting set up

You need: **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)**, **Node 22+**
with npm, and **podman** (or docker) for Postgres. The suite needs a
**Postgres 16+**; pgvector is optional (without it, search is plain FTS and the
pgvector tests self-skip).

```bash
git clone https://git.radd-hq.com/Radd/Radd.git
cd Radd

# Backend — dev db (:5456) + live-reloading API on :8000.
# The container runs `alembic upgrade head` itself; seed inside it:
podman compose -f compose.dev.yaml up
podman compose -f compose.dev.yaml exec app \
  python -m radd.seed --email you@example.com --password … --name "You"

# Host-side tools (pytest, alembic) need the dev db's port:
cd server && uv sync
export RADD_DATABASE_URL=postgresql+psycopg://radd:radd@localhost:5456/radd

# Frontend
cd ../web && npm install
npm run build      # refreshes the bundle served at :8000; `npm run dev` for :5173
```

`docs/deploy.md` covers running it properly; `CLAUDE.md` is the map of how the
codebase is put together and the conventions a change is expected to follow.

## Before you open a pull request

```bash
cd server && uv run pytest -q            # the suite builds its own throwaway database
cd ../web && npm run check
```

**Building is not verifying.** A clean `tsc` proves nothing about whether a UI
change renders correctly — `web/scripts/render-proof.mjs` shows the zero-dep
pattern for driving headless Chromium and measuring the result. Several bugs
have shipped past a green build because nobody looked at the output.

## What a good change looks like

The conventions in `CLAUDE.md` are not stylistic preferences; they are what
keeps the module boundaries real:

- **Features are modules.** Code lives in `server/src/radd/modules/<name>/`,
  exposes a `plugin: RaddPlugin`, and talks to other modules only through their
  public `service.py`, emitted events, or declared extension points.
- **No hardcoded magic values.** Anything naming a behaviour, state or type is
  a `StrEnum` or a config field.
- **Document the connections.** A new module, event type or cross-module
  dependency gets its row in `docs/modules.md` in the same change.
- **Frontend uses the semantic tokens**, never raw palette utilities. A raw
  `zinc-*` or `indigo-*` class in `web/src` is a review finding.
- **Tests where they earn their keep** — core invariants many modules depend
  on, not a unit test per endpoint.
- **The change exists on the tracker first.** Maintainer work is filed in the
  **RADD** project at <https://project.radd-hq.com> (the public demo of Radd
  tracking itself). As an outside contributor you don't need an account there:
  file bugs and feature requests on **this repository's issue tracker**
  (templates ship in `.github/`), or describe the issue fully in your PR, or
  email <info@radd-hq.com> — a maintainer mirrors it into RADD and links your
  PR. The record must exist, not necessarily by your hand.

## Working in the tracker

Radd tracks its own development, and the project is public. Two consequences.

**Every commit names its issue, in brackets, at the front:**

```
[RADD-412] board columns scroll instead of clipping
```

One commit per issue — never against an epic, which is a container rather than a
unit of work. The bracket form auto-links: the Forgejo connector matches the key
and the commit appears in the issue's Version control tab with no extra step. If a
change genuinely spans two issues it is two commits; if it cannot be split, those
were one issue.

**Prefer fewer, meaningful issues with subtasks** over many tiny issues. The
subtask checklist on one issue is where steps belong; splitting work apart to have
something to reference is bureaucracy.

**Write the issue for someone who was not there.** What is wrong or wanted (with
the actual symptom or number), what changes and what you rejected, where in the
code, and the observable condition that means it is done. A one-sentence body is a
mention, not a filed issue.

**The lifecycle:** In Progress while you work → `Waiting for release` when it lands
(finished, not shipped — it sits in the `done` category, so throughput counts the
day the work was done) → a published release sweeps it to `Done` with the version
recorded.

## Pull requests

`main` is protected: it cannot be pushed to directly and merges require review.
Open a PR from your fork and it will be reviewed.

**CI does not yet run on pull requests.** A PR-check workflow (PR-head checkout,
disposable Postgres, `pytest`, `ruff`, `npm run check`) is prepared but not landed.
Forgejo executes the TARGET branch's workflows for a fork PR, so it only starts
protecting PRs once it is on `main` AND an isolated runner labelled `checks` exists
whose Docker daemon is not shared with release or deployment jobs, because fork code
executes there. The runner image in `deploy/ci-runner.version` (1.4.0) already carries
Chromium for it. Until then, run the gates locally and say so in the PR.

**How a maintainer validates a fork PR**: fetch the PR head locally
(`git fetch origin refs/pull/<n>/head && git checkout FETCH_HEAD`), then run
`uv run pytest -q` in `server/` and `npm run check` in `web/`, plus a render-proof when
the change touches UI. Never merge on the contributor's word alone; the tag build runs
the gates again anyway (the publish workflow's `test` job is the backstop).

`npm run check` in `web/` is the unified frontend gate. Set `RADD_CHROME` if Chromium is not on a standard path or in the Playwright cache. The browser test uses a local synthetic API for repeatability; UI changes also need relevant interactions against a real backend. `npm run build` remains the quick host-only build.

## Releases

Maintainers tag a version and CI publishes the container image:

```bash
git tag -a v0.34.0 -m "Radd 0.34.0" && git push origin v0.34.0
```

No `latest` tag is published — deployments pin an immutable version, so a
rollback is a config change rather than a race over what a moving tag points
at. Deployment itself lives in a separate private repository.

## Reporting issues

Issues go on the tracker at **https://project.radd-hq.com** — which is Radd,
running itself. Filing one is the most direct way to find out whether the
product works.
