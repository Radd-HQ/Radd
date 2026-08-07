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
    api_title: str = "Radd"
    api_prefix: str = "/api/v1"
    # Built SPA to serve at / (empty or missing dir = API-only). Default: the repo's web/dist.
    web_dist: str = ""

    # Auth (see radd/modules/auth)
    session_ttl_hours: int = 720
    session_cookie_secure: bool = False  # enable behind HTTPS
    token_last_used_throttle_seconds: int = 60  # min interval between PAT last_used_at writes
    # Staleness bound for module-level snapshots (RADD-899) — capability pills,
    # login-page provider buttons, the default-storage-host mirror. A second web
    # replica converges within this window instead of "until restart".
    snapshot_ttl_seconds: float = 30.0

    # Worker split (spec 48): false = this process serves web only; the
    # background loops (webhooks/automations/notify/search/sla/googlechat/mail)
    # stay dormant. Realtime + storage init always run (they serve the web tier).
    run_workers: bool = True
    # Which task_backend socket provider runs kernel-registered TaskSpecs
    # (RADD-872). "localloop" is the built-in poll-loop runner; a celery-style
    # plugin swaps in by registering another provider under its own name.
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
    # Graph runs (spec 116). A linear rule cost `items x actions`; a graph costs
    # `items x nodes x fan-out`, so a run needs a ceiling on both axes. Hitting
    # either is RECORDED in the run report, never applied in silence — a run that
    # quietly did less is indistinguishable from a run that had less to do.
    automation_graph_max_node_runs: int = 200
    automation_graph_max_item_actions: int = 2000

    # Event-cascade consumer (see radd/modules/events/cascade.py) — events read
    # per iteration when draining kernel-registered cascades.
    event_cascade_batch: int = 50

    # Notifications (see radd/modules/notify)
    notify_poll_interval: float = 1.0
    notify_batch: int = 100
    # Email digests: one batched email per user per interval. Empty smtp_host = disabled.
    notify_email_interval: float = 300.0
    notify_email_max_age_hours: int = 24
    # Per-event mail (RADD-968): the second, FASTER loop that mails the
    # notification rows whose type is in the immediate-email set, so a comment
    # reaches its watchers now rather than at the next digest window. Rows it
    # sends are stamped `emailed_at`, which is what keeps the digest from
    # repeating them.
    notify_mail_poll_interval: float = 5.0
    notify_mail_batch: int = 100
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    # RADD_SMTP_FROM **or** RADD_SMTP_FROM_ADDRESS. The field name implies the
    # latter, every document and the deployment say the former, and for months
    # only the unwritten one was read — so outbound mail went out as
    # `radd@localhost`, which a real relay refuses because it hosts no such
    # mailbox. A wire constant with no compiler behind it: it type-checks
    # nowhere and simply does nothing. Both names work now; the short one is
    # what people actually type.
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

    # Search indexer (see radd/modules/search)
    search_poll_interval: float = 1.0
    search_batch: int = 200

    # Attachments (see radd/modules/attachments). Storage backend: "filesystem"
    # (default; attachments_dir) or "s3" (any S3-compatible store — MinIO, AWS).
    attachment_storage: str = "filesystem"
    attachments_dir: str = "var/attachments"
    attachment_max_bytes: int = 25 * 1024 * 1024
    s3_endpoint: str = "localhost:9000"  # host:port (no scheme; s3_secure picks it)
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "radd-attachments"
    s3_secure: bool = False  # true behind TLS
    s3_presign_expiry_seconds: int = 300

    # SLA engine (see radd/modules/slas) — periodic timer evaluation.
    sla_check_interval: float = 60.0

    # OIDC SSO (see radd/modules/sso). SEED-ONLY since spec 110: providers are
    # `sso_providers` rows managed in Settings → Sign-in, and these values create
    # the first row ONCE, on a database that has none. Editing them later does
    # nothing — change the provider in the UI. Empty issuer = seed nothing.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_auto_provision: bool = True
    # Comma-separated domains allowed to CREATE an account through the seeded
    # provider ("radd-hq.com,example.com"). Empty + auto-provision on seeds the
    # "*" wildcard, preserving spec 40's anyone-at-the-IdP behavior for existing
    # deployments; new providers added in the UI default to an empty list, which
    # means no signups at all.
    oidc_signup_domains: str = ""
    # Groups claim → instance role sync: members of any listed group become
    # instance admins; everyone else joins as member. Re-synced on every login.
    # Leaving admin_groups EMPTY means the provider has no role opinion and
    # leaves instance_role alone (spec 110) — required so a Google login can't
    # demote the AD admin whose account it just linked to.
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
    # Group reconcile loop (spec 84 → RADD-829: GROUPS are the sync surface, not
    # linked teams). Needs the bind account + run_workers; long interval by design.
    ldap_group_sync_seconds: float = 3600.0
    # RADD-829: the nesting walk's depth cap. AD nesting is rarely deeper than 3;
    # a pathological directory degrades to "incomplete" (fails CLOSED — fewer
    # memberships resolved) instead of "down".
    group_nesting_max_depth: int = 10
    # Cap on the error list persisted per sync run in directory_sync_state —
    # the JSONB row is a status line, not a log (group + user sync loops).
    ldap_max_recorded_errors: int = 20
    # Directory settings page + automatic user sync (spec 85). These four are
    # the CASCADE DEFAULTS for the registered instance-scope SettingKeys — an
    # instance override written on the Directory settings page wins over env.
    ldap_group_search_base: str = ""  # "" = base_dn(); narrow to a groups OU
    ldap_user_sync_enabled: bool = False  # the automation switch (off = manual only)
    # Deactivate ldap-source users that vanish from the directory. OFF by
    # default so a transient AD outage can't lock people out.
    ldap_user_sync_deactivate_missing: bool = False
    ldap_user_sync_seconds: float = 3600.0  # ldap-usersync loop interval
    # Exclude directory accounts with the AD ACCOUNTDISABLE bit from imports and
    # sync. ON by default because most of a real directory is leavers — a live
    # instance showed 2057 disabled against 1031 active — and importing them fills
    # the tracker with dead users. Overridable per instance in Settings → Directory.
    ldap_exclude_disabled: bool = True

    # Proxies allowed to speak X-Forwarded-For (comma-separated IPs/CIDRs, e.g.
    # your ingress/LB range). "" = the header is ignored and the socket peer is
    # the client IP. Storage CIDR routing rules (spec 102) depend on this being
    # right behind a proxy. See radd/clientip.py.
    trusted_proxies: str = ""

    # AI layer (see radd/modules/ai). Since spec 101 the ai_provider/base_url/
    # api_key/model quartet is SEED-ONLY: it creates one provider row + the chat
    # role on first boot (like the jira_* block), after which Settings → AI owns
    # the registry. max_tokens/timeouts stay live global tunables.
    ai_provider: str = ""  # "openai" (any OpenAI-compatible base_url) | "anthropic"
    ai_base_url: str = ""  # "" = the provider's default endpoint
    ai_api_key: str = ""
    ai_model: str = ""
    ai_max_tokens: int = 1024
    ai_timeout_seconds: float = 30.0
    ai_stream_timeout_seconds: float = 120.0  # editor-action SSE read timeout
    # Embedding indexer (spec 103): batch handed to one /embeddings call, loop
    # cadence, and the per-entity text cap fed to the model. The embedder loop
    # DRAINS (no sleep between full batches), so the interval only paces the
    # idle poll; the batch amortizes per-call overhead during backfills.
    ai_embed_batch: int = 256
    ai_embedder_poll_interval: float = 3.0
    ai_embed_max_chars: int = 8000
    # Budget for the semantic half of a hybrid search — past it, FTS-only.
    ai_search_timeout_seconds: float = 2.0
    # Spec 116: how much text the automation AI-classifier node may send in one
    # prompt. There is no principled value — the real limit is the configured
    # model's context window, which the provider registry does not record, so
    # this is a deliberately generous default you raise or lower to match yours
    # (~40k characters is roughly 10k tokens, comfortable for an 8k-token model
    # with room for the answer). It is spent on WHOLE items: the digest includes
    # each item entirely or not at all, and names how many it left out, rather
    # than truncating a description mid-sentence and cutting the very line that
    # decides the classification.
    ai_automation_context_chars: int = 40_000
    #: How many items ONE per-item AI classifier node may classify in a single
    #: run. Separate from (and far below) `automation_graph_max_item_actions`
    #: because these are model round trips, not database writes: at roughly a
    #: second each, the action budget of 2000 would park a consumer iteration for
    #: half an hour. Items past the cap take the node's fallback port — routed,
    #: never silently dropped.
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
    ai_summarize: bool = True
    ai_nl_slq: bool = True
    # OFF by default: the rerank buys reasons + rescoring at the
    # price of a chat-model round trip on every similar-issues open.
    ai_similar_rerank: bool = False
    # Deliver summaries / similar-reasons progressively (SSE) instead of
    # complete-then-show.
    ai_stream_responses: bool = True

    # Embedded MCP server (see radd/modules/mcp) — POST {api_prefix}/mcp.
    mcp_enabled: bool = True
    # Spec 114: above this many permitted projects, a tool's project parameter
    # degrades from an enum to a plain string — a 300-entry enum costs the agent
    # more context than the precision buys it.
    mcp_project_enum_max: int = 25
    # RADD-740: how often the tools/list_changed stream re-checks the caller's
    # catalog, and how often it emits a keepalive comment so proxies do not drop
    # an idle connection. Seconds.
    mcp_catalog_poll_seconds: float = 15.0
    mcp_stream_keepalive_seconds: float = 25.0

    # Forgejo/Gitea connector (see radd/modules/forgejo). Spec 111 moved hosts into
    # the database (`forgejo_connections`), so these SEED one connection on first
    # startup and are inert afterwards — the spec-100/101 rule. An existing deploy
    # keeps verifying webhooks across the upgrade; rotation happens in the UI.
    forgejo_webhook_secret: str = ""
    forgejo_base_url: str = ""  # seed only: https://git.example.com
    # Spec 112 cascade defaults (per-project overrides in Settings → Releases).
    release_waiting_state: str = ""
    release_shipped_state: str = ""
    # Backfill bounds (spec 111): how far back the API walk goes by default.
    forgejo_backfill_max_commits: int = 2000
    forgejo_api_page_size: int = 50
    # Per-request bound on Forgejo API calls (connection test + backfill walk).
    forgejo_http_timeout_seconds: float = 30.0

    # Jira import connector (see radd/modules/jiraimport, specs 90/100).
    # Spec 100 moved connections into the database (`jira_connections`), so these
    # now only SEED a default connection on first startup — an existing deploy
    # keeps working, and thereafter connections are managed in the UI with no
    # restart. Empty base URL = nothing to seed.
    jira_base_url: str = ""  # e.g. https://jira.example.com (no trailing /rest)
    # Two auth modes, both supported. A PAT (Bearer) takes precedence when set;
    # otherwise username + password is used (HTTP Basic — Jira DC accepts either).
    jira_pat: str = ""  # Jira DC personal access token — Bearer; read scope is enough
    jira_user: str = ""  # basic-auth username (used when jira_pat is empty)
    jira_password: str = ""  # basic-auth password
    jira_verify_ssl: bool = True  # internal CA / self-signed → set false
    jira_timeout_seconds: float = 30.0
    # Domain used to synthesize an address for a Jira user whose email Jira does
    # not expose, so a later AD import can match on email and adopt the
    # placeholder's work (spec 88). Empty = DERIVE it from the connection's host
    # (jira.example.com -> example.com). Spec 100 replaced a hardcoded
    # company domain in `issuemap.py` with this.
    jira_placeholder_email_domain: str = ""

    # Google Chat notifier (see radd/modules/googlechat). Empty URL = disabled.
    googlechat_webhook_url: str = ""
    googlechat_event_types: str = "item.created,sla.breached,page.created"
    googlechat_poll_interval: float = 2.0
    googlechat_batch: int = 100  # events read per consumer iteration

    # Alertmanager intake (see radd/modules/alertmanager). Empty token = disabled.
    alertmanager_token: str = ""
    alertmanager_project_key: str = ""
    alertmanager_resolve_state: str = ""  # state NAME on alert resolve ("" = none)

    # Email-to-issue intake (see radd/modules/mailintake). Empty host = disabled.
    mail_imap_host: str = ""
    mail_imap_port: int = 993
    mail_imap_username: str = ""
    mail_imap_password: str = ""
    mail_imap_folder: str = "INBOX"
    mail_poll_seconds: float = 60.0
    mail_project_key: str = ""
    # Requester loop (spec 62): acknowledge intake/public-form items that captured
    # a contact (needs smtp_host); the outbound consumer mails public comments back.
    mail_send_ack: bool = True
    mail_outbound_poll_seconds: float = 5.0
    # HTTPS ingest (RADD-953). The shared secret the Cloudflare Email Worker
    # signs each raw message with — `openssl rand -base64 32`. EMPTY REJECTS
    # EVERYTHING, the same safe default as forgejo_webhook_secret: an
    # unauthenticated, internet-reachable endpoint that creates issues is the
    # worst way to discover a missing environment variable.
    email_ingest_secret: str = ""
    # The address mail is accepted for. Informational for now — it is what the
    # Reply-To on outbound carries, and what a source row will name (RADD-958).
    email_ingest_address: str = ""

    # CSAT surveys (see radd/modules/csat, spec 65). `csat_enabled` is the
    # instance default of the SettingKey.CSAT_ENABLED scalar cascade — surveys
    # are per-project OPT-IN, so the default stays off.
    csat_enabled: bool = False
    csat_poll_seconds: float = 5.0
    csat_batch: int = 200  # events read per sender iteration

    # GitLab connector (see radd/modules/gitlab). Empty secret = endpoint disabled.
    gitlab_webhook_secret: str = ""
    # State NAME referenced items move to when their MR merges ("" = no transition).
    gitlab_merge_transition_state: str = ""

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
    # (off | guards | strict), overridable per workspace/project via the
    # scalar-settings cascade. "off" keeps the feature fully optional.
    workflow_transition_mode: str = "off"

    # Story points (spec 70) — the instance default of the
    # SettingKey.ESTIMATION_POINTS scalar cascade. Per-project OPT-IN: a
    # project that hasn't enabled it shows zero points UI anywhere.
    estimation_points: bool = False

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
        "radd.modules.vcs",
        "radd.modules.webhooks",
        "radd.modules.views",
        "radd.modules.reporting",
        "radd.modules.forms",
        "radd.modules.automations",
        "radd.modules.timelogging",
        "radd.modules.audit",
        "radd.modules.backup",
        "radd.modules.notify",
        "radd.modules.realtime",
        "radd.modules.search",
        "radd.modules.attachments",
        "radd.modules.canned",
        "radd.modules.slas",
        "radd.modules.gitlab",
        "radd.modules.sso",
        "radd.modules.ldap",
        "radd.modules.pages",
        "radd.modules.ai",
        "radd.modules.mcp",
        "radd.modules.forgejo",
        "radd.modules.googlechat",
        "radd.modules.alertmanager",
        "radd.modules.mailintake",
        "radd.modules.csat",
        "radd.modules.approvals",
        "radd.modules.participants",
        "radd.modules.dashboards",
        "radd.modules.jiraimport",
        "radd.modules.monitoring",
        "radd.modules.leave",
    )
    # Non-core plugins are INSTALLED + runtime-ENABLED via the plugin manager
    # (docs/plugin-platform.md §10), not the always-on bootstrap set above. These
    # ship in the repo and are discoverable by the manager; `create_app` also loads
    # whichever are in state ENABLED in the `installed_plugins` table.
    installable_plugins: tuple[str, ...] = ("radd.modules.milestones",)


settings = Settings()
