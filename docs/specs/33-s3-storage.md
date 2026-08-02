# Spec 33 — S3/MinIO object storage for attachments

Attachment bytes currently live on the local filesystem (spec 29). For anything
beyond a single node — and for studio NAS/MinIO deployments — attachments need an
S3-compatible backend. This spec adds a **storage seam** inside the attachments
module with two backends selected by `RADD_ATTACHMENT_STORAGE`:

- `filesystem` (default, unchanged): streams to `RADD_ATTACHMENTS_DIR`, served
  with `FileResponse`.
- `s3`: any S3-compatible store (MinIO, Garage, AWS). Uploads buffer to the size
  cap (25 MB default — in-memory is fine at that bound) and `put_object`; downloads
  **redirect (307) to a short-lived presigned GET** (`RADD_S3_PRESIGN_EXPIRY_SECONDS`,
  300s) carrying `response-content-disposition`/`content-type`, so bytes never
  proxy through the app. The bucket is created on startup if missing.

Client: the lightweight `minio` Python SDK (sync, wrapped in `asyncio.to_thread`).

Settings: `RADD_ATTACHMENT_STORAGE` (`filesystem`|`s3`), `RADD_S3_ENDPOINT`
(`host:port`), `RADD_S3_ACCESS_KEY`/`RADD_S3_SECRET_KEY`, `RADD_S3_BUCKET`
(`radd-attachments`), `RADD_S3_SECURE` (default false — LAN MinIO; set true behind
TLS).

The DB row is backend-agnostic (`storage_name` is the object key either way), so
**switching backends only affects new uploads**; old rows keep serving from the
backend that stored them? — NO: simpler and honest, the backend is global. Migrating
existing files = copy `RADD_ATTACHMENTS_DIR/*` into the bucket keyed by filename
(documented, no tool yet).

## Known simplifications

- One global backend; per-workspace storage config comes with the settings UI.
- Presigned redirects mean the final response headers come from the object store
  (no `X-Content-Type-Options` there); the inline/download split still holds via
  `response-content-disposition`, and uploads store the content type we validated.
- No migration tool for existing filesystem attachments (copy files into the
  bucket with the same names).
- In-memory upload buffering bounded by the attachment size cap.
