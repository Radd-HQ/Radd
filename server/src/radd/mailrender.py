"""Every email Radd sends, composed in ONE place (RADD-967).

Three subsystems had each grown their own idea of what an email is. The outbound
comment reply shipped the raw comment body — no author, no issue, no link, so a
watcher received a paragraph with nothing saying what it was about. The
notification digest had explicit lines for four of the nine notification types
(the other five all read "commented") and pasted its URLs together inline. The
ack was a template constant. All three were plain text only. And a fourth,
`googlechat`, kept a private copy of the issue-URL string.

This module owns composition and nothing else. It has no session, imports no
`radd.modules.*`, and reads no settings — the base URL arrives as an argument.
A rendering test therefore needs neither a database nor an app config, and the
caller stays the one that decides what this instance is called.

**Both parts, always.** Every renderer returns text AND html together. A
multipart message whose halves are built in different places is a message whose
halves drift; here they cannot, because one function writes both.

**Nothing survives as markup.** Everything interpolated goes through
`html.escape`, and a comment body is inserted as escaped text with its line
breaks preserved. A comment IS markdown, and rendering it would mean running a
markdown renderer (a new dependency) over user text whose output lands in
someone's mail client. That is `mailintake/html_body.py`'s decision pointed the
other way: markup is stripped on the way in, and never produced on the way out.

**Inline styles, table layout, no assets.** Gmail drops `<style>` blocks,
Outlook lays out with tables, and a remote asset is a tracking-pixel prompt in
the recipient's client. So the chrome is deliberately small.
"""

from __future__ import annotations

import html as html_escaping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

# --- links: the ONE place a Radd URL is spelled ---

ISSUE_PATH = "/issues"
PAGE_PATH = "/pages"
INBOX_PATH = "/inbox"


def site(base_url: str) -> str:
    """The instance root with no trailing slash. A configured
    `https://radd.example.com/` used to produce `…com//issues/KEY`, which most
    servers redirect and some proxies 404."""
    return (base_url or "").rstrip("/")


def issue_url(base_url: str, key: str) -> str:
    return f"{site(base_url)}{ISSUE_PATH}/{key}"


def page_url(base_url: str, space_slug: str, page_slug: str) -> str:
    return f"{site(base_url)}{PAGE_PATH}/{space_slug}/{page_slug}"


def inbox_url(base_url: str) -> str:
    return f"{site(base_url)}{INBOX_PATH}"


# --- the palette (mail clients have no tokens; these are the tokens) ---

FONT_STACK = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
PAGE_BG = "#f4f5f7"
CARD_BG = "#ffffff"
BORDER = "#e3e5e8"
#: 15:1 on the card — body text.
TEXT = "#1f2329"
#: 4.9:1 on the card — the smallest type here still clears 4.5:1.
MUTED = "#5f6673"
#: 6.3:1 as text on the card, and white on it as a fill clears 4.5:1 too.
LINK = "#3b5bdb"


class RenderedMail(NamedTuple):
    """The two halves of one message. Unpacks as `text, html = …`."""

    text: str
    html: str


@dataclass(frozen=True)
class ItemMail:
    """The issue a message is about, plus where this instance lives."""

    key: str
    title: str
    base_url: str

    @property
    def url(self) -> str:
        return issue_url(self.base_url, self.key)

    @property
    def label(self) -> str:
        return f"[{self.key}] {self.title}".strip()


@dataclass(frozen=True)
class DigestEntry:
    """One notification as a digest line.

    The headline is already a sentence when it gets here: what a `page_updated`
    or an `approval` reads like is knowledge the `notify` module owns (it owns
    the enum), and teaching this module those types would put the vocabulary
    in two places.
    """

    headline: str
    subject: str = ""
    excerpt: str = ""
    url: str = ""


# --- html primitives ---


def _esc(value: str) -> str:
    return html_escaping.escape(value or "", quote=True)


def _lines(value: str) -> str:
    """User text as html: escaped, line breaks kept. `<br>` rather than
    `white-space:pre-wrap` because Outlook's Word engine honours the tag
    everywhere and the property nowhere."""
    return _esc(value).replace("\n", "<br>")


def _anchor(url: str, label: str, *, color: str = LINK) -> str:
    return f'<a href="{_esc(url)}" style="color:{color};text-decoration:underline;">{_esc(label)}</a>'


def _button(url: str, label: str) -> str:
    return (
        f'<a href="{_esc(url)}" style="display:inline-block;background:{LINK};color:#ffffff;'
        f'font-size:14px;font-weight:600;text-decoration:none;padding:9px 16px;'
        f'border-radius:6px;">{_esc(label)}</a>'
    )


def _document(content: str, *, footer: str = "") -> str:
    """One card on a page ground, with the footer OUTSIDE the card — the
    convention every mail client's users already read as "why am I getting
    this", rather than as part of the message."""
    footer_html = (
        f'<div style="max-width:600px;margin:12px auto 0;font-family:{FONT_STACK};'
        f'font-size:12px;line-height:1.5;color:{MUTED};text-align:left;">{footer}</div>'
        if footer
        else ""
    )
    return (
        f'<html><body style="margin:0;padding:0;background:{PAGE_BG};">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        f' style="background:{PAGE_BG};padding:24px 12px;"><tr><td align="center">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"'
        f' style="max-width:600px;background:{CARD_BG};border:1px solid {BORDER};'
        f'border-radius:8px;"><tr><td style="padding:20px 24px;font-family:{FONT_STACK};'
        f'font-size:14px;line-height:1.5;color:{TEXT};">{content}</td></tr></table>'
        f"{footer_html}</td></tr></table></body></html>"
    )


def _header(item: ItemMail) -> str:
    return (
        f'<div style="font-size:12px;color:{MUTED};padding-bottom:10px;'
        f'border-bottom:1px solid {BORDER};margin-bottom:16px;">'
        f"{_anchor(item.url, item.label)}</div>"
    )


def _quoted(body: str) -> str:
    return (
        f'<div style="border-left:3px solid {BORDER};padding:2px 0 2px 12px;'
        f'margin:0 0 20px;">{_lines(body)}</div>'
    )


# --- the messages ---


def comment_reply(item: ItemMail, *, author: str, body: str, reason: str) -> RenderedMail:
    """A public comment, mailed to someone on the issue.

    `reason` is the recipient's own — a watcher and an external requester are on
    the thread for different reasons, and one wording cannot honestly say both.
    """
    headline = f"{author} commented on {item.label}"
    text = "\n".join(
        [
            headline,
            "",
            body.strip(),
            "",
            "--",
            f"View the issue: {item.url}",
            reason,
        ]
    )
    content = (
        _header(item)
        + f'<div style="margin-bottom:14px;"><strong>{_esc(author)}</strong> commented</div>'
        + _quoted(body)
        + _button(item.url, "View issue")
    )
    return RenderedMail(text=text, html=_document(content, footer=_esc(reason)))


#: The ack's prose. It stays a constant because the bracketed key is LOAD-BEARING
#: — `parsing.extract_reply_key` threads the requester's replies on it — so the
#: sentence that asks them to keep it cannot be casually reworded.
ACK_BODY = (
    "Your request has been received and is being tracked as {key}.\n"
    "\n"
    "We'll follow up by email. You can reply to this message to add details — "
    "replies are attached to the ticket automatically (keep [{key}] in the subject)."
)

#: The receipt's link affordance, one label for both parts. Deliberately SECOND
#: to `ACK_BODY` in both renderings — see `acknowledgement`.
ACK_LINK_LABEL = "View the ticket"


def acknowledgement(item: ItemMail, *, reason: str = "") -> RenderedMail:
    """The receipt an external requester gets when their mail opens a ticket.

    **It carries the issue URL in both parts (RADD-977).** RADD-967 deliberately
    left it out — "the requester has no account, so the link is a login page" —
    and that reasoning is now stale twice over: intake PROVISIONS an account for
    an unknown sender (RADD-828), and on an instance with SSO the sender is very
    often a colleague who is already signed in. A receipt with no way to look at
    the thing it acknowledges is a dead end for both of them, and a login page is
    a recoverable one.

    Reply-by-email stays the PRIMARY wording: it is the interface that works for
    every requester, signed in or not, so the prose comes first and the link
    follows it in both parts. The `[{key}]` subject mechanics are untouched.
    """
    body = ACK_BODY.format(key=item.key)
    text = f"{item.label}\n\n{body}\n\n{ACK_LINK_LABEL}: {item.url}\n"
    content = (
        f'<div style="font-size:12px;color:{MUTED};padding-bottom:10px;'
        f'border-bottom:1px solid {BORDER};margin-bottom:16px;">{_esc(item.label)}</div>'
        f"<div>{_lines(body)}</div>"
        f'<div style="margin-top:18px;">{_button(item.url, ACK_LINK_LABEL)}</div>'
    )
    return RenderedMail(text=text, html=_document(content, footer=_esc(reason)))


def digest_line(entry: DigestEntry, *, divider: bool = True) -> RenderedMail:
    """One notification, both halves. Public because the digest's shape is what
    a test pins — every notification type has to produce a distinct line.

    `divider` is off for the last line: a rule under the final row reads as a
    section that lost its content, not as a separator.
    """
    head = f"{entry.subject} — {entry.headline}" if entry.subject else entry.headline
    lines = [f"• {head}"]
    if entry.excerpt:
        lines.append(f'  "{entry.excerpt}"')
    if entry.url:
        lines.append(f"  {entry.url}")
    subject_html = (
        _anchor(entry.url, entry.subject) if entry.url and entry.subject else _esc(entry.subject)
    )
    parts = [
        f'<div style="font-size:14px;color:{TEXT};">'
        + (f"{subject_html} — " if entry.subject else "")
        + f"{_esc(entry.headline)}</div>"
    ]
    if entry.excerpt:
        parts.append(
            f'<div style="margin-top:4px;font-size:13px;color:{MUTED};font-style:italic;">'
            f"“{_esc(entry.excerpt)}”</div>"
        )
    if entry.url and not entry.subject:
        parts.append(f'<div style="margin-top:4px;font-size:12px;">{_anchor(entry.url, entry.url)}</div>')
    rule = f"border-bottom:1px solid {BORDER};" if divider else ""
    return RenderedMail(
        text="\n".join(lines),
        html=f'<div style="padding:12px 0;{rule}">' + "".join(parts) + "</div>",
    )


def notice(entry: DigestEntry, *, reason: str) -> RenderedMail:
    """ONE notification as its own email — the per-event message, as opposed to
    the batched `digest` (RADD-968).

    Same vocabulary, none of the batching chrome: the footer is the recipient's
    own reason, because "you have email digests on" is not why this arrived.
    A comment has its own renderer (`comment_reply`) that quotes the full body;
    this is what every other type gets.
    """
    head = f"{entry.subject} — {entry.headline}" if entry.subject else entry.headline
    body = [head, ""]
    if entry.excerpt:
        body.append(f'"{entry.excerpt}"')
    if entry.url:
        body.append(f"View the issue: {entry.url}")
    body.append(reason)
    text = "\n".join(body)
    content = digest_line(entry, divider=False).html
    if entry.url:
        content += _button(entry.url, "View issue")
    return RenderedMail(text=text, html=_document(content, footer=_esc(reason)))


def digest(entries: Sequence[DigestEntry], *, inbox: str) -> RenderedMail:
    """The batched notification email. `inbox` is the recipient's inbox URL —
    the one link that is always right when a line's own is missing."""
    last = len(entries) - 1
    rendered = [digest_line(entry, divider=index != last) for index, entry in enumerate(entries)]
    text = "\n\n".join(line.text for line in rendered)
    text += f"\n\n—\nYour Radd inbox: {inbox}"
    content = "".join(line.html for line in rendered)
    footer = f"You are receiving this because you have email digests on. {_anchor(inbox, 'Your Radd inbox')}"
    return RenderedMail(text=text, html=_document(content, footer=footer))
