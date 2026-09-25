"""Discovery must never pass by omitting a class of repository artifacts."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("plugin_inventory", Path(__file__).parents[1] / "plugin_inventory.py")
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def write(self, path, value, *, tracked=True):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(value)
        if tracked:
            subprocess.run(["git", "add", "--", path], cwd=self.root, check=True)

    def run_inventory(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return inventory.run(self.root, **kwargs)

    def data(self, name):
        return json.loads((self.root / inventory.LEDGER / f"{name}.json").read_text())

    def test_every_tracked_artifact_is_accounted_for_including_unknown_types(self):
        artifacts = {
            "server/migrations/versions/new.py": "from radd.db import Base\n",
            "sdk/src/client.py": "import httpx\n",
            "web/packages/plugin-sdk/vite.mjs": "import { plugin } from 'builder';\n",
            "scripts/check.sh": "#!/bin/sh\ntrue\n",
            "deploy/Containerfile": "FROM example\n",
            ".github/workflows/check.yaml": "jobs: {}\n",
            "web/src/app.css": "body {}\n",
            "docs/architecture.md": "# Architecture\n",
            "mystery.unknown": "unknown syntax\n",
        }
        for path, value in artifacts.items():
            self.write(path, value)
        data = inventory.discover(self.root)
        self.assertEqual(set(data["files"]), set(artifacts))
        self.assertEqual(data["files"]["mystery.unknown"]["role"], "unclassified")
        self.assertEqual(data["files"]["server/migrations/versions/new.py"]["role"], "migration")
        self.assertEqual(data["files"]["web/packages/plugin-sdk/vite.mjs"]["imports"][0]["module"], "builder")

    def test_new_source_is_seen_without_following_ignored_or_untracked_local_artifacts(self):
        self.write(".gitignore", "node_modules/\n.env\n")
        self.write("web/src/new.jsx", "export const value = 1;", tracked=False)
        self.write("server/src/new.py", "value = 1", tracked=False)
        self.write("web/package.json", '{"name":"new-package"}', tracked=False)
        self.write("web/node_modules/library/index.js", "ignored", tracked=False)
        self.write(".env", "SECRET=local", tracked=False)
        self.write("docs/personal.md", "local notes", tracked=False)
        self.write("web/scripts/personal.png", "local screenshot", tracked=False)
        files = inventory.discover(self.root)["files"]
        self.assertEqual(set(files), {".gitignore", "web/src/new.jsx", "server/src/new.py", "web/package.json"})
        self.assertEqual(self.run_inventory(), [])
        subprocess.run(["git", "add", "web/src/new.jsx"], cwd=self.root, check=True)
        self.assertEqual(self.run_inventory(check=True), [])

    def test_current_reviews_survive_but_byte_changes_require_a_new_review(self):
        self.write("web/src/component.ts", "export const x = 1;\n")
        self.assertEqual(self.run_inventory(), [])
        review = self.data("review")
        review["web/src/component.ts"].update(status="reviewed", owner="example", issue="RADD-1", evidence=["inspected source and browser behavior"])
        self.write(f"{inventory.LEDGER}/review.json", json.dumps(review))
        self.assertEqual(self.run_inventory(check=True), [])
        self.assertEqual(self.run_inventory(require_reviewed=True, check=True), [])
        self.write("web/src/component.ts", "export const x = 2;\n")
        before = (self.root / inventory.LEDGER / "review.json").read_bytes()
        self.assertTrue(self.run_inventory(check=True))
        self.assertEqual((self.root / inventory.LEDGER / "review.json").read_bytes(), before)
        self.assertEqual(self.run_inventory(), [])
        self.assertEqual(self.data("review")["web/src/component.ts"]["status"], "unreviewed")
        self.assertTrue(self.run_inventory(require_reviewed=True, check=True))

    def test_deletion_is_archived_and_restoration_returns_to_current_scope(self):
        self.write("web/src/removed.ts", "export const x = 1;\n")
        self.run_inventory()
        (self.root / "web/src/removed.ts").unlink()
        self.assertTrue(self.run_inventory(check=True))
        self.run_inventory()
        self.assertIn("web/src/removed.ts", self.data("retired"))
        self.assertEqual(self.data("retired")["web/src/removed.ts"]["status"], "unreviewed")
        self.assertEqual(self.run_inventory(check=True), [])
        self.assertTrue(self.run_inventory(check=True, require_reviewed=True))
        subprocess.run(["git", "rm", "--cached", "web/src/removed.ts"], cwd=self.root, check=True, stdout=subprocess.DEVNULL)
        self.assertEqual(self.run_inventory(check=True), [])
        self.write("web/src/removed.ts", "export const x = 1;\n")
        self.run_inventory()
        self.assertNotIn("web/src/removed.ts", self.data("retired"))
        self.assertEqual(self.data("review")["web/src/removed.ts"]["status"], "unreviewed")

    def test_builtin_and_external_manifests_and_package_dependencies_are_discovered(self):
        self.write("server/src/radd/modules/example/__init__.py", "plugin = RaddPlugin(name='example', depends_on=('auth',))\n")
        self.write("server/src/radd/modules/example/ui/src/index.tsx", "export {};\n")
        self.write("examples/external/src/external/__init__.py", "plugin = RaddPlugin(name='external', core=False)\n")
        self.write("examples/external/src/external/ui/src/index.tsx", "export {};\n")
        self.write("examples/external/src/external/ui/package.json", '{"name":"external-ui","dependencies":{"@radd/plugin-sdk":"*"}}')
        self.write("examples/external/pyproject.toml", '[project]\nname="external"\ndependencies=["radd"]\n[project.entry-points."radd.plugins"]\nexternal="external:plugin"\n')
        data = inventory.discover(self.root)
        self.assertEqual(len(data["modules"]), 2)
        self.assertEqual(data["modules"]["example"]["declarations"]["depends_on"], ["auth"])
        external = next(entry for key, entry in data["modules"].items() if key.startswith("example:"))
        self.assertEqual(external["ui_sources"], ["examples/external/src/external/ui/src/index.tsx"])
        self.assertEqual(data["packages"]["examples/external/pyproject.toml"]["project"]["entry-points"]["radd.plugins"], {"external": "external:plugin"})
        self.assertEqual(self.run_inventory(), [])
        self.assertEqual(self.run_inventory(check=True), [])

    def test_parse_errors_are_visible_and_cannot_pass_freshness_checks(self):
        self.write("server/src/broken.py", "def broken(\n")
        self.write("web/package.json", "{")
        self.assertEqual(len(inventory.discover(self.root)["files"]), 2)
        self.assertEqual(len(inventory.discover(self.root)["discovery_errors"]), 2)
        self.assertTrue(self.run_inventory())
        self.assertTrue(self.run_inventory(check=True))

    def test_symlinks_record_target_without_reading_outside_repository(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.py"
            target.write_text("def invalid(\n")
            (self.root / "linked.py").symlink_to(target)
            subprocess.run(["git", "add", "linked.py"], cwd=self.root, check=True)
            entry = inventory.discover(self.root)["files"]["linked.py"]
            self.assertEqual(entry["role"], "symlink")
            self.assertEqual(entry["target"], str(target))
            self.assertNotIn("discovery_error", entry)

    def test_review_claims_need_evidence_and_exceptions_need_reasons(self):
        self.assertTrue(inventory.review_errors({"a": {"status": "reviewed"}}, require_reviewed=False))
        row = {"status": "exception", "owner": "example", "issue": "RADD-1", "evidence": ["test"]}
        self.assertTrue(inventory.review_errors({"a": row}, require_reviewed=True))
        row["reason"] = "Generated derivative; verify its generator and emitted artifact."
        self.assertEqual(inventory.review_errors({"a": row}, require_reviewed=True), [])

    def test_only_generated_ledgers_are_excluded_from_tracked_scope(self):
        for path in inventory.GENERATED:
            self.write(path, "{}")
        self.write(f"{inventory.LEDGER}/README.md", "The audit's working agreement")
        self.assertEqual(set(inventory.discover(self.root)["files"]), {f"{inventory.LEDGER}/README.md"})
        self.run_inventory()
        (self.root / inventory.LEDGER / "retired.json").unlink()
        self.assertTrue(self.run_inventory(check=True))


if __name__ == "__main__":
    unittest.main()
