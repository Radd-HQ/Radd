"""Pure Alertmanager webhook → planned actions (spec 47) — tested in
tests/test_connectors.py. No I/O: `existing` carries the known fingerprints
(the alert_items dedup table) so the firing-new / firing-dup / resolved
decision stays a pure function; lookups and writes happen in service.py."""

from dataclasses import dataclass

from .types import AlertAction, AlertStatus, RESOLVED_COMMENT, STILL_FIRING_TEMPLATE, TITLE_MAX_CHARS

# Well-known Alertmanager payload fields.
_ALERTNAME_LABEL = "alertname"
_SUMMARY_ANNOTATION = "summary"


@dataclass(frozen=True)
class AlertPlan:
    action: AlertAction
    fingerprint: str
    title: str = ""  # CREATE only
    description: str = ""  # CREATE only
    comment: str = ""  # STILL_FIRING / RESOLVED only


def _title(alert: dict) -> str:
    alertname = (alert.get("labels") or {}).get(_ALERTNAME_LABEL, "")
    summary = (alert.get("annotations") or {}).get(_SUMMARY_ANNOTATION, "")
    title = ": ".join(part for part in (alertname, summary) if part) or "alert"
    return title[:TITLE_MAX_CHARS]


def _description(alert: dict) -> str:
    """Labels + annotations as a markdown table, plus the generator link."""
    lines = ["| Key | Value |", "| --- | --- |"]
    for section, mapping in (("label", alert.get("labels")), ("annotation", alert.get("annotations"))):
        for key, value in sorted((mapping or {}).items()):
            lines.append(f"| {key} ({section}) | {value} |")
    generator_url = alert.get("generatorURL", "")
    if generator_url:
        lines += ["", f"[Source]({generator_url})"]
    return "\n".join(lines)


def plan_alerts(payload: dict, existing: frozenset[str] = frozenset()) -> list[AlertPlan]:
    """One plan per alert with a usable fingerprint:

    - firing + unknown fingerprint → CREATE (title/description built here)
    - firing + known fingerprint → STILL_FIRING comment
    - resolved + known fingerprint → RESOLVED comment
    - resolved + unknown fingerprint, or no fingerprint → skipped
    """
    alerts = payload.get("alerts") or []
    firing_count = sum(1 for a in alerts if a.get("status") == AlertStatus.FIRING)
    known = set(existing)
    plans: list[AlertPlan] = []
    for alert in alerts:
        fingerprint = alert.get("fingerprint", "")
        if not fingerprint:
            continue
        status = alert.get("status", "")
        if status == AlertStatus.FIRING:
            if fingerprint in known:
                plans.append(
                    AlertPlan(
                        action=AlertAction.STILL_FIRING,
                        fingerprint=fingerprint,
                        comment=STILL_FIRING_TEMPLATE.format(count=firing_count),
                    )
                )
            else:
                known.add(fingerprint)  # a repeat in the same payload is a dup, not a 2nd item
                plans.append(
                    AlertPlan(
                        action=AlertAction.CREATE,
                        fingerprint=fingerprint,
                        title=_title(alert),
                        description=_description(alert),
                    )
                )
        elif status == AlertStatus.RESOLVED and fingerprint in known:
            plans.append(
                AlertPlan(
                    action=AlertAction.RESOLVED,
                    fingerprint=fingerprint,
                    comment=RESOLVED_COMMENT,
                )
            )
    return plans
