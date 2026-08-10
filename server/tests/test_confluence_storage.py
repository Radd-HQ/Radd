"""Confluence storage format → markdown (spec 117, RADD-1015).

Pure conversion, so these are ordinary unit tests with no database.

The first fixture is a REAL page body from a live Confluence Server/DC instance,
not a hand-written approximation — it is the one that settled what the converter
actually has to parse: a `<time>` element, a wrapped table with a `colgroup`, a
`jira` macro nested three levels inside a table cell, an `ac:task-list`, and an
`ac:placeholder` that is editor chrome rather than content.
"""

import json

from radd.modules.confluenceimport.client import _int, _page_of
from radd.modules.confluenceimport.storage import ConvertContext, convert, translate_jql
from radd.modules.confluenceimport.types import ProblemKind

# A maintenance-notes page, verbatim from the corpus.
REAL_PAGE = (
    '<h2>Date</h2><p><time datetime="2023-10-12">2023-10-12</time></p>'
    "<h2>Attendees</h2><ul><li><p>@Hrvoje Dakovic</p></li><li>@Ilknur Manav</li></ul>"
    "<p><br/></p><h2>Maintenance items</h2>"
    '<table class="wrapped"><colgroup><col style="width: 55.0px;"/><col/></colgroup>'
    "<tbody><tr><th>Time</th><th colspan=\"1\">Ticket</th></tr>"
    '<tr><td>8:00 a.m.</td><td colspan="1"><div class="content-wrapper"><p>'
    '<ac:structured-macro ac:macro-id="b140" ac:name="jira" ac:schema-version="1">'
    '<ac:parameter ac:name="server">JIRA</ac:parameter>'
    '<ac:parameter ac:name="key">SAT-1665</ac:parameter>'
    "</ac:structured-macro></p></div></td></tr></tbody></table>"
    "<h2>Action items</h2><ac:task-list>\n<ac:task>\n<ac:task-id>1</ac:task-id>\n"
    "<ac:task-status>incomplete</ac:task-status>\n"
    '<ac:task-body><ac:placeholder ac:type="mention">Type your task here.'
    "</ac:placeholder></ac:task-body>\n</ac:task>\n</ac:task-list>"
)


def _fences(markdown: str, name: str) -> list[dict]:
    """Every `radd:<name>` block's parsed params."""
    out = []
    for chunk in markdown.split(f"```radd:{name}\n")[1:]:
        out.append(json.loads(chunk.split("```")[0]))
    return out


# --- the real page ---


def test_real_page_keeps_its_structure():
    result = convert(REAL_PAGE)
    md = result.markdown

    assert "## Date" in md and "## Maintenance items" in md
    assert "2023-10-12" in md, "a <time> element is its date, not nothing"
    # The table survives with a header row and its separator.
    assert "| Time | Ticket |" in md
    assert "| --- | --- |" in md
    assert "8:00 a.m." in md
    # The task list is native markdown, not an extension.
    assert "- [ ] Type your task here." not in md, "the placeholder is editor chrome"
    assert "- [ ]" in md


def test_placeholder_is_dropped_but_the_task_survives():
    """`ac:placeholder` is the grey prompt text an empty editor shows. Importing it
    as content puts "Type your task here" on a hundred real pages."""
    result = convert(REAL_PAGE)
    assert "Type your task here" not in result.markdown


def test_jira_macro_inside_a_table_cell_is_found():
    """Three levels deep — td > div > p > macro. A converter that only looks at
    block level misses every one of these."""
    assert convert(REAL_PAGE).macros_seen.get("jira") == 1


# --- the Jira join ---


def test_jira_key_becomes_an_issue_mention_when_imported():
    """The join between the two halves of the migration: a key spec 100 imported
    renders as a live chip, and `pages/mentions.py` derives item_page_links from it
    with no extra work."""
    ctx = ConvertContext(item_exists=lambda key: key == "SAT-1665")
    md = convert(REAL_PAGE, ctx).markdown
    assert "#[SAT-1665](SAT-1665)" in md


def test_unimported_jira_key_keeps_an_honest_external_link():
    ctx = ConvertContext(item_exists=lambda key: False, jira_base_url="https://jira.example.com")
    result = convert(REAL_PAGE, ctx)
    assert "[SAT-1665](https://jira.example.com/browse/SAT-1665)" in result.markdown
    assert "SAT-1665" in result.jira_keys


# --- macros ---


def test_note_macros_become_one_callout_with_a_kind():
    body = (
        '<ac:structured-macro ac:name="warning">'
        '<ac:parameter ac:name="title">Careful</ac:parameter>'
        "<ac:rich-text-body><p>Mind the gap</p></ac:rich-text-body>"
        "</ac:structured-macro>"
    )
    params = _fences(convert(body).markdown, "callout")
    assert params == [{"kind": "warning", "title": "Careful", "text": "Mind the gap"}]


def test_code_macro_becomes_a_plain_fence_with_its_language():
    body = (
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">python</ac:parameter>'
        "<ac:plain-text-body><![CDATA[print(1)]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    md = convert(body).markdown
    assert "```python\nprint(1)\n```" in md, "CDATA must survive — it is the code"


def test_a_code_fence_carries_the_canonical_language():
    """Confluence writes `py`; a markdown fence should say `python`.

    Radd's own picker resolves both now, but the body is portable markdown that
    GitHub and every other renderer also reads — and there, `py` highlights
    nothing. The token that travels should be the one everybody understands.
    """
    body = (
        '<ac:structured-macro ac:name="code">'
        '<ac:parameter ac:name="language">py</ac:parameter>'
        "<ac:plain-text-body><![CDATA[x = 1]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )
    assert "```python\nx = 1\n```" in convert(body).markdown


def test_a_plain_text_code_macro_gets_no_language():
    for token in ("none", "text", "plain"):
        body = (
            '<ac:structured-macro ac:name="code">'
            f'<ac:parameter ac:name="language">{token}</ac:parameter>'
            "<ac:plain-text-body><![CDATA[hello]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        assert "```\nhello\n```" in convert(body).markdown, token


def test_toc_maps_onto_the_extension_that_already_existed():
    body = (
        '<ac:structured-macro ac:name="toc">'
        '<ac:parameter ac:name="maxLevel">2</ac:parameter></ac:structured-macro>'
    )
    assert _fences(convert(body).markdown, "toc") == [{"depth": 2}]


def test_an_unknown_macro_is_carded_not_stripped():
    """A page whose content WAS the macro must not import empty, and the block must
    keep enough to upgrade in place once a renderer exists."""
    body = (
        '<ac:structured-macro ac:name="drawio">'
        '<ac:parameter ac:name="diagramName">network</ac:parameter>'
        "</ac:structured-macro>"
    )
    result = convert(body)
    assert _fences(result.markdown, "unsupported-macro") == [
        {"macro": "drawio", "params": {"diagramName": "network"}}
    ]
    problem = result.problems[0]
    assert problem.kind is ProblemKind.MACRO
    # Addressed back to the control that fixes it — "Fix in Macros → drawio".
    assert problem.mapping_key == "drawio"
    assert problem.section is not None and problem.section.value == "macros"


def test_anchor_macro_is_stripped_because_headings_carry_their_own():
    body = '<p>a</p><ac:structured-macro ac:name="anchor"/><p>b</p>'
    assert "unsupported-macro" not in convert(body).markdown


# --- references ---


def test_user_mention_resolves_to_the_native_token():
    body = '<ac:link><ri:user ri:username="jsmith"/></ac:link>'
    ctx = ConvertContext(user_ref=lambda u: ("Jane Smith", "uuid-1"))
    assert "@[Jane Smith](uuid-1)" in convert(body, ctx).markdown


def test_unresolved_mention_degrades_and_is_reported():
    body = '<ac:link><ri:user ri:username="ghost"/></ac:link>'
    result = convert(body)
    assert "@ghost" in result.markdown
    assert result.problems[0].kind is ProblemKind.USER


def test_image_points_at_the_imported_attachment_and_carries_its_width():
    body = '<ac:image ac:width="600"><ri:attachment ri:filename="diagram.png"/></ac:image>'
    ctx = ConvertContext(attachment_url=lambda n: f"/api/v1/attachments/{n}")
    result = convert(body, ctx)
    # RADD-751: ?w= makes the endpoint serve fewer bytes than the original.
    assert "![diagram.png](/api/v1/attachments/diagram.png?w=600)" in result.markdown
    assert "diagram.png" in result.attachment_refs


def test_page_link_records_a_reference_when_the_target_is_not_imported():
    body = (
        '<ac:link><ri:page ri:content-title="Other Page" ri:space-key="PIP"/>'
        "<ac:link-body>see this</ac:link-body></ac:link>"
    )
    result = convert(body, ConvertContext(confluence_base_url="https://wiki.example.com"))
    assert "Other Page" in result.page_refs
    assert "see this" in result.markdown
    assert result.problems[0].kind is ProblemKind.LINK


# --- what a real page taught us (RADD-1015) ---
#
# Running the converter against a live macro-rich page found three gaps that the
# hand-written fixture above never would have: Confluence writes images BOTH ways,
# `status` is inline and sits inside table cells, and page layouts wrap everything.


def test_a_plain_img_resolves_like_an_ac_image():
    """The COMMON form on a real corpus. The editor's insert writes
    <ac:image><ri:attachment>, but a paste (and every older editor) writes a bare
    <img> with an absolute /download/attachments/ URL. Handling only the first
    silently drops most images on most pages."""
    body = (
        '<p><img alt="Screenshot.png" width="400" '
        'src="https://wiki.example.com/download/attachments/248676810/'
        'Screenshot%202025-02-07%20at%2015.37.38.png?version=1&amp;api=v2"/></p>'
    )
    ctx = ConvertContext(attachment_url=lambda n: f"/api/v1/attachments/{n}")
    result = convert(body, ctx)
    # URL-decoded, because that is the filename the attachment was stored under.
    assert "Screenshot 2025-02-07 at 15.37.38.png" in result.attachment_refs
    assert "?w=400" in result.markdown


def test_a_filename_with_spaces_still_makes_a_link():
    """Confluence filenames routinely contain spaces, and `![a](b c.png)` is not
    a link — the renderer prints it literally. Caught by importing a real page."""
    body = (
        '<ac:image><ri:attachment ri:filename="Screen shot 1.png"/></ac:image>'
    )
    assert "![Screen shot 1.png](<Screen shot 1.png>)" in convert(body).markdown


def test_an_external_img_keeps_its_url():
    body = '<p><img src="https://example.com/logo.png" alt="logo"/></p>'
    assert "![logo](https://example.com/logo.png)" in convert(body).markdown


def test_status_is_inline_and_does_not_break_its_table():
    """A `radd:*` fence is BLOCK-level. Emitting one inside a table cell — which is
    where status lozenges live — ends the table at that row."""
    body = (
        "<table><tbody><tr><th>Status</th><td><p>"
        '<ac:structured-macro ac:name="status">'
        '<ac:parameter ac:name="colour">Yellow</ac:parameter>'
        '<ac:parameter ac:name="title">WIP</ac:parameter>'
        "</ac:structured-macro></p></td></tr></tbody></table>"
    )
    md = convert(body).markdown
    assert "```" not in md, "a fence inside a cell would terminate the table"
    assert "| Status | `WIP` |" in md


def test_page_layouts_flow_their_cells_in_document_order():
    """`ac:layout` is chrome. Markdown has no columns, so the content flows."""
    body = (
        "<ac:layout><ac:layout-section><ac:layout-cell><h2>Left</h2></ac:layout-cell>"
        "<ac:layout-cell><p>Right</p></ac:layout-cell>"
        "</ac:layout-section></ac:layout>"
    )
    md = convert(body).markdown
    assert "## Left" in md and "Right" in md


def test_details_macro_yields_its_body_rather_than_a_card():
    """A container macro's content IS the page. Carding it would bury a whole
    table inside a JSON blob."""
    body = (
        '<ac:structured-macro ac:name="details"><ac:rich-text-body>'
        "<p>real content</p></ac:rich-text-body></ac:structured-macro>"
    )
    md = convert(body).markdown
    assert "real content" in md and "unsupported-macro" not in md


# --- what the live instance taught us ---


def test_position_none_is_a_string_and_must_not_crash():
    """`extensions.position` is an integer for a page whose order was set by hand
    and the literal STRING "none" for one that inherits it.

    Measured on the real PIP space: 4203 of 6099 pages carry "none" — 69%, not an
    edge case. A bare int() raised on the first one, which aborted the whole
    listing, which is what turned it into "download failed" for the entire space
    and an empty tree browser with no error at all.
    """
    page = _page_of(
        {"id": "3801098", "title": "Install Photoshop extension",
         "extensions": {"position": "none"}, "version": {"number": 5}},
        "PIP",
    )
    assert page.position == 0
    assert page.version == 5
    assert page.title == "Install Photoshop extension"


def test_every_remote_number_falls_back_rather_than_raising():
    """Nothing in another system's JSON is guaranteed to be the type its field
    name suggests."""
    assert _int("none") == 0
    assert _int(None, 1) == 1
    assert _int("", 7) == 7
    assert _int({}, 3) == 3
    assert _int("12") == 12
    assert _int(4) == 4


def test_a_listing_drops_a_repeated_page(monkeypatch):
    """Offset pagination over a LIVE collection repeats rows.

    Walking a real 6107-page space returned one page in two different windows,
    and the snapshot's primary key then killed the download 375 bodies in. The
    listing owns this: a caller asking for "every page in this space" should
    never have to know it might be told one of them twice.
    """
    from radd.modules.confluenceimport.client import ConfluenceClient
    from radd.modules.confluenceimport.types import ConfluenceAuthMode, ConfluenceCreds

    rows = [
        {"id": "1", "title": "One", "extensions": {"position": 0}},
        {"id": "2", "title": "Two", "extensions": {"position": "none"}},
        {"id": "1", "title": "One again", "extensions": {"position": 0}},
    ]
    client = ConfluenceClient(
        ConfluenceCreds(base_url="https://x", auth_mode=ConfluenceAuthMode.PAT, credential="t")
    )
    monkeypatch.setattr(client, "_paged", lambda *a, **k: iter(rows))

    pages = client._pages("/whatever", "PIP")
    assert [p.id for p in pages] == ["1", "2"]


def test_a_page_row_with_no_version_block_still_parses():
    page = _page_of({"id": "1", "title": "Bare"}, "PIP")
    assert (page.position, page.version, page.space_key) == (0, 1, "PIP")


def test_a_mention_by_userkey_reads_as_a_person():
    """Server/DC writes mentions as an opaque `ri:userkey`, not a username.

    Unresolved, that put raw 32-character hex on the page and produced reports
    reading "mention of unknown user 8a05808b692118d5016b76858a5f1e1a" — which
    nobody can map by hand. The key is resolved to a person at download time; the
    converter asks the resolver and shows a NAME either way.
    """
    body = '<p>ask <ac:link><ri:user ri:userkey="8a05808b692118d5016b76858a5f1e1a"/></ac:link></p>'
    directory = {"8a05808b692118d5016b76858a5f1e1a": ("Hussein Jarrar", "uuid-9")}
    ctx = ConvertContext(user_ref=lambda token: directory.get(token, (token, "")))
    assert "@[Hussein Jarrar](uuid-9)" in convert(body, ctx).markdown


def test_an_unmatched_userkey_still_shows_a_name_not_hex():
    body = '<ac:link><ri:user ri:userkey="8a05808b692118d5016b76858a5f1e1a"/></ac:link>'
    ctx = ConvertContext(user_ref=lambda token: ("Hussein Jarrar", ""))
    md = convert(body, ctx).markdown
    assert "@Hussein Jarrar" in md
    assert "8a05808b" not in md


# --- multimedia ---


def test_multimedia_becomes_a_player_not_a_card():
    """The macro IS the content of the pages that use it — a meeting recording
    carded as "unsupported" is the page missing its point."""
    body = (
        '<ac:structured-macro ac:name="multimedia">'
        '<ac:parameter ac:name="name">2021-08-26 standup.mp4</ac:parameter>'
        "</ac:structured-macro>"
    )
    ctx = ConvertContext(attachment_url=lambda n: f"/api/v1/attachments/{n}/download")
    result = convert(body, ctx)
    block = _fences(result.markdown, "media")[0]
    assert block["kind"] == "video"
    assert block["src"].endswith("/download")
    assert "2021-08-26 standup.mp4" in result.attachment_refs


def test_an_audio_attachment_gets_the_audio_player():
    body = (
        '<ac:structured-macro ac:name="multimedia">'
        '<ac:parameter ac:name="name">interview.mp3</ac:parameter></ac:structured-macro>'
    )
    assert _fences(convert(body).markdown, "media")[0]["kind"] == "audio"


def test_multimedia_naming_its_file_in_the_body_still_resolves():
    body = (
        '<ac:structured-macro ac:name="multimedia"><ac:rich-text-body>'
        '<ri:attachment ri:filename="demo.mp4"/></ac:rich-text-body></ac:structured-macro>'
    )
    assert "demo.mp4" in convert(body).attachment_refs


def test_a_media_macro_naming_nothing_degrades_to_a_card():
    """No file and no URL is not a player — it is a macro we cannot honour, and
    the honest fallback still applies."""
    body = '<ac:structured-macro ac:name="multimedia"/>'
    assert "unsupported-macro" in convert(body).markdown


# --- robustness ---


def test_malformed_markup_degrades_instead_of_raising():
    """A decade-old corpus is full of pasted HTML. An unclosed tag must not take
    the rest of the page with it."""
    body = "<p>before<div><span>text</p></div><p>after</p>"
    md = convert(body).markdown
    assert "before" in md and "text" in md and "after" in md


def test_empty_body_is_empty_not_an_error():
    assert convert("").markdown == ""
    assert convert("   ").markdown == ""


def test_unknown_element_keeps_its_text():
    assert "kept" in convert("<weird-thing>kept</weird-thing>").markdown


# --- JQL translation ---


def test_simple_jql_translates_to_slq():
    slq, ok = translate_jql('project = PIP AND status = "In Progress"')
    assert ok and "project = PIP" in slq and "AND" in slq


def test_currentuser_becomes_the_slq_sentinel():
    slq, ok = translate_jql("assignee = currentUser()")
    assert ok and slq == "assignee = me"


def test_an_untranslatable_query_says_so_rather_than_guessing():
    """A silently mistranslated query that returns plausible rows is worse than one
    that admits it needs a person."""
    for jql in (
        "cf[10101] ~ 'x'",
        "project = PIP AND (status = Open OR status = Closed)",
        "worklogAuthor in membersOf('dev')",
        "",
    ):
        _, ok = translate_jql(jql)
        assert not ok, f"{jql!r} should not claim a translation"


def test_jiraissues_keeps_the_original_jql_when_translation_fails():
    body = (
        '<ac:structured-macro ac:name="jiraissues">'
        "<ac:parameter ac:name=\"jqlQuery\">cf[10101] ~ 'x'</ac:parameter>"
        "</ac:structured-macro>"
    )
    result = convert(body)
    block = _fences(result.markdown, "items")[0]
    assert block["unsupported"] is True
    assert block["source_jql"] == "cf[10101] ~ 'x'"
    assert result.problems[0].kind is ProblemKind.MACRO
