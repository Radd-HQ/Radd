# Resolvable issue threads

RADD-1282 adds a distinction between ordinary comments and discussions that
need a resolution, modelled on GitLab. The issue composer has two buttons that
light up once there is text: **Comment** posts an ordinary comment, **Start
thread** posts a resolvable one. Both kinds support replies. Replying to an
ordinary comment does not turn it into a blocking thread.

A thread is marked in the list: a framed card with a coloured left rule and a
status chip — **Unresolved thread**, or **Resolved by <name>** once closed.

Resolve and unresolve sit beside a thread's replies, shown only to people the
project's rule allows (below). Resolution keeps the discussion and its replies.
A resolved thread still takes replies: **Reply** leaves it resolved, **Reply and
unresolve** (offered to whoever may unresolve it) reopens it in the same write.
The **Unresolved threads** filter searches all visible comments, including older
pages.

Wiki pages work the same way (RADD-1283): a page's **Discussion** has Start
thread, the thread marking, Resolve/Unresolve, Reply and unresolve and the
Unresolved filter; inline annotations offer Reply and unresolve too.

## Who can resolve threads

**Project settings → Workflow → Who can resolve threads** sets a default and,
optionally, a rule per issue type (a type's rule beats the default):

| Rule | Who may resolve / unresolve |
|---|---|
| The thread's author and project managers | the default — RADD-1282's original rule |
| The author, the issue's assignee and project managers | e.g. the reviewer closes review threads |
| Anyone who can comment on the issue | GitLab's behaviour |
| Project managers only | not even the author |

Anyone else sees the thread's status but no Resolve button, and no Reply and
unresolve. Losing comment permission loses resolve under every rule except
"managers only". Pages have no project or issue type, so page threads always use
the default, with page managers as the managers. Changes appear in the audit log.

## Require resolution before a status change

In **Project settings → Workflow → Transitions**:

1. Set enforcement to **Guards** (or **Strict** if the project requires a complete
   transition graph). **Off** disables all transition conditions.
2. Add or edit a transition to the status you want to protect. Use **Any state**
   as its source to cover every incoming move.
3. Enable **All threads must be resolved**.
4. To restrict this to particular issue types, set **Applies when → Issue type
   → is** and select the types. Leave Applies when empty for every issue type.
5. Repeat for each protected status, such as Code Review and Done.

Existing first-match precedence still applies. Edit the governing row rather
than adding a second rule below an earlier matching transition; put specific
rows above general rows. Other field conditions and approvals are preserved.

The guard runs in the shared issue-update path, including API, MCP and automation
state changes. Ordinary comments and replies never block it. No threads, or
only resolved threads, satisfy it. Open internal/team-restricted threads also
block it even when the person changing status cannot read them. The failure
message reveals no thread text, authors, team names or counts; ask a project
manager if the visible unresolved-thread list is empty.

This is a transition condition, not a continuous state constraint. A new or
reopened thread on an already-closed issue does not automatically reopen the
issue; it affects the next applicable status change.

## Upgrade and API

Apply migrations `d1282threads` and `d1283threadpolicy` before starting the updated application. Existing
ordinary comments and replies remain ordinary. Existing inline annotations and
roots explicitly resolved through the old API remain resolvable.

- Create: `POST /items/{id}/comments` with `is_thread: true` (default false).
- Resolve/reopen: `POST /comments/{id}/resolve` or `/reopen`.
- Reply and unresolve: `POST /comments/{id}/replies` with `unresolve: true`;
  without it a reply leaves a resolved thread resolved.
- Who can resolve: `GET`/`PUT /projects/{id}/thread-resolution` (project.manage),
  body `{"default": "author", "overrides": [{"issue_type_id": …, "resolvers": "anyone"}]}`
  — PUT replaces the whole policy. Every comment read carries `can_resolve` for
  the reader; clients show controls by it rather than restating the rule.
- Unresolved feed: `GET /items/{id}/comments/feed?unresolved=true` (composes with
  `section`, e.g. a page's `section=discussion&unresolved=true`).
- Workflow rule: `{"check":"require_resolved_threads","params":{}}`.
- MCP `comment_item` accepts `is_thread: true`; it cannot be combined with
  `reply_to`. With `reply_to`, `unresolve: true` reopens a resolved thread. The REST resolution endpoints use the same permissions as the UI.

Creation and resolution/reopening lock the parent issue to serialize against
state updates; resolution also locks the root against replies. The workflow
check uses an indexed existence query over unresolved roots, independent of
comment pagination and the caller's comment audience.
