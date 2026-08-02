"""Jira-markup → Markdown converter invariants (importer + back-fill + the frontend
twin's reference behavior — `web/src/lib/jira-markup.ts` mirrors these rules 1:1).

Pure tests. The rules interact (rule order, the code-block stash, the ambiguity
gate), so every construct and every known false-positive hazard is pinned here."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from jira_markup import jira_to_markdown, replace_attachment_embeds  # noqa: E402


def test_links_mentions_mono_headings():
    assert jira_to_markdown("[docs|https://x.io]") == "[docs](https://x.io)"
    assert jira_to_markdown("[https://x.io]") == "<https://x.io>"
    assert jira_to_markdown("[~jane.doe]") == "@jane.doe"
    assert jira_to_markdown("{{ls -la}}") == "`ls -la`"
    assert jira_to_markdown("h2. Title") == "## Title"


def test_code_block_protects_contents():
    out = jira_to_markdown("{code:python}x = [~a] * 2{code}")
    assert out == "\n```python\nx = [~a] * 2\n```\n"


def test_code_param_soup_yields_clean_language():
    out = jira_to_markdown("{code:title=Foo.java|language=java}int x;{code}")
    assert out.startswith("\n```java\n")
    out = jira_to_markdown("{code:title=Foo.java}int x;{code}")
    assert out.startswith("\n```\n")


def test_noformat_accepts_params():
    assert jira_to_markdown("{noformat:nopanel=true}raw{noformat}") == "\n```\nraw\n```\n"


def test_bold_and_strike():
    assert jira_to_markdown("this is *important* now") == "this is **important** now"
    assert jira_to_markdown("was -removed- today") == "was ~~removed~~ today"


def test_bold_leaves_lists_and_native_strong_alone():
    assert jira_to_markdown("* item one\n* item two") == "* item one\n* item two"
    assert jira_to_markdown("**already strong**") == "**already strong**"
    # a list item whose text carries bold
    assert jira_to_markdown("* fix *now*") == "* fix **now**"


def test_strike_skips_ranges_flags_and_rules():
    assert jira_to_markdown("range -5-10 stays") == "range -5-10 stays"
    assert jira_to_markdown("use --force flag") == "use --force flag"
    assert jira_to_markdown("---") == "---"


def test_ordered_and_nested_lists():
    assert jira_to_markdown("# first\n# second") == "1. first\n1. second"
    assert jira_to_markdown("# top\n## nested") == "1. top\n    1. nested"
    assert jira_to_markdown("* top\n** nested") == "* top\n    - nested"
    assert jira_to_markdown("#* mixed") == "    - mixed"


def test_list_rule_runs_before_heading_rule():
    # `h1.` becomes `# Title` — the list pass must never re-convert it to `1. Title`.
    assert jira_to_markdown("h1. Title") == "# Title"


def test_tables_become_gfm():
    out = jira_to_markdown("||a||b||\n|1|2|")
    assert out == "| a | b |\n| --- | --- |\n| 1 | 2 |"


def test_headerless_table_promotes_first_row():
    out = jira_to_markdown("|1|2|\n|3|4|", assume_jira=True)
    assert out == "| 1 | 2 |\n| --- | --- |\n| 3 | 4 |"


def test_table_after_paragraph_gets_blank_line():
    out = jira_to_markdown("Results:\n||a||b||")
    assert out == "Results:\n\n| a | b |\n| --- | --- |"


def test_link_pipes_resolved_before_table_split():
    out = jira_to_markdown("||col||\n|[docs|https://x.io]|")
    assert "| [docs](https://x.io) |" in out


def test_panel_color_anchor_toc():
    assert jira_to_markdown("{panel:title=Note}body{panel}") == "\n> **Note**\n>\n> body\n"
    assert jira_to_markdown("{panel}body{panel}") == "\n> body\n"
    assert jira_to_markdown("{color:red}alert{color}") == "alert"
    assert jira_to_markdown("see {anchor:here} this") == "see  this"
    assert jira_to_markdown("{toc:maxLevel=2}\nintro") == "intro"


def test_image_embeds():
    assert jira_to_markdown("!shot.png|thumbnail!") == "*(image: shot.png)*"
    assert jira_to_markdown("!https://x.io/a/img!") == "![](https://x.io/a/img)"
    # plain excited prose is not an embed
    assert jira_to_markdown("wow!really!", assume_jira=True) == "wow!really!"


def test_emoticons():
    assert jira_to_markdown("done (/) and (x) blocked") == "done ✅ and ❌ blocked"
    assert jira_to_markdown("f(x) is math", assume_jira=True) == "f(x) is math"


def test_gate_passes_native_markdown_untouched():
    native = "# Heading\n\n*emphasis* and **strong**\n\n- item\n\n| a |\n| --- |"
    assert jira_to_markdown(native, assume_jira=False) == native


def test_gate_opens_on_any_unambiguous_construct():
    # one Jira marker → the whole text converts, ambiguous rules included
    out = jira_to_markdown("h1. Title\n*bold* # not a heading", assume_jira=False)
    assert out == "# Title\n**bold** # not a heading"
    out = jira_to_markdown("||h||\n# item", assume_jira=False)
    assert out == "| h |\n| --- |\n1. item"


def test_empty_and_none():
    assert jira_to_markdown(None) == ""
    assert jira_to_markdown("") == ""


def test_attachment_embeds_rewrite_to_uploaded_urls():
    urls = {"shot.png": "/attachments/abc"}
    raw = "see !shot.png|thumbnail! and !missing.png!"
    rewritten = replace_attachment_embeds(raw, urls)
    assert rewritten == "see ![shot.png](/attachments/abc) and !missing.png!"
    # the converter keeps the real image and degrades only the missing one
    assert jira_to_markdown(rewritten) == (
        "see ![shot.png](/attachments/abc) and *(image: missing.png)*"
    )
