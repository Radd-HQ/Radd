# Publication hygiene

Radd's public repository is **https://github.com/radd-hq/radd**, and it carries
the project's full history. The self-hosted Forgejo at `git.radd-hq.com/Radd/Radd`
remains the **source of truth and the build host**: releases are tagged there,
its pipeline builds the image, the SBOMs and the vulnerability reports, and a
push mirror publishes every commit and tag to GitHub within minutes. GitHub is
where issues, discussions and pull requests arrive.

The history is publishable because it was **rewritten once, before the first
public push**: an Active Directory export, a real-content import sample, the
scripts that produced them, the origin organisation's name and hosts, partner
domains, a leaked service secret and machine paths were removed from every
commit with `git filter-repo`, commit messages included, and the result was
checked against the operator denylist, a list of every person in the removed
export, an e-mail-domain census and a gitleaks scan of all commits. The rewrite
is not repeatable without another hash change for every commit, so **the gate
below runs before every push**, not only at launch.

## The launch procedure

From a clean checkout of `main` with all tags:

```bash
sh scripts/publish-gate.sh          # must print CLEAN — see below
gitleaks git .                      # must print "no leaks found"
git remote add github git@github.com:radd-hq/radd.git
git push github main --tags
```

Then on GitHub: make `main` the default branch and protect it (no direct
pushes; maintainers land PRs through Forgejo), and configure the Forgejo push
mirror (repository settings → Mirror settings → *Push to a remote repository*,
or `POST /api/v1/repos/Radd/Radd/push_mirrors` with `sync_on_commit: true`) so
the manual push above is the last one anyone makes to GitHub directly.

**Landing a GitHub pull request.** Fetch its head, validate it with the same
gates a release goes through, and push it to Forgejo `main`; the mirror carries
it back to GitHub and GitHub closes the PR as merged when it sees the commits.
Never merge on GitHub: that would fork the two histories.

```bash
git fetch https://github.com/radd-hq/radd.git pull/<n>/head:pr-<n>
git checkout pr-<n>
cd server && uv run pytest -q && cd ../web && npm run check
```

## The gate

`scripts/publish-gate.sh` is the ratchet that keeps the tree publishable. It
refuses a tree that carries:

- machine-absolute paths (plain or dash-encoded) outside deploy examples;
- tracked `.env`, key material, or dump-shaped files;
- any pattern in `var/publish-denylist.txt` — an operator-local list of
  strings that must never appear. That file is **deliberately untracked**
  (each operator keeps their own); the gate fails loudly when the file is
  missing rather than passing vacuously.
- secrets, when `gitleaks` is installed. Install it: with history now public,
  the tree-level scan is not optional, and `gitleaks git .` covers every
  commit.

The denylist must hold more than the organisation's name. Two scrub rounds
missed material that carried no denylisted word: partner organisations'
domains, individual employees' names inside test fixtures, dash-encoded paths,
a headcount, a service secret in a config example. When something is added to
the denylist, run the check over `git log -p`, not only the working tree.

## What deliberately stays

`Jira` and `Confluence` where they name the importers (nominative use — you
may say what you interoperate with), `radd-hq.com` as the project's own
infrastructure, the maintainer's own name and public address, and the full
narrative docs (PLAN.md, BUILD-LOG.md, docs/specs/) — the build's history is
part of the product's story. The scrub replaced identities, not the record of
what was built and why.
