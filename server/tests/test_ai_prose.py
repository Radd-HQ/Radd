"""What reaches a model is prose (RADD-1232): images, data URIs, tags and bare
addresses are not, and the summary/similar/automation/embedding seams all
read through the same function."""

from radd.modules.ai import prose as prose_module
from radd.modules.ai.embeddings import embedder
from radd.modules.ai.prose import IMAGE_MARKER, LINK_MARKER, prose


def test_images_become_a_marker_and_keep_their_alt():
    body = "Steps:\n\n![login screen](/api/v1/attachments/abc/content?w=800)\n\nThen it fails."
    out = prose(body)
    assert "/api/v1/attachments" not in out
    assert f"{IMAGE_MARKER} login screen" in out
    assert "Then it fails." in out


def test_a_pasted_data_uri_is_gone_entirely():
    blob = "data:image/png;base64," + "iVBORw0KGgo" * 400
    out = prose(f"before\n\n![image.png]({blob})\n\nafter")
    assert len(out) < 60
    assert "base64" not in out and "before" in out and "after" in out


def test_link_text_survives_but_addresses_do_not():
    out = prose("see [the runbook](https://wiki.example.com/x/y) and https://example.com/very/long/path?a=1")
    assert "the runbook" in out
    assert "wiki.example.com" not in out
    assert out.endswith(LINK_MARKER)


def test_html_tags_and_extension_fences_are_not_prose():
    body = '<img src="x.png"><p>Hello</p>\n\n```radd:children\n{"depth": 2}\n```\n\nBye'
    out = prose(body)
    assert "<img" not in out and "<p>" not in out
    assert '"depth"' not in out
    assert "Hello" in out and "Bye" in out


def test_code_is_kept_because_a_stack_trace_is_the_report():
    body = "```\nTraceback (most recent call last):\n  File x.py\n```"
    assert prose(body) == body


def test_the_embedding_text_reads_through_prose():
    text = embedder.embed_text("TD-1", "Login fails", "![shot](data:image/png;base64,AAAAAAAAAAAAAAAAAAAAAAAA)\n500 on submit")
    assert "base64" not in text and "500 on submit" in text
    assert prose_module.IMAGE_MARKER in text
