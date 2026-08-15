# Publishing the public repository

The public repo starts from **one squashed initial commit** of a cleaned tree
(decided on RADD-688). This is not cosmetic: files that must never be public
were tracked in this repository's history for weeks, and `git rm` does not
remove what a clone already carries. A fresh initial commit is the only
publication mode where no scan can miss what simply isn't there. This
repository stays private as the full 337-commit archive; per-version release
notes remain browsable on the Forgejo releases page and the wiki.

## The procedure

From a clean checkout of the commit being published:

```bash
sh scripts/publish-gate.sh          # must print CLEAN — see below
git checkout --orphan public-main   # same tree, no parents
git add -A
git commit -s -m "Radd <version> — initial public release"
git remote add public <public-repo-url>
git push public public-main:main
```

Then on the public host: make `main` the default branch, protect it, and tag
`v<version>` there so the publish workflow builds the image from the public
repo going forward. **After launch the public repository is THE repository** —
development continues there; this archive is frozen, kept for provenance.

## The gate

`scripts/publish-gate.sh` refuses a tree that carries:

- machine-absolute paths or private-IP literals outside deploy examples;
- tracked `.env`, key material, or dump-shaped files;
- any pattern in `var/publish-denylist.txt` — the operator-specific names
  (origin company, internal hostnames). That file is **deliberately
  untracked**: a tracked denylist would ship the very words it blocks. The
  gate fails loudly when the file is missing rather than passing vacuously.
- secrets, when `gitleaks` is installed (tree-level; history never ships
  under this procedure, which is the point).

Run it before every push to the public remote, not only the first: the gate
is the ratchet that keeps a later commit from re-introducing what the launch
scrubbed (RADD-1076).

## What deliberately stays

`Jira` where it names the import feature (nominative use — you may say what
you interoperate with), `radd-hq.com` as the project's own infrastructure,
and the full narrative docs (PLAN.md, BUILD-LOG.md, docs/specs/) — the
build's history is part of the product's story; only its provenance and
other people's data were removed.
