# Publication hygiene

Radd's repository is **https://github.com/radd-hq/radd**: the source of truth,
carrying the project's full history. Releases are tagged there, GitHub Actions
builds the image, the SBOMs and the vulnerability reports, publishes the
release, and the tracker follows it through the GitHub connector. The
self-hosted Forgejo at `git.radd-hq.com` keeps a read-only pull mirror as a
backup and hosts the private deployment repository; nothing is pushed to it.

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

Then on GitHub: make `main` the default branch and protect it (no force-push,
no deletion, admins included), and register the repository webhook that feeds
the tracker (Settings → GitHub on the instance says what to send where).

**Landing a pull request.** The checks workflow has to be green; a maintainer
reads the change and, when it touches UI, runs a render-proof. Land it with
*Rebase and merge* so each commit keeps its `[RADD-####]` key and arrives on the
issue's Version control tab through the connector; a squash is fine when the PR
is one issue's worth of work and its title carries the key.

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
