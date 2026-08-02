"""Walking a snapshot's issues into an inbound profile (spec 100) — PURE.

One pass, feeding every counter at once: fields, the eight vocabularies, and the
people. Streaming rather than list-in-memory, because a real import is tens of
thousands of issues.

Nothing here decides policy. It counts what IS in the data; the mapping step
decides what to do about it.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .. import inference, issuemap, schemakeys
from ..types import BUILTIN_JIRA_FIELDS, InferredField, InferredType
from .types import InboundProfile, PersonEntry, VocabEntry

# Where a person can be named on an issue. Everything an import will need to
# attribute correctly, so nobody is silently credited to whoever ran it.
ROLE_ASSIGNEE = "assignee"
ROLE_REPORTER = "reporter"
ROLE_CREATOR = "creator"
ROLE_COMMENT = "comment author"
ROLE_WORKLOG = "worklog author"
ROLE_WATCHER = "watcher"
ROLE_ATTACHMENT = "attachment author"
ROLE_HISTORY = "history actor"


class ProfileAccumulator:
    """Feed it issues; ask it for a profile."""

    def __init__(self, catalog: dict[str, dict[str, Any]]):
        self.catalog = catalog or {}
        self.total = 0
        # Field statistics, mirroring what `inference.infer_schema` computes but
        # accumulated incrementally so the whole snapshot never sits in memory.
        self._populated: Counter[str] = Counter()
        self._array_seen: dict[str, bool] = {}
        self._samples: dict[str, list[str]] = {}
        self._distinct: dict[str, Counter[str]] = {}
        self._seen_ids: set[str] = set()
        # Vocabularies.
        self._issue_types: Counter[str] = Counter()
        self._statuses: Counter[str] = Counter()
        self._status_meta: dict[str, dict] = {}
        self._priorities: Counter[str] = Counter()
        self._resolutions: Counter[str] = Counter()
        self._link_types: Counter[str] = Counter()
        self._sprints: Counter[str] = Counter()
        self._sprint_meta: dict[str, dict] = {}
        self._versions: Counter[str] = Counter()
        self._components: Counter[str] = Counter()
        self._labels: Counter[str] = Counter()
        self._people: dict[str, PersonEntry] = {}
        # Resolved once from the catalog's stable type keys.
        self.sprint_field_ids = tuple(
            schemakeys.find_by_schema_key(self.catalog, schemakeys.JiraSchemaKey.SPRINT)
        )
        epic_ids = schemakeys.find_by_schema_key(
            self.catalog, schemakeys.JiraSchemaKey.EPIC_LINK
        ) or [
            fid
            for fid, meta in self.catalog.items()
            if (meta.get("name") or "").lower() == "epic link"
        ]
        self.epic_link_field_id = epic_ids[0] if epic_ids else ""

    # --- one issue ---

    def add(self, payload: dict) -> None:
        self.total += 1
        fields = payload.get("fields") or {}
        self._add_fields(fields)
        self._add_vocabularies(fields)
        self._add_people(fields, payload)

    def _add_fields(self, fields: dict) -> None:
        for fid, value in fields.items():
            self._seen_ids.add(fid)
            rendered = inference.render_value(value)
            if rendered is None:
                continue
            self._populated[fid] += 1
            self._array_seen[fid] = self._array_seen.get(fid, False) or isinstance(value, list)
            bucket = self._samples.setdefault(fid, [])
            if len(bucket) < inference.MAX_SAMPLES and rendered not in bucket:
                bucket.append(rendered)
            counter = self._distinct.setdefault(fid, Counter())
            for token in inference.scalar_values(value):
                counter[token] += 1

    def _add_vocabularies(self, fields: dict) -> None:
        if name := _named(fields.get("issuetype")):
            self._issue_types[name] += 1
        status = fields.get("status") or {}
        if name := _named(status):
            self._statuses[name] += 1
            # Jira's `statusCategory.key` is stable vocabulary (new/indeterminate/
            # done) — the suggestion uses it instead of matching English names.
            self._status_meta.setdefault(
                name,
                {"category_key": (status.get("statusCategory") or {}).get("key", "")},
            )
        if name := _named(fields.get("priority")):
            self._priorities[name] += 1
        if name := _named(fields.get("resolution")):
            self._resolutions[name] += 1
        for link in fields.get("issuelinks") or []:
            if name := ((link.get("type") or {}).get("name") or "").strip():
                self._link_types[name] += 1
        for version in fields.get("fixVersions") or []:
            if name := _named(version):
                self._versions[name] += 1
        for component in fields.get("components") or []:
            if name := _named(component):
                self._components[name] += 1
        for label in fields.get("labels") or []:
            if text := str(label).strip():
                self._labels[text] += 1
        # Sprints come from the field(s) Jira's own `gh-sprint` type key names —
        # never a hardcoded id, which is what made spec 90 parse arbitrary values
        # as sprint beans on any other instance.
        for sprint in issuemap.sprints(fields, self.sprint_field_ids):
            self._sprints[sprint.name] += 1
            self._sprint_meta.setdefault(
                sprint.name,
                {
                    "state": sprint.state or "",
                    "start_date": sprint.start_date or "",
                    "end_date": sprint.end_date or "",
                    "complete_date": sprint.complete_date or "",
                },
            )

    def _add_people(self, fields: dict, payload: dict) -> None:
        self._person(fields.get("assignee"), ROLE_ASSIGNEE)
        self._person(fields.get("reporter"), ROLE_REPORTER)
        self._person(fields.get("creator"), ROLE_CREATOR)
        for comment in (fields.get("comment") or {}).get("comments") or []:
            self._person(comment.get("author"), ROLE_COMMENT)
            self._person(comment.get("updateAuthor"), ROLE_COMMENT)
        for worklog in (fields.get("worklog") or {}).get("worklogs") or []:
            self._person(worklog.get("author"), ROLE_WORKLOG)
        for attachment in fields.get("attachment") or []:
            self._person(attachment.get("author"), ROLE_ATTACHMENT)
        for history in (payload.get("changelog") or {}).get("histories") or []:
            self._person(history.get("author"), ROLE_HISTORY)

    def _person(self, raw: dict | None, role: str) -> None:
        if not raw:
            return
        key = (raw.get("name") or raw.get("key") or raw.get("accountId") or "").strip()
        if not key:
            return
        entry = self._people.get(key)
        if entry is None:
            entry = PersonEntry(key=key)
            self._people[key] = entry
        entry.count += 1
        entry.roles.add(role)
        if not entry.display_name:
            entry.display_name = issuemap.person_name(raw)
        if not entry.email:
            # Only an address Jira actually exposed. No domain is synthesized
            # here — the Users step decides that, visibly.
            entry.email = issuemap.decode_email(
                raw.get("emailAddress") or raw.get("email")
            ) or ""

    # --- the result ---

    def profile(self) -> InboundProfile:
        return InboundProfile(
            total_issues=self.total,
            fields=self._field_profiles(),
            issue_types=_entries(self._issue_types),
            statuses=_entries(self._statuses, self._status_meta),
            priorities=_entries(self._priorities),
            resolutions=_entries(self._resolutions),
            link_types=_entries(self._link_types),
            sprints=_entries(self._sprints, self._sprint_meta),
            versions=_entries(self._versions),
            components=_entries(self._components),
            labels=_entries(self._labels),
            people=sorted(
                self._people.values(), key=lambda p: (-p.count, p.display_name.lower())
            ),
            sprint_field_ids=self.sprint_field_ids,
            epic_link_field_id=self.epic_link_field_id,
        )

    def _field_profiles(self) -> list[InferredField]:
        """Same judgement as `inference.infer_schema`, over the WHOLE snapshot
        rather than a 50-issue sample — which is what makes an `unused` verdict a
        fact instead of "not in the ones we looked at"."""
        results: list[InferredField] = []
        # Catalog fields the issues never mentioned are still offered — hidden in
        # the unused band, not dropped, so nothing is invisible.
        for fid in sorted(self._seen_ids | set(self.catalog)):
            meta = self.catalog.get(fid, {})
            counter = self._distinct.get(fid, Counter())
            inferred = inference.classify(
                meta.get("schema_type", ""),
                meta.get("schema_items", ""),
                self._array_seen.get(fid, False),
                counter,
            )
            name = meta.get("name", fid)
            is_builtin = fid in BUILTIN_JIRA_FIELDS and not meta.get("is_custom", False)
            option_set = (
                sorted(counter)
                if inferred in (InferredType.SELECT, InferredType.MULTI_SELECT)
                and 0 < len(counter) <= inference.SELECT_MAX_DISTINCT
                else None
            )
            tokens = sum(counter.values())
            dominant = (counter.most_common(1)[0][1] / tokens) if tokens else 0.0
            band, reason = inference.band_of(
                meta.get("schema_key", ""),
                is_builtin,
                self._populated.get(fid, 0),
                self.total,
                dominant,
            )
            results.append(
                InferredField(
                    jira_id=fid,
                    name=name,
                    inferred_type=inferred,
                    populated=self._populated.get(fid, 0),
                    sample_count=self.total,
                    is_builtin=is_builtin,
                    distinct_count=len(counter),
                    dominant_ratio=dominant,
                    schema_key=meta.get("schema_key", ""),
                    band=band,
                    band_reason=reason,
                    native_target=schemakeys.native_target(meta.get("schema_key", ""), name),
                    samples=self._samples.get(fid, []),
                    distinct_values=option_set,
                )
            )
        results.sort(
            key=lambda f: (
                inference.FIELD_BAND_ORDER[f.band],
                -f.populated,
                -f.distinct_count,
                f.name.lower(),
            )
        )
        return results


def _named(raw: Any) -> str:
    """A Jira `{name|value}` object's label, or "" — the shape every vocabulary
    entry arrives in."""
    if isinstance(raw, dict):
        return str(raw.get("name") or raw.get("value") or "").strip()
    return str(raw).strip() if raw else ""


def _entries(counts: Counter[str], meta: dict[str, dict] | None = None) -> list[VocabEntry]:
    """Counted values, most-used first — the order the mapping table renders in."""
    return [
        VocabEntry(value=value, count=count, meta=(meta or {}).get(value, {}))
        for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    ]


def merge_catalog(
    entries: list[VocabEntry], catalog: list[dict], key: str = "name"
) -> list[VocabEntry]:
    """Append the instance-wide values the snapshot never used, with count 0.

    They belong in the table — hidden and ignored, but present, so an admin who
    knows a status is coming can map it ahead of time. This is where "59 issue
    types, 6 of them used" becomes tractable rather than overwhelming.
    """
    by_value = {e.value: e for e in entries}
    extra: list[VocabEntry] = []
    for row in catalog or []:
        value = str(row.get(key) or "").strip()
        if not value:
            continue
        meta = _vocab_meta(row)
        if (seen := by_value.get(value)) is not None:
            # A USED value still needs the catalog's metadata — Jira's priority
            # `id` (the severity ladder) and a status's category live there, and
            # without them the suggestions fall back to guessing.
            seen.meta = {**meta, **seen.meta}
        else:
            extra.append(VocabEntry(value=value, count=0, meta=meta))
    return [*entries, *sorted(extra, key=lambda e: e.value.lower())]


def _vocab_meta(row: dict) -> dict:
    meta: dict[str, str] = {}
    if category := (row.get("statusCategory") or {}).get("key"):
        meta["category_key"] = category
    for field_name in ("inward", "outward", "id", "description"):
        if value := row.get(field_name):
            meta[field_name] = str(value)
    return meta
