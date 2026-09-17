# Service-desk email images (RADD-988)

Public replies to external service-desk contacts can carry images referenced
in the comment as MIME attachments. This is an explicit storage export policy:
being able to view a file, choosing a host for uploads, making it the default,
or proxying downloads does not authorize emailing its bytes.

## Setup

In **Settings → Storage**, edit the host approved for external sharing (for
example **General**) and enable **Allow images in service-desk email**. Leave
private/zoned hosts disabled. The hosts list marks enabled hosts **Email images**.
Only instance administrators can edit storage hosts.

Migration `d988emailimages` adds `storage_hosts.email_images_allowed` with a
database default of false. Existing hosts, newly created hosts and environment
seeded hosts all start disabled. No host is enabled by its name.

## Eligibility

- Only inline Markdown image/file links to this instance's attachment endpoint
  in the current public comment are candidates. Query parameters such as image
  width are supported. Repeated references produce one attachment.
- The file must belong to the same issue, be stored on an explicitly enabled
  host, and have no active attachment-specific access grants. Uploader/admin
  read access does not bypass this export restriction.
- Only PNG, JPEG, GIF and WebP with matching, verified image bytes qualify.
  SVG, other files and misleading MIME declarations are excluded.
- At most 10 candidate files, 5 MiB per image and 10 MiB total raw image bytes
  per message. MIME encoding increases the wire size. Storage reads time out.
- Current comment visibility, attachment ownership, host and export setting are
  read at delivery, rather than copied into a queued plan. Deleted/internal
  comments are not delivered; a host disabled or file moved before delivery
  no longer qualifies.

Included references become `[Image attached]`; excluded local references become
`[Attachment not included]`. The latter discloses neither filename nor storage
location. Text still sends if a file is missing, blocked, invalid or too large.
There is no generated direct or presigned download-link fallback. The existing
issue link remains subject to normal application access checks.

## Scope and verification

This applies to the external requester reply path. It does not automatically
attach every file on the issue or add attachments to digests, acknowledgements,
CSAT surveys or internal user notifications. External URLs, raw HTML and
reference-style Markdown are not fetched. Images are downloadable MIME parts,
not inline CID rendering. Existing text is not a general data-loss-prevention
filter: agents must still choose what they write in a public reply.

`server/tests/test_mail_attachments.py` covers opt-in, mixed General/private
replies, restricted/cross-parent files, MIME/content verification, size/count
limits, unavailable storage, revocation/moves and the actual outbound → SMTP
MIME path. SMTP is captured locally; no test emails are sent.

`node web/scripts/storage-email-proof.mjs` exercises the built SPA against a
local fixture API: default-off checkbox, selective enable, save payload, reopen,
private-host exclusion, disable, new-host default and visible layout. It writes
its screenshot to `/tmp/radd-988-storage-settings.png` and changes no live settings.
