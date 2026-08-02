# Spec 102 — attachment storage rebuilt: multi-host, routed, ACL'd, polymorphic

**.** One global backend (spec 33) becomes N storage hosts as DB rows
with an ordered routing chain deciding where each upload lives, per-attachment
read grants, and wiki pages as first-class parents.

## Why

The deployment target runs NETWORK ZONES: an isolated zone whose storage must
be physically unreachable to users outside it. That needs separate S3
*deployments* (not buckets), per-upload routing, and delivery that lets the
network — not application logic — decide who can fetch bytes. Garage is the
blessed S3 server (MinIO CE was archived 2026-02; the code stays
server-agnostic over the S3 API).

## The pieces

- **`storage_hosts`** rows (filesystem | s3): endpoint/bucket/credentials
  (redacted reads, empty-keeps), per-host **delivery mode** — `proxy` (bytes
  through the API) or `presigned` (307 to a short presigned URL minted with the
  host's own credentials; presigning is pure HMAC, so the API can mint for a
  host it cannot even reach — the browser's network position decides the
  fetch). Exactly one default host; env seeds one row once; live health probes;
  the kernel STORAGE_BACKEND socket finally sits in the request path (the
  registered impl is a client CLASS taking the host row — a plugin host type is
  one IntegrationSpec).
- **Routing** (`storage_rules`, firewall-style, first match wins, default host
  as the terminal): `user_choice` — uploaders are asked (a small prompt before
  the upload, once per gesture) among user-selectable hosts **when the answer
  can matter**: upload-context simulates the chain for the gesture's content
  types + the caller's IP, and an earlier decisive rule (an LLM rule covering
  image/*, a CIDR rule matching the address) suppresses the prompt and is
  named in `preempted_by` — asking and then discarding the answer is worse
  than not asking. A choice is honored only if it names a selectable host; `cidr` — the
  trusted-proxy-resolved client IP (new `radd/clientip.py`,
  `RADD_TRUSTED_PROXIES`) against admin CIDRs; `llm` — an admin-authored
  filtering prompt + ENUMERATED answers each mapped to a host, executed via the
  spec-101 vision role with structured output ("if this image contains human
  characters or 3d assets → content"). Every failure mode falls through to the
  next rule; rule types are a kernel socket (STORAGE_ROUTING_RULE).
- **Per-attachment read ACL** on the spec-92 framework: an `attachment`
  ResourceSpec (read, default-open, user/team/role subjects) — no grants =
  everyone who reads the parent; any grant restricts; uploader + parent-writers
  always pass. Enforced at the ONE download/presign mint chokepoint; listings
  filter unreadable rows and flag restricted ones (the lock badge → the generic
  AccessGrantsEditor). S3 itself cannot express this (Garage has no IAM/STS/
  object ACLs) — Radd's ACL is the source of truth and S3 access is derived
  per-request.
- **Polymorphic parents**: `(entity_type, entity_id)` replaces the item FK;
  bindings are a registry (`parents.py`) — attachments registers `item`, docs
  registers `doc_page` at its own init, so the wiki editor finally uploads
  images. Canonical `POST/GET /attachments`; the item aliases stay. Events keep
  `item_id` for item parents (notify/automation compat).
- **Visible placement**: every attachment read carries `storage_host_name` and
  the grid badges each file with its host — where bytes live is never a mystery.
- **Move job**: per host, copy → verify size (etag best-effort) → repoint →
  best-effort source delete; per-file failures accumulate into an amber "done,
  with skips"; a failed file's row keeps pointing at the source.
- **Orphan GC**: a head-seeded consumer on `item.deleted`/`doc_page.deleted`
  removes rows + grants + BYTES — the old FK cascade deleted rows and orphaned
  bytes forever; with no FK this consumer is the correctness mechanism.
- **Blob API** (`save_blob`/`read_blob`/`remove_blob`): other modules' loose
  bytes (jiraimport snapshots) pin the default host, skip routing, and guard
  host deletion through `hosts.register_use_check`.

## Deliberately deferred

Presigned-PUT direct upload (schema carries `state=pending` for it): uploads
stay through the API because LLM rules and the filter socket need bytes BEFORE
a host is chosen, and the decided topology lets the API reach every host.
Multi-filesystem-host backup packing (backup includes the DEFAULT filesystem
host's tree; S3 bytes stay outside backups — Garage replication is that
story). A public mint path for images on public KB pages.

## Dev stack

`podman compose -f compose.dev.yaml --profile storage up -d` starts two Garage
hosts (localhost:3900/3910); `sh deploy/garage/init.sh garage-1` lays out the
node and imports a fixed dev key. docs/deploy.md has the walkthrough.
