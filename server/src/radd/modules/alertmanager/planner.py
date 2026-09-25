"""Pure Alertmanager webhook → planned actions (spec 47). No I/O: `existing`
carries the known fingerprints so the firing-new / firing-again / resolved
decision stays a pure function. Since RADD-1317 a plan carries the alert itself
— its facts are what the trigger events carry — and no comment text: what a
repeat or a resolution does to the issue is an automation's business."""

from dataclasses import dataclass, field
from typing import Any

from .types import AlertAction, AlertStatus, TITLE_MAX_CHARS

# Well-known Alertmanager payload fields.
_ALERTNAME_LABEL = "alertname"
_SUMMARY_ANNOTATION = "summary"


@dataclass(frozen=True)
class AlertPlan:
    action: AlertAction
    fingerprint: str
    alert: dict[str, Any] = field(default_factory=dict)
    firing_count: int = 0
    title: str = ""  # CREATE only
    description: str = ""  # CREATE only


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


def facts_of(plan: AlertPlan, receiver: str) -> dict[str, Any]:
    """What a trigger event carries about one alert."""
    alert = plan.alert
    labels = dict(alert.get("labels") or {})
    annotations = dict(alert.get("annotations") or {})
    return {
        "receiver": receiver,
        "fingerprint": plan.fingerprint,
        "status": str(alert.get("status") or ""),
        "alertname": str(labels.get(_ALERTNAME_LABEL, "")),
        "summary": str(annotations.get(_SUMMARY_ANNOTATION, "")),
        "labels": labels,
        "annotations": annotations,
        "generator_url": str(alert.get("generatorURL") or ""),
        "starts_at": str(alert.get("startsAt") or ""),
        "ends_at": str(alert.get("endsAt") or ""),
        "firing_count": plan.firing_count,
    }


def plan_alerts(payload: dict, existing: frozenset[str] = frozenset()) -> list[AlertPlan]:
    """One plan per alert with a usable fingerprint:

    - firing + unknown fingerprint → CREATE (title/description built here)
    - firing + known fingerprint → STILL_FIRING
    - resolved + known fingerprint → RESOLVED
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
                plans.append(AlertPlan(AlertAction.STILL_FIRING, fingerprint, alert, firing_count))
            else:
                known.add(fingerprint)  # a repeat in the same payload is a dup, not a 2nd issue
                plans.append(
                    AlertPlan(
                        AlertAction.CREATE, fingerprint, alert, firing_count,
                        title=_title(alert), description=_description(alert),
                    )
                )
        elif status == AlertStatus.RESOLVED and fingerprint in known:
            plans.append(AlertPlan(AlertAction.RESOLVED, fingerprint, alert, firing_count))
    return plans
