"""The sample/export importer must not bypass the wizard's audience safeguards."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def test_cli_omits_unknown_audiences_and_keeps_internal_notes(monkeypatch):
    scripts = Path(__file__).parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('jira_comment_cli_test', scripts / 'import_jira.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    sent = []

    def post(path, json):
        sent.append(json)
        return 201, {}

    ctx = SimpleNamespace(users_by_email={}, report=module.Report(),
                          api=SimpleNamespace(post_dependent=post))
    module.import_comments(ctx, 'item', {'jira_key': 'SRC-1', 'comments': [
        {'body': 'public', 'author_email': 'test@example.com'},
        {'body': 'internal', 'author_email': 'test@example.com', 'internal': True},
        {'body': 'group', 'author_email': 'test@example.com', 'restriction': {'type': 'group', 'value': 'staff'}},
        {'body': 'role', 'author_email': 'test@example.com', 'visibility': {'type': 'role', 'value': 'admin'}},
    ]})
    assert [(p['body'], p['visibility']) for p in sent] == [('public', 'public'), ('internal', 'internal')]
    assert len(ctx.report.warnings) == 2
