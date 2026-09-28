"""The release-notes range starts at the last tag the host PUBLISHED (RADD-1479):
a tag whose publish run failed must not swallow every change before it."""
import importlib.util
from pathlib import Path
import unittest
import urllib.error

SPEC = importlib.util.spec_from_file_location("release_notes", Path(__file__).parents[1] / "release_notes.py")
release_notes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_notes)

CHAIN = {"v0.49.2": "v0.49.1", "v0.49.1": "v0.49.0", "v0.49.0": "v0.48.0", "v0.48.0": "v0.47.0", "v0.47.0": "0123abcd"}


class FakeHost:
    def __init__(self, published, token="t", fail=False):
        self.published, self.token, self.fail = set(published), token, fail

    def get_release(self, tag):
        if self.fail:
            raise urllib.error.URLError("host down")
        return {"tag_name": tag} if tag in self.published else None


class RangeTests(unittest.TestCase):
    def setUp(self):
        self._real = release_notes.previous_tag
        release_notes.previous_tag = lambda tag: CHAIN[tag]
        self.addCleanup(setattr, release_notes, "previous_tag", self._real)

    def test_unpublished_tags_are_walked_over(self):
        host = FakeHost({"v0.48.0", "v0.47.0"})
        self.assertEqual(release_notes.previous_published_tag("v0.49.2", host), "v0.48.0")

    def test_a_published_previous_tag_is_kept(self):
        self.assertEqual(release_notes.previous_published_tag("v0.49.1", FakeHost({"v0.49.0"})), "v0.49.0")

    def test_no_token_means_the_plain_previous_tag(self):
        self.assertEqual(release_notes.previous_published_tag("v0.49.2", FakeHost(set(), token="")), "v0.49.1")

    def test_a_host_that_cannot_be_asked_does_not_block(self):
        self.assertEqual(release_notes.previous_published_tag("v0.49.2", FakeHost(set(), fail=True)), "v0.49.1")

    def test_the_first_commit_ends_the_walk(self):
        self.assertEqual(release_notes.previous_published_tag("v0.49.2", FakeHost(set())), "0123abcd")


if __name__ == "__main__":
    unittest.main()
