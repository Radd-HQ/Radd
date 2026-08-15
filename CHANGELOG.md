# Changelog

Release notes are **generated per tag**, not hand-maintained here — each
version's notes are built from its `[RADD-###]` issues (title, type, labels)
by `scripts/changelog.py` and published in two places by CI:

- **Forgejo releases:** <https://git.radd-hq.com/Radd/Radd/releases> — notes
  plus the SBOMs and vulnerability reports for that image.
- **The wiki's Release notes space** on <https://project.radd-hq.com> — the
  same notes as browsable pages, one per version, with an SBOM child page.

The repository's history itself is the fine-grained log: one commit per
issue, `[RADD-###]` up front, and the tracker holds the full write-up behind
every key.

> The public repository begins at the 1.0 launch commit; pre-1.0 history
> (0.1.0 → 0.33.x, ~120 build specs) lives in the private archive it was
> developed in, and its release notes remain browsable at the links above.
