# Contributing

Radd is developed on a self-hosted Forgejo at **https://git.radd-hq.com/Radd/Radd**.
Anyone can sign in with Google, fork, and open a pull request.

## Getting set up

```bash
git clone https://git.radd-hq.com/Radd/Radd.git
cd Radd

# Backend — Postgres 16+ with pgvector (optional; without it search is plain FTS)
podman compose -f compose.dev.yaml up      # db + API on :8000
cd server && uv sync && uv run alembic upgrade head
uv run python -m radd.seed --email you@example.com --password … --name "You"

# Frontend
cd web && npm run build      # or `npm run dev` on :5173
```

`docs/deploy.md` covers running it properly; `CLAUDE.md` is the map of how the
codebase is put together and the conventions a change is expected to follow.

## Before you open a pull request

```bash
cd server && uv run pytest -q            # the suite builds its own throwaway database
cd web && ./node_modules/.bin/tsc -b && ./node_modules/.bin/vite build
```

`test_merge_coverage` currently flags `view_members.added_by`; that failure is
known and not yours.

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

## Pull requests

`main` is protected: it cannot be pushed to directly and merges require review.
Open a PR from your fork and it will be reviewed.

**CI does not run on pull requests.** Forgejo executes the workflows from the
target branch rather than the PR's, so a workflow added in a PR has no effect —
and no workflow here triggers on `pull_request` anyway. Run the tests locally;
the results are what the review goes on.

## Releases

Maintainers tag a version and CI publishes the container image:

```bash
git tag -a v0.2.0 -m "Radd 0.2.0" && git push origin v0.2.0
```

No `latest` tag is published — deployments pin an immutable version, so a
rollback is a config change rather than a race over what a moving tag points
at. Deployment itself lives in a separate private repository.

## Reporting issues

Issues go on the tracker at **https://project.radd-hq.com** — which is Radd,
running itself. Filing one is the most direct way to find out whether the
product works.
