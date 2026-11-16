"""The restore path is drilled with the client the image ships (RADD-1543).

The image carried PostgreSQL 17 client tools against a 16 server. `pg_dump` 17
writes `SET transaction_timeout = 0;` into every archive; a 16 server does not
know the setting, and one unknown `SET` aborted the single-transaction restore.
Every backup was "verified" and none could be restored.
"""

import re
from pathlib import Path

from radd.backup.postgres import strip_unknown_settings

REPO = Path(__file__).resolve().parents[2]

HEADER = (
    b"--\n-- PostgreSQL database dump\n--\n\n"
    b"SET statement_timeout = 0;\n"
    b"SET transaction_timeout = 0;\n"
    b"SET client_encoding = 'UTF8';\n"
    b"SET default_table_access_method = heap;\n"
    b"SET vendor.option = 'x';\n"
    b"\nCREATE TABLE public.notes (body text);\n"
    b"COPY public.notes (body) FROM stdin;\n"
)


def test_a_setting_the_server_does_not_have_is_dropped_and_the_rest_is_untouched():
    known = {"statement_timeout", "client_encoding", "default_table_access_method"}
    cleaned = strip_unknown_settings(HEADER, known)
    assert b"transaction_timeout" not in cleaned
    assert cleaned == HEADER.replace(b"SET transaction_timeout = 0;\n", b"")
    # An extension's dotted setting is not in pg_settings until the extension loads: kept.
    assert b"SET vendor.option = 'x';" in cleaned


def test_a_server_that_knows_every_setting_gets_the_script_unchanged():
    known = {"statement_timeout", "transaction_timeout", "client_encoding", "default_table_access_method"}
    assert strip_unknown_settings(HEADER, known) == HEADER


def test_only_whole_set_lines_match():
    """Table data is never examined (only the header is passed in), but even
    there a line has to BE a `SET name = …;` statement to be dropped."""
    text = b"  SET transaction_timeout = 0;\nSELECT 'SET transaction_timeout = 0;';\n"
    assert strip_unknown_settings(text, set()) == text


def test_ci_drills_with_the_client_major_the_image_ships():
    major = re.search(r"postgresql-client-(\d+)", (REPO / "Containerfile").read_text()).group(1)
    workflow = (REPO / ".github" / "workflows" / "checks.yaml").read_text()
    matrix = re.search(r"client: \[([0-9, ]+)\]", workflow)
    assert matrix, "the drills job lost its client matrix"
    assert major in [m.strip() for m in matrix.group(1).split(",")], (
        f"the image ships postgresql-client-{major}; the restore drill must run with it"
    )


def test_ci_runs_the_suite_on_the_interpreter_the_image_ships():
    """RADD-1535: pytest ran on 3.13 (`.python-version`) while the image shipped
    3.12, so a release was tested on an interpreter it did not run on."""
    shipped = re.search(r"python:(\d+\.\d+)", (REPO / "Containerfile").read_text()).group(1)
    workflow = (REPO / ".github" / "workflows" / "checks.yaml").read_text()
    tested = re.search(r'UV_PYTHON: "(\d+\.\d+)"', workflow)
    assert tested, "checks.yaml no longer pins the interpreter it tests on"
    assert tested.group(1) == shipped, f"CI tests on {tested.group(1)}, the image ships {shipped}"
