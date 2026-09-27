from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RADD_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://radd:radd@localhost:5455/radd"
    # Async engine pool (RADD-897): sized for one web replica + its background
    # loops; pre-ping trades a cheap SELECT 1 per checkout for never handing a
    # request a connection the database already dropped.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True
    # Postgres kills an app session idle-in-transaction this long (RADD-845): a leak costs
    # one connection, not a wedged migration. 0 disables; app engine only.
    db_idle_tx_timeout_seconds: int = 600
    api_title: str = "Radd"
    api_prefix: str = "/api/v1"
    # Built SPA to serve at / (empty or missing dir = API-only). Default: the repo's web/dist.
    web_dist: str = ""
    # Shared persistent volume, identical on every web and worker process.
    plugins_dir: str = "var/plugins"
    # Live plugin lifecycle (RADD-1341/1372; kernel/admission.py, pluginmgr/live.py).
    # Every process polls desired state this often (one small query; discovery
    # only runs when something moved).
    plugin_reconcile_interval_seconds: float = 2.0
    # Each process writes its acknowledgement row and renews its lease this often.
    plugin_heartbeat_seconds: float = 5.0
    # Without a heartbeat for this long, a process refuses non-core plugin work.
    # MUST stay below plugin_process_stale_seconds: peers disregard a stale row
    # only because its process has already stopped admitting.
    plugin_lease_seconds: float = 25.0
    plugin_process_stale_seconds: float = 30.0
    # How long a toggle waits for the plugin's own requests/jobs/ticks before
    # reporting and retrying; never cancels them.
    plugin_drain_timeout_seconds: float = 30.0
    # A failed apply retries after the reconcile interval, doubling up to this.
    plugin_retry_max_seconds: float = 60.0
    # Acknowledgement rows of processes gone this long are deleted.
    plugin_process_retention_hours: int = 24

    # Auth (see radd/modules/auth)
    session_ttl_hours: int = 720
    auth_login_window_seconds: float = Field(default=300.0, gt=0)
    auth_login_account_attempts: int = Field(default=20, gt=0)
    auth_login_ip_attempts: int = Field(default=120, gt=0)
    auth_login_bucket_limit: int = Field(default=10000, gt=0)
    # Per-account write admission (RADD-1148): a sliding window over issue + comment
    # creation; admins and the automation actor are exempt. Per process, like the above.
    write_window_seconds: int = Field(default=3600, gt=0)
    item_creates_per_window: int = Field(default=30, gt=0)
    comments_per_window: int = Field(default=120, gt=0)
    write_throttle_bucket_limit: int = Field(default=10000, gt=0)
    auth_password_workers: int = Field(default=4, gt=0)
    session_cookie_secure: bool = False  # enable behind HTTPS
    token_last_used_throttle_seconds: int = 60  # min interval between PAT last_used_at writes
    # Staleness bound for module-level snapshots (RADD-899) — capability pills,
    # login-page provider buttons, the default-storage-host mirror. A second web
    # replica converges within this window instead of "until restart".
    snapshot_ttl_seconds: float = 30.0

    # Worker split (spec 48): false = this process serves web only; the
    # background loops (webhooks/automations/notify/search/sla/mail)
    # stay dormant. Realtime + storage init always run (they serve the web tier).
    run_workers: bool = True
    # The task_backend socket provider that runs kernel TaskSpecs; "localloop" is built in.
    task_backend: str = "localloop"

    # Webhook dispatcher (see radd/modules/webhooks)
    webhook_poll_interval: float = 1.0
    webhook_timeout: float = 5.0
    # Seconds until the Nth retry after a failed attempt; exhausted -> dead-letter.
    webhook_retry_schedule: tuple[int, ...] = (5, 300, 1800, 7200, 18000, 36000)
    webhook_fanout_batch: int = 100
    webhook_attempt_batch: int = 20

    # Automations engine (see radd/modules/automations)
    automation_poll_interval: float = 1.0
    automation_batch: int = 100
    # Scheduled rules (spec 69): the scheduler loop's tick, the IANA timezone
    # daily/weekly times are interpreted in (one instance clock), and the cap on
    # items one scheduled run may act on (ordered by rank; truncation is logged).
    automation_scheduler_interval: float = 60.0
    scheduler_tz: str = "UTC"
    automation_schedule_max_items: int = 200
    # Graph run ceilings (spec 116), on nodes and on item actions. Hitting one is RECORDED
    # in the run report: a run that quietly did less reads like one with less to do.
    automation_graph_max_node_runs: int = 200
    # RADD-1315: a trigger opted in to other automations' changes fires only below this
    # chain depth, so two rules that feed each other stop instead of looping.
    automation_max_chain_depth: int = 3
    automation_graph_max_item_actions: int = 2000
    #: How long recorded runs are kept (RADD-1266). 0 keeps them forever.
    automation_run_retention_days: int = 30

    # --- scripts plugin (RADD-1269) — the managed interpreter and its runs ---
    #: Where the venv lives. A persistent volume in production (the chart mounts /data).
    scripts_dir: str = "var/scripts"
    #: Where a run's temporary directory is made; empty = the system temp dir.
    scripts_run_dir: str = ""
    scripts_uv_path: str = "uv"
    scripts_default_python: str = "3.12"
    #: The Radd SDK client installed into every venv: a wheel or source path, or
    #: a package name. Empty = the newest `radd_sdk` wheel in a wheelhouse, else
    #: the checkout's sdk/ when present, else the `radd-sdk` package.
    scripts_sdk_source: str = ""
    #: Wheelhouse dirs uv resolves from before any index (comma-separated; the image sets
    #: /app/wheels so the build needs no network); `<scripts_dir>/wheels` is always
    #: searched. The index URL is a Settings → Scripts row.
    scripts_find_links: str = ""
    #: The URL a script's `ctx.client` calls; empty = `app_base_url`. The chart sets the
    #: in-cluster service so a script never hairpins through the ingress.
    scripts_api_url: str = ""
    #: Ceiling on a node's timeout param, and the default when it names none.
    scripts_max_timeout_seconds: int = 300
    scripts_default_timeout_seconds: int = 60
    #: How long a uv invocation (venv, install) may take.
    scripts_tool_timeout_seconds: int = 600
    #: How many items a script is handed at once (the read models are wide).
    scripts_max_items: int = 50
    # Spec 119: wall clock ONE intake verdict may spend. It runs in the create transaction
    # holding the project's number lock, so it bounds how long other creations queue; keep
    # it under ai_timeout_seconds (a slow check leaves by its "can't check" port, RADD-1329).
    intake_validation_budget_seconds: float = 25.0

    # Event-cascade consumer (see radd/modules/events/cascade.py) — events read
    # per iteration when draining kernel-registered cascades.
    event_cascade_batch: int = 50

    # Notifications (see radd/modules/notify)
    notify_poll_interval: float = 1.0
    notify_batch: int = 100
    # Email digests: one batched email per user per interval.
    notify_email_interval: float = 300.0
    notify_email_max_age_hours: int = 24
    # Per-event mail (RADD-968): the faster loop for immediate-email types; sent rows get
    # `emailed_at` so the digest skips them.
    notify_mail_poll_interval: float = 5.0
    notify_mail_batch: int = 100
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    # Read from RADD_SMTP_FROM or RADD_SMTP_FROM_ADDRESS (docs always said the former).
    smtp_from_address: str = Field(
        default="Radd <radd@localhost>",
        validation_alias=AliasChoices(
            "RADD_SMTP_FROM", "RADD_SMTP_FROM_ADDRESS", "smtp_from_address"
        ),
    )
    # Absolute base URL used in outbound links (email digests, connectors).
    app_base_url: str = "http://localhost:8000"

    # Realtime WebSocket tail (see radd/modules/realtime)
    realtime_poll_interval: float = 0.5
    realtime_batch: int = 200
    realtime_session_refresh_seconds: float = Field(default=60.0, gt=0)
    realtime_send_timeout: float = Field(default=2.0, gt=0)
    realtime_send_concurrency: int = Field(default=32, gt=0)

    # Collaborative editing (see radd/modules/collab, spec 122). Rooms are
    # in-process: one API replica, or sticky routing of /api/v1/collab/*.
    collab_seed_grant_seconds: float = Field(default=20.0, gt=0)  # a seed grant nobody used lapses
    collab_persist_debounce_seconds: float = Field(default=1.0, gt=0)
    collab_room_idle_seconds: float = Field(default=60.0, gt=0)  # empty room → dropped from memory
    collab_frame_auth_seconds: float = Field(default=5.0, gt=0)  # session re-check cadence on inbound frames
    # Scalar cascade default (instance scope, owned by `pages`): a collab save
    # writes a page_versions row only when the last one is older than this.
    page_collab_version_window_seconds: int = 300

    # Search indexer (see radd/modules/search)
    search_poll_interval: float = 1.0
    search_batch: int = 200

    # Attachments (see radd/modules/attachments). Storage backend: "filesystem"
    # (default; attachments_dir) or "s3" (any S3-compatible store — Garage, AWS).
    attachment_storage: str = "filesystem"
    attachments_dir: str = "var/attachments"
    # 5 GiB: wiki imports carry recordings (spec 117). Uploads spool to disk, so disk,
    # not RAM, is the limit.
    attachment_max_bytes: int = 5 * 1024 * 1024 * 1024
    # Files attached to an intake form that was never submitted (forms/staging.py,
    # RADD-1426): a staging area is reclaimed once its NEWEST file is this many days
    # old; the sweep looks this often.
    form_staging_retention_days: int = Field(default=7, gt=0)
    form_staging_sweep_interval_seconds: float = Field(default=3600.0, gt=0)

    # Spec 117: downloaded Confluence snapshots are working files on local disk (one rmtree
    # to delete), not object-store blobs; bytes reach storage when a run imports them.
    confluence_snapshot_dir: str = "var/confluence-snapshots"
    s3_endpoint: str = "localhost:9000"  # host:port (no scheme; s3_secure picks it)
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "radd-attachments"
    s3_secure: bool = False  # true behind TLS
    s3_presign_expiry_seconds: int = 300

    # SLA engine (see radd/modules/slas) — periodic timer evaluation.
    sla_check_interval: float = 60.0
    # RADD-1320: `sla.met` for a target met longer ago than this is not emitted
    # when its bookkeeping row is first created — a new policy evaluated over
    # old, long-answered items must not fire a burst of historical "met" events.
    sla_met_event_max_age_hours: int = 24

    # OIDC SSO (radd/modules/sso): SEED-ONLY since spec 110 — the first `sso_providers` row,
    # once, on a database with none; later edits do nothing. Empty issuer = seed nothing.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_auto_provision: bool = True
    # Domains allowed to CREATE accounts via the seeded provider; empty + auto-provision seeds "*".
    oidc_signup_domains: str = ""
    # Groups claim → instance admin, re-synced each login. Empty admin_groups = no role opinion
    # (spec 110), so a Google login cannot demote the AD admin it just linked to.
    oidc_group_claim: str = "groups"
    oidc_admin_groups: str = ""
    # Live tunable (not seed-only): per-request bound on the SSO HTTP round
    # trips (issuer discovery, the code→token exchange).
    sso_http_timeout_seconds: float = 10.0

    # LDAP/AD directory bind (see radd/modules/ldap). Empty url = disabled.
    # Direct bind: the user's own credentials authenticate the connection as
    # <username>@<user_domain> — no stored service/bind account.
    ldap_url: str = ""  # e.g. ldaps://ad.example.com:636
    ldap_user_domain: str = ""  # UPN suffix; also derives the default base DN
    ldap_base_dn: str = ""  # "" = derived (ad.example.com -> DC=ad,DC=example,DC=com)
    ldap_email_attribute: str = "mail"  # falls back to the UPN when absent
    ldap_name_attribute: str = "displayName"  # falls back to the username
    # Comma-separated group CNs whose members (nested membership counts, via
    # AD's transitive matching rule) become instance admins; everyone else
    # joins as member. Role re-synced on every login, as with OIDC.
    ldap_admin_groups: str = ""
    ldap_auto_provision: bool = True
    ldap_timeout_seconds: float = 5.0  # connect + receive bound per login
    # Optional SERVICE-ACCOUNT bind (spec 49) — only for BULK directory enumeration
    # (import_ad_users). Interactive login stays direct-bind (no stored account).
    # Empty bind_dn = enumeration disabled.
    ldap_bind_dn: str = ""  # e.g. CN=svc-radd,OU=Service Accounts,DC=ad,DC=example,DC=com
    ldap_bind_password: str = ""
    ldap_user_search_base: str = ""  # "" = base_dn(); narrow to an OU to scope the import
    ldap_user_filter: str = "(&(objectCategory=person)(objectClass=user)(mail=*))"
    ldap_page_size: int = 500  # AD caps a single search at ~1000; page through
    # Group reconcile loop (RADD-829); needs the bind account + run_workers.
    ldap_group_sync_seconds: float = 3600.0
    # Nesting walk depth cap: a deeper directory degrades to "incomplete" (fails CLOSED).
    group_nesting_max_depth: int = 10
    # Cap on the error list persisted per sync run in directory_sync_state —
    # the JSONB row is a status line, not a log (group + user sync loops).
    ldap_max_recorded_errors: int = 20
    # Directory page + user sync (spec 85): cascade DEFAULTS for instance SettingKeys; an
    # override written on Settings → Directory wins.
    ldap_group_search_base: str = ""  # "" = base_dn(); narrow to a groups OU
    ldap_user_sync_enabled: bool = False  # the automation switch (off = manual only)
    # Deactivate ldap-source users that vanish from the directory. OFF by
    # default so a transient AD outage can't lock people out.
    ldap_user_sync_deactivate_missing: bool = False
    ldap_user_sync_seconds: float = 3600.0  # ldap-usersync loop interval
    # Skip AD ACCOUNTDISABLE accounts in imports and sync. ON: most of a real directory is
    # leavers (a live one held ~2 disabled per active account).
    ldap_exclude_disabled: bool = True

    # RADD-1279: refuse a session to a password login with no second factor.
    # Seed/fallback only — Settings → Sign-in owns it (the `require_mfa` row).
    require_mfa: bool = False
    # How long the enrolment ticket a refused login receives stays usable.
    mfa_enrollment_ticket_minutes: int = 15
    # RADD-1295: the largest source image a profile-picture upload accepts
    # (it is stored as a 256px WebP, so this bounds decode work, not storage).
    avatar_max_upload_bytes: int = 8 * 1024 * 1024

    # Proxies allowed to speak X-Forwarded-For (comma-separated IPs/CIDRs, e.g.
    # your ingress/LB range). "" = the header is ignored and the socket peer is
    # the client IP. Storage CIDR routing rules (spec 102) depend on this being
    # right behind a proxy. See radd/clientip.py.
    trusted_proxies: str = ""

    # AI layer (radd/modules/ai). provider/base_url/api_key/model are SEED-ONLY (spec 101):
    # one provider row + chat role on first boot. max_tokens/timeouts stay live.
    ai_provider: str = ""  # "openai" (any OpenAI-compatible base_url) | "anthropic"
    ai_base_url: str = ""  # "" = the provider's default endpoint
    ai_api_key: str = ""
    ai_model: str = ""
    ai_max_tokens: int = 1024
    ai_timeout_seconds: float = 30.0
    ai_stream_timeout_seconds: float = 120.0  # editor-action SSE read timeout
    # RADD-1273: an Anthropic-shape provider's thinking budget when its row has reasoning
    # ON, added to max_tokens (the API requires it to fit inside). OpenAI shapes ignore it.
    ai_reasoning_budget_tokens: int = 1024
    # RADD-1275: image attachments a summary shows the vision model — count, source cap, width.
    ai_vision_max_images: int = 4
    ai_vision_max_image_bytes: int = 8_000_000
    ai_vision_image_width: int = 1024
    # Embedding indexer (spec 103): batch per /embeddings call, idle-poll interval (the
    # loop DRAINS full batches without sleeping), per-entity text cap.
    ai_embed_batch: int = 256
    ai_embedder_poll_interval: float = 3.0
    ai_embed_max_chars: int = 8000
    # Budget for the semantic half of a hybrid search — past it, FTS-only.
    ai_search_timeout_seconds: float = 2.0
    # Text budget for one AI-classifier prompt (spec 116); size it to your model's context
    # (~40k chars ≈ 10k tokens). Spent on WHOLE items, never cut mid-sentence.
    ai_automation_context_chars: int = 40_000
    #: Items ONE per-item classifier node may classify per run — model round trips, so far
    #: below the action budget. Overflow takes the node's fallback port.
    ai_automation_max_classifications: int = 50
    #: Concurrent model calls for one per-item classifier node. The contexts are
    #: built first, on the walk's single session; only the provider calls overlap.
    ai_automation_classify_concurrency: int = 8
    # Where the built-in CPU embedding backend caches model weights (downloaded
    # from Hugging Face on first use; pre-seed on air-gapped deploys).
    ai_local_embed_cache: str = "var/models"

    # Per-feature AI toggles (spec 101) — env defaults for the Settings → AI
    # instance switches; a feature also needs its role's provider configured.
    ai_editor_actions: bool = True
    ai_semantic_search: bool = True
    ai_storage_routing: bool = True
    mail_signature_max_chars: int = 100_000
    mail_signature_regex_timeout_seconds: float = 0.02
    mail_signature_ai_timeout_seconds: float = 5
    ai_mail_signature: bool = False
    ai_mail_routing: bool = True
    ai_summarize: bool = True
    ai_nl_slq: bool = True
    # OFF by default: the rerank buys reasons + rescoring at the
    # price of a chat-model round trip on every similar-issues open.
    ai_similar_rerank: bool = False
    # Spec 119: kill switch for the ai.validate node (nothing runs until it is in a graph).
    ai_validation: bool = True
    # Spec 120: kill switch for the ai.generate node (same).
    ai_generation: bool = True
    # Deliver summaries / similar-reasons progressively (SSE) instead of
    # complete-then-show.
    ai_stream_responses: bool = True

    # Embedded MCP server (see radd/modules/mcp) — POST {api_prefix}/mcp.
    # Spec 114: above this many permitted projects, a tool's project parameter
    # degrades from an enum to a plain string — a 300-entry enum costs the agent
    # more context than the precision buys it.
    mcp_project_enum_max: int = 25
    # RADD-740: how often the tools/list_changed stream re-checks the caller's
    # catalog, and how often it emits a keepalive comment so proxies do not drop
    # an idle connection. Seconds.
    mcp_catalog_poll_seconds: float = 15.0
    mcp_stream_keepalive_seconds: float = 25.0

    # Forgejo (radd/modules/forgejo): SEED-ONLY since spec 111 — one connection row on first start.
    forgejo_webhook_secret: str = ""
    forgejo_base_url: str = ""  # seed only: https://git.example.com
    # Backfill bounds (spec 111): how far back the API walk goes by default.
    forgejo_backfill_max_commits: int = 2000
    forgejo_api_page_size: int = 50
    # Per-request bound on Forgejo API calls (connection test + backfill walk).
    forgejo_http_timeout_seconds: float = 30.0

    # GitHub connector (see radd/modules/github, RADD-1129). Connections are rows;
    # these SEED one connection (+ one repository) on first startup, then are inert.
    github_webhook_secret: str = ""
    github_api_token: str = ""  # seed only: a read-only fine-grained token
    github_base_url: str = ""  # seed only: https://github.com (default) or a GHES host
    github_repo: str = ""  # seed only: owner/repo to register with the seeded connection
    github_backfill_max_commits: int = 2000
    github_backfill_max_comments: int = 2000  # per PR, issue + review comments (RADD-1261)
    github_api_page_size: int = 100  # GitHub's maximum
    github_http_timeout_seconds: float = 30.0

    # Jira import (radd/modules/jiraimport): SEED-ONLY since spec 100 — one connection row on
    # first start. Empty base URL = nothing to seed.
    jira_base_url: str = ""  # e.g. https://jira.example.com (no trailing /rest)
    # Two auth modes, both supported. A PAT (Bearer) takes precedence when set;
    # otherwise username + password is used (HTTP Basic — Jira DC accepts either).
    jira_pat: str = ""  # Jira DC personal access token — Bearer; read scope is enough
    jira_user: str = ""  # basic-auth username (used when jira_pat is empty)
    jira_password: str = ""  # basic-auth password
    jira_verify_ssl: bool = True  # internal CA / self-signed → set false
    jira_timeout_seconds: float = 30.0
    # Placeholder-email domain for Jira users with hidden emails (spec 88), so a later AD import
    # can adopt them. Empty = derived from the connection's host.
    jira_placeholder_email_domain: str = ""

    # Confluence import (spec 117): SEED-ONLY, like jira_*. Server/DC only.
    confluence_base_url: str = ""  # e.g. https://confluence.example.com
    confluence_pat: str = ""  # personal access token — Bearer; read scope is enough
    confluence_user: str = ""  # basic-auth username (used when the PAT is empty)
    confluence_password: str = ""
    confluence_verify_ssl: bool = True  # internal CA / self-signed → set false
    confluence_timeout_seconds: float = 30.0
    # Same contract as jira_placeholder_email_domain.
    confluence_placeholder_email_domain: str = ""


    # Alertmanager intake (RADD-1317): SEED-ONLY — the token + project key become
    # one receiver row, once, when the table is empty. Receivers are rows after.
    alertmanager_token: str = ""
    alertmanager_project_key: str = ""

    # Email-to-issue intake (see radd/modules/mailintake). Empty host = disabled.
    mail_imap_host: str = ""
    mail_imap_port: int = 993
    mail_imap_username: str = ""
    mail_imap_password: str = ""
    mail_imap_folder: str = "INBOX"
    mail_poll_seconds: float = 60.0
    mail_project_key: str = ""
    # Requester-loop defaults (Settings → Email overrides, RADD-1368). Both OFF: nothing
    # reaches a requester's mailbox unless switched on.
    mail_send_ack: bool = False
    mail_send_resolved: bool = False
    # The receipt's plain-text body. `{{key}}`/`{{title}}`/`{{link}}`/
    # `{{requester_name}}` substitute (`mailintake.service._render_ack_body`);
    # an unset OR blank override sends this wording.
    mail_ack_body: str = (
        "Your request has been received and is being tracked as {{key}}.\n"
        "\n"
        "We'll follow up by email. You can reply to this message to add details "
        "— replies are attached to the ticket automatically (keep [{{key}}] in "
        "the subject)."
    )
    mail_outbound_poll_seconds: float = 5.0
    # HTTPS ingest (RADD-953): the Cloudflare Email Worker's signing secret. EMPTY REJECTS ALL.
    email_ingest_secret: str = ""
    # The address mail is accepted for. Informational for now — it is what the
    # Reply-To on outbound carries, and what a source row will name (RADD-958).
    email_ingest_address: str = ""

    # CSAT (spec 65): `csat_enabled` is the cascade default; surveys are per-project OPT-IN.
    csat_enabled: bool = False
    csat_poll_seconds: float = 5.0
    csat_batch: int = 200  # events read per sender iteration

    # GitLab (radd/modules/gitlab): SEED-ONLY since RADD-1253 — one connection row on first start.
    gitlab_webhook_secret: str = ""  # seed only: the hook's "Secret token"
    gitlab_base_url: str = ""  # seed only: https://gitlab.example.com (default gitlab.com)
    gitlab_api_token: str = ""  # seed only: a read_api token (admin's = automatic author matching)
    gitlab_repo: str = ""  # seed only: group/project to register with the seeded connection
    gitlab_backfill_max_commits: int = 2000
    gitlab_api_page_size: int = 100  # GitLab's maximum
    gitlab_http_timeout_seconds: float = 30.0

    # Manual item ranking (see radd/modules/items) — gap between fractional rank
    # keys on create/rebalance; a wide gap allows many midpoint insertions.
    item_rank_step: float = 1024.0

    # Bulk operations (spec 68) — max items per bulk-update/bulk-move request and
    # the id cap on GET /items/ids ("select all matching").
    bulk_max_items: int = 500

    # Time logging (see radd/modules/timelogging) — a working day/week, not calendar,
    # so Jira-style durations (`1d`, `2w`) convert to seconds consistently everywhere.
    timelog_hours_per_day: int = 8
    timelog_days_per_week: int = 5
    # Timesheet outlier flags: a workday logged outside these
    # bounds is highlighted on the per-person timesheet view.
    timesheet_day_min_hours: int = 6
    timesheet_day_max_hours: int = 10

    # The instance's working week (spec 35): comma-separated day names. Drives
    # work-week-only SLA timers and timesheet display (GET /instance exposes it).
    work_week_days: str = "mon,tue,wed,thu,fri"

    # Workflow transition enforcement (spec 61) — a TransitionMode value
    # (off | guards | strict), overridable per project via the
    # scalar-settings cascade. "off" keeps the feature fully optional.
    workflow_transition_mode: str = "off"

    # Story points (spec 70): the cascade default; per-project OPT-IN.
    estimation_points: bool = False
    # Spec 121: what a new issue is unless the filer says otherwise
    # (public | internal | restricted); the `item_default_visibility` scoped setting.
    item_default_visibility: str = "public"

    # Backups (spec 99, see radd/backup). The artifact is encrypted end-to-end;
    # the key lives on a DIFFERENT volume from the backups by default, so losing
    # one does not lose both. Generated on first use if absent.
    backup_dir: str = "/opt/radd/backups"
    backup_key_file: str = "/data/radd-backup.key"
    backup_encryption: bool = True
    backup_scheduler_interval: float = 60.0
    backup_pg_dump_path: str = "pg_dump"
    backup_pg_restore_path: str = "pg_restore"
    # pg_dump/pg_restore are runtime REQUIREMENTS: a startup pre-flight refuses
    # to boot without them. True downgrades that to a warning (dev boxes).
    backup_tools_optional: bool = False
    backup_compression: str = "gzip:6"  # pg_dump --compress: gzip|lz4|zstd[:level]
    backup_include_attachments_default: bool = True
    backup_retention_keep_last: int = 7
    backup_min_free_bytes: int = 1 << 30
    backup_timeout_seconds: float = 3600.0
    backup_max_upload_bytes: int = 0  # 0 = unlimited (free-space guard still applies)

    # Ordered module assembly — the plugin system's root configuration.
    modules: tuple[str, ...] = (
        "radd.modules.events",
        "radd.modules.projects",
        "radd.modules.auth",
        "radd.modules.capabilities",
        "radd.modules.pluginmgr",
        "radd.modules.settings",
        "radd.modules.groups",
        "radd.modules.teams",
        "radd.modules.access",
        "radd.modules.workflow",
        "radd.modules.labels",
        "radd.modules.fields",
        "radd.modules.cycles",
        "radd.modules.releases",
        "radd.modules.itemtypes",
        "radd.modules.screens",
        "radd.modules.linktypes",
        "radd.modules.items",
        "radd.modules.comments",
        "radd.modules.weblinks",
        "radd.modules.webhooks",
        "radd.modules.views",
        "radd.modules.reporting",
        "radd.modules.forms",
        "radd.modules.automations",
        "radd.modules.timelogging",
        # RADD-1258: vcs mirrors MR/PR time into worklogs, so it loads after timelogging.
        "radd.modules.vcs",
        "radd.modules.audit",
        "radd.modules.backup",
        "radd.modules.notify",
        "radd.modules.realtime",
        "radd.modules.search",
        "radd.modules.attachments",
        "radd.modules.avatars",  # RADD-1295: above attachments (the blob API)
        "radd.modules.canned",
        "radd.modules.slas",
        "radd.modules.gitlab",
        "radd.modules.sso",
        "radd.modules.ldap",
        "radd.modules.pages",
        "radd.modules.collab",
        "radd.modules.ai",
        "radd.modules.mcp",
        "radd.modules.forgejo",
        "radd.modules.github",
        "radd.modules.alertmanager",
        "radd.modules.mailintake",
        "radd.modules.csat",
        "radd.modules.approvals",
        "radd.modules.participants",
        "radd.modules.scripts",  # RADD-1269: core=False, disableable
        "radd.modules.dashboards",
        "radd.modules.jiraimport",
        "radd.modules.confluenceimport",
        "radd.modules.monitoring",
        "radd.modules.leave",
    )
    # Shipped but not bootstrapped: installed + enabled through the plugin manager
    # (docs/plugin-platform.md §10); boot also loads those ENABLED in `installed_plugins`.
    installable_plugins: tuple[str, ...] = ("radd.modules.milestones",)


settings = Settings()
