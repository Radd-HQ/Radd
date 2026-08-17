# Publication hygiene

Radd's public repository began at a single squashed initial commit (decided on
RADD-688) — a standard practice for projects that graduate from a private
incubation repo: the public tree starts exactly at its reviewed, launch-ready
state, and pre-launch scaffolding stays in a private archive. Per-version
release notes remain browsable on the releases page and in the wiki's Release
notes space.

## The launch procedure

From a clean checkout of the commit being published:

```bash
sh scripts/publish-gate.sh          # must print CLEAN — see below
git checkout --orphan public-main   # same tree, no parents
git add -A
git commit -s -m "Radd <version> — initial public release"
git remote add public <public-repo-url>
git push public public-main:main
```

Then repoint the clone URLs in README.md and docs/contributing.md at the
public host, and on the public host: make `main` the default branch, protect it, and tag
`v<version>` there so the publish workflow builds the image from the public
repo going forward. **After launch the public repository is THE repository** —
development continues there.

## The gate

`scripts/publish-gate.sh` is the ratchet that keeps the tree publishable. It
refuses a tree that carries:

- machine-absolute paths (plain or dash-encoded) outside deploy examples;
- tracked `.env`, key material, or dump-shaped files;
- any pattern in `var/publish-denylist.txt` — an operator-local list of
  strings that must never appear. That file is **deliberately untracked**
  (each operator keeps their own); the gate fails loudly when the file is
  missing rather than passing vacuously.
- secrets, when `gitleaks` is installed.

Run it before every push, not only at launch: the gate is what keeps a later
commit from re-introducing what a scrub removed (RADD-1076).

## What deliberately stays

`Jira` where it names the import feature (nominative use — you may say what
you interoperate with), `radd-hq.com` as the project's own infrastructure,
and the full narrative docs (PLAN.md, BUILD-LOG.md, docs/specs/) — the
build's history is part of the product's story.
