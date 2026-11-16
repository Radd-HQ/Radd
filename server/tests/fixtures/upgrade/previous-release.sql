--
-- PostgreSQL database dump
--

\restrict FXEF3ro8JEr5tKZwZeIw9VE1pL2F2RuZPfWNpSyvwNjBC66QmdTH8mY3ZixFjiI

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 16.14 (Debian 16.14-1.pgdg12+1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;


--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';


--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: access_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_grants (
    id uuid NOT NULL,
    resource_type character varying(40) NOT NULL,
    resource_id character varying(100) NOT NULL,
    subject_type character varying(10) NOT NULL,
    subject_id uuid NOT NULL,
    access character varying(20) NOT NULL,
    project_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    effect character varying(5) DEFAULT 'allow'::character varying NOT NULL,
    expires_at timestamp without time zone,
    granted_by uuid
);


--
-- Name: access_restrictions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.access_restrictions (
    id uuid NOT NULL,
    resource_type character varying(40) NOT NULL,
    resource_id character varying(100) NOT NULL,
    access character varying(20) NOT NULL,
    project_id uuid
);


--
-- Name: ai_model_roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_model_roles (
    role character varying(20) NOT NULL,
    provider_id uuid NOT NULL,
    model character varying(200) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_preset_prompts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_preset_prompts (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    prompt text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: ai_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ai_providers (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    wire_shape character varying(20) NOT NULL,
    base_url character varying(500) NOT NULL,
    api_key text NOT NULL,
    default_model character varying(200) NOT NULL,
    source character varying(10) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    reasoning boolean DEFAULT false NOT NULL,
    request_params jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: alert_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alert_items (
    fingerprint text NOT NULL,
    item_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    receiver_id uuid,
    id uuid DEFAULT gen_random_uuid() NOT NULL
);


--
-- Name: alertmanager_receivers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alertmanager_receivers (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    token text NOT NULL,
    project_id uuid,
    active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    comment_updates boolean DEFAULT false NOT NULL,
    label character varying(100) DEFAULT ''::character varying NOT NULL,
    resolve_state_id uuid
);


--
-- Name: alertmanager_seed; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alertmanager_seed (
    key character varying(40) NOT NULL
);


--
-- Name: api_tokens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.api_tokens (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    token_hash character varying(64) NOT NULL,
    prefix_display character varying(12) NOT NULL,
    expires_at timestamp without time zone,
    last_used_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    scopes jsonb,
    automation_cause jsonb
);


--
-- Name: approval_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_requests (
    id uuid NOT NULL,
    item_id uuid NOT NULL,
    transition_id uuid,
    to_state_id uuid NOT NULL,
    requested_by uuid,
    note text NOT NULL,
    status character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    approvers jsonb DEFAULT '[]'::jsonb NOT NULL
);


--
-- Name: approval_votes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approval_votes (
    id uuid NOT NULL,
    request_id uuid NOT NULL,
    user_id uuid NOT NULL,
    verdict character varying(10) NOT NULL,
    note text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: attachment_move_jobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attachment_move_jobs (
    id uuid NOT NULL,
    source_host_id uuid NOT NULL,
    target_host_id uuid NOT NULL,
    state character varying(20) NOT NULL,
    total integer NOT NULL,
    moved integer NOT NULL,
    failed integer NOT NULL,
    problems jsonb NOT NULL,
    created_by uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone
);


--
-- Name: attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attachments (
    id uuid NOT NULL,
    filename character varying(300) NOT NULL,
    content_type character varying(120) NOT NULL,
    size_bytes bigint NOT NULL,
    storage_name character varying(64) NOT NULL,
    created_by uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id uuid NOT NULL,
    storage_host_id uuid NOT NULL,
    state character varying(10) NOT NULL
);


--
-- Name: automation_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_runs (
    id uuid NOT NULL,
    automation_id uuid NOT NULL,
    trigger_node_id character varying(64) NOT NULL,
    source character varying(16) NOT NULL,
    event_id bigint,
    event_type character varying(100) DEFAULT ''::character varying NOT NULL,
    started_at timestamp without time zone NOT NULL,
    finished_at timestamp without time zone NOT NULL,
    status character varying(16) NOT NULL,
    actor_id uuid,
    item_keys jsonb DEFAULT '[]'::jsonb NOT NULL,
    actions_applied integer DEFAULT 0 NOT NULL,
    actions_skipped integer DEFAULT 0 NOT NULL,
    error text DEFAULT ''::text NOT NULL,
    report jsonb DEFAULT '{}'::jsonb NOT NULL
);


--
-- Name: automation_schedule_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_schedule_state (
    automation_id uuid NOT NULL,
    next_run_at timestamp without time zone NOT NULL,
    last_run_at timestamp without time zone,
    node_id character varying(64) NOT NULL
);


--
-- Name: automation_triggers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_triggers (
    automation_id uuid NOT NULL,
    node_id character varying(64) NOT NULL,
    event_type character varying(100) NOT NULL,
    schedule jsonb,
    include_automated boolean DEFAULT false NOT NULL
);


--
-- Name: automation_validations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_validations (
    automation_id uuid NOT NULL,
    node_id character varying(64) NOT NULL,
    target_kind character varying(16) NOT NULL,
    target_id uuid NOT NULL,
    mode character varying(16) NOT NULL
);


--
-- Name: automation_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automation_versions (
    id uuid NOT NULL,
    automation_id uuid NOT NULL,
    version integer NOT NULL,
    name character varying(200) NOT NULL,
    nodes jsonb DEFAULT '[]'::jsonb NOT NULL,
    edges jsonb DEFAULT '[]'::jsonb NOT NULL,
    orientation character varying(16) DEFAULT 'vertical'::character varying NOT NULL,
    created_by_id uuid,
    created_at timestamp without time zone NOT NULL,
    note text DEFAULT ''::text NOT NULL,
    restored_from integer
);


--
-- Name: automations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.automations (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    enabled boolean NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    nodes jsonb DEFAULT '[]'::jsonb NOT NULL,
    edges jsonb DEFAULT '[]'::jsonb NOT NULL,
    orientation character varying(16) DEFAULT 'vertical'::character varying NOT NULL,
    created_by_id uuid,
    version integer DEFAULT 1 NOT NULL
);


--
-- Name: backup_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backup_runs (
    id uuid NOT NULL,
    kind character varying(20) NOT NULL,
    status character varying(20) NOT NULL,
    stage character varying(30) NOT NULL,
    artifact_name character varying(120),
    size_bytes bigint,
    schedule_id uuid,
    actor_id uuid,
    started_at timestamp without time zone NOT NULL,
    finished_at timestamp without time zone,
    error text,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: backup_schedules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.backup_schedules (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    enabled boolean NOT NULL,
    config json NOT NULL,
    include_attachments boolean NOT NULL,
    keep_last integer,
    keep_days integer,
    next_run_at timestamp without time zone,
    last_run_at timestamp without time zone,
    last_status character varying(20),
    last_error text,
    created_by_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: canned_responses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.canned_responses (
    id uuid NOT NULL,
    title character varying(200) NOT NULL,
    body text NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: card_layout_presets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.card_layout_presets (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    layout jsonb NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: comment_visibility_teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.comment_visibility_teams (
    comment_id uuid NOT NULL,
    team_id uuid NOT NULL
);


--
-- Name: comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.comments (
    id uuid NOT NULL,
    author_id uuid,
    body text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    visibility character varying(10) DEFAULT 'public'::character varying NOT NULL,
    entity_type character varying(30) DEFAULT 'item'::character varying NOT NULL,
    entity_id uuid NOT NULL,
    anchor jsonb,
    resolved_at timestamp without time zone,
    resolved_by uuid,
    parent_comment_id uuid,
    is_thread boolean DEFAULT false NOT NULL,
    origin character varying(20),
    email_signature text
);


--
-- Name: confluence_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_connections (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    base_url character varying(500) NOT NULL,
    auth_mode character varying(20) NOT NULL,
    username character varying(200) NOT NULL,
    credential text NOT NULL,
    verify_ssl boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    source character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: confluence_import_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_import_records (
    id bigint NOT NULL,
    run_id uuid NOT NULL,
    entity_type character varying(40) NOT NULL,
    entity_id character varying(64) NOT NULL,
    action character varying(20) NOT NULL,
    subject character varying(300) NOT NULL,
    before jsonb,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: confluence_import_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.confluence_import_records ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.confluence_import_records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: confluence_pending_refs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_pending_refs (
    id uuid NOT NULL,
    run_id uuid,
    source_page_id uuid NOT NULL,
    external_source character varying(200) NOT NULL,
    target_page_id character varying(64) NOT NULL,
    target_title character varying(500) NOT NULL,
    resolved boolean DEFAULT false NOT NULL
);


--
-- Name: confluence_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_plans (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    snapshot_id uuid NOT NULL,
    mappings jsonb NOT NULL,
    options jsonb NOT NULL,
    provisioned_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: confluence_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_runs (
    id uuid NOT NULL,
    plan_id uuid,
    snapshot_id uuid,
    actor_id uuid,
    kind character varying(20) NOT NULL,
    dry_run boolean DEFAULT false NOT NULL,
    plan_snapshot jsonb NOT NULL,
    external_source character varying(200) NOT NULL,
    stage character varying(30) NOT NULL,
    counts jsonb NOT NULL,
    problems jsonb NOT NULL,
    report jsonb NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone
);


--
-- Name: confluence_snapshot_attachments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_snapshot_attachments (
    snapshot_id uuid NOT NULL,
    attachment_id character varying(64) NOT NULL,
    page_id character varying(64) NOT NULL,
    filename character varying(500) NOT NULL,
    content_type character varying(200) NOT NULL,
    size_bytes bigint NOT NULL,
    download_path character varying(1000) NOT NULL,
    file_path character varying(1000) DEFAULT ''::character varying NOT NULL
);


--
-- Name: confluence_snapshot_comments; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_snapshot_comments (
    snapshot_id uuid NOT NULL,
    comment_id character varying(64) NOT NULL,
    page_id character varying(64) NOT NULL,
    parent_comment_id character varying(64),
    body text NOT NULL,
    author character varying(200) NOT NULL,
    author_email character varying(320) NOT NULL,
    created_at character varying(64) NOT NULL,
    anchor jsonb
);


--
-- Name: confluence_snapshot_pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_snapshot_pages (
    snapshot_id uuid NOT NULL,
    page_id character varying(64) NOT NULL,
    space_key character varying(100) NOT NULL,
    parent_id character varying(64),
    title character varying(500) NOT NULL,
    "position" integer NOT NULL,
    version integer NOT NULL,
    body text NOT NULL,
    payload jsonb NOT NULL,
    versions jsonb NOT NULL,
    restrictions jsonb NOT NULL,
    labels jsonb NOT NULL
);


--
-- Name: confluence_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.confluence_snapshots (
    id uuid NOT NULL,
    connection_id uuid,
    actor_id uuid,
    name character varying(200) NOT NULL,
    scope jsonb NOT NULL,
    external_source character varying(200) NOT NULL,
    base_url character varying(500) NOT NULL,
    include_history boolean DEFAULT false NOT NULL,
    history_limit integer,
    include_attachments boolean NOT NULL,
    include_comments boolean NOT NULL,
    stage character varying(30) NOT NULL,
    counts jsonb NOT NULL,
    problems jsonb NOT NULL,
    catalogs jsonb NOT NULL,
    page_count integer NOT NULL,
    byte_size bigint NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone
);


--
-- Name: consumer_offsets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.consumer_offsets (
    name character varying(100) NOT NULL,
    last_event_id bigint NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: csat_surveys; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.csat_surveys (
    id uuid NOT NULL,
    item_id uuid NOT NULL,
    token character varying(64) NOT NULL,
    rating smallint,
    comment text NOT NULL,
    sent_at timestamp without time zone NOT NULL,
    responded_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: cycle_series; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cycle_series (
    id uuid NOT NULL,
    label character varying(180) NOT NULL,
    drafts_ahead integer NOT NULL,
    next_number integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    start_weekday integer,
    duration_days integer
);


--
-- Name: cycle_teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cycle_teams (
    cycle_id uuid NOT NULL,
    team_id uuid NOT NULL
);


--
-- Name: cycles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cycles (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    start_date date,
    end_date date,
    goal text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    completed_at timestamp without time zone,
    project_id uuid
);


--
-- Name: dashboard_widgets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dashboard_widgets (
    id uuid NOT NULL,
    dashboard_id uuid NOT NULL,
    widget_type character varying(30) NOT NULL,
    title character varying(200),
    width integer NOT NULL,
    "position" integer NOT NULL,
    config jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    height integer DEFAULT 360 NOT NULL,
    collapsed boolean DEFAULT false NOT NULL
);


--
-- Name: dashboards; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.dashboards (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    description text NOT NULL,
    owner_id uuid,
    global_access character varying(10),
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: directory_sync_state; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.directory_sync_state (
    kind character varying(20) NOT NULL,
    last_run_at timestamp without time zone NOT NULL,
    last_result jsonb NOT NULL
);


--
-- Name: events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.events (
    id bigint NOT NULL,
    event_type character varying(100) NOT NULL,
    entity_type character varying(50) NOT NULL,
    entity_id character varying(64) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    actor_id uuid,
    silent boolean DEFAULT false NOT NULL,
    automated boolean DEFAULT false NOT NULL,
    project_id uuid,
    entity_label character varying(300),
    search_text text,
    automation_rule_id uuid,
    automation_depth smallint DEFAULT '0'::smallint NOT NULL
);


--
-- Name: events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.events ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: field_definition_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.field_definition_projects (
    field_id uuid NOT NULL,
    project_id uuid NOT NULL
);


--
-- Name: field_definitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.field_definitions (
    id uuid NOT NULL,
    key character varying(50) NOT NULL,
    name character varying(200) NOT NULL,
    type character varying(20) NOT NULL,
    required boolean NOT NULL,
    options jsonb,
    indexed boolean NOT NULL,
    ai_visible boolean NOT NULL,
    source character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    display character varying(20),
    default_value jsonb
);


--
-- Name: forgejo_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forgejo_connections (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    base_url character varying(500) NOT NULL,
    api_token text NOT NULL,
    webhook_secret text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    verify_ssl boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: forgejo_repos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forgejo_repos (
    id uuid NOT NULL,
    connection_id uuid NOT NULL,
    full_name character varying(300) NOT NULL,
    project_id uuid,
    default_branch character varying(200) NOT NULL,
    last_backfill_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    time_category_id uuid,
    mirror_time boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    link_all_projects boolean DEFAULT true NOT NULL,
    move_on_merge boolean DEFAULT false NOT NULL,
    publish_on_release boolean DEFAULT false NOT NULL
);


--
-- Name: form_shares; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.form_shares (
    id uuid NOT NULL,
    form_id uuid NOT NULL,
    user_id uuid,
    team_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_form_shares_one_subject CHECK (((user_id IS NULL) <> (team_id IS NULL)))
);


--
-- Name: forms; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forms (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    description text NOT NULL,
    enabled boolean NOT NULL,
    fields jsonb NOT NULL,
    defaults jsonb NOT NULL,
    title_prompt character varying(200) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    allow_public boolean DEFAULT false NOT NULL,
    description_enabled boolean DEFAULT true NOT NULL,
    description_prompt character varying(200) DEFAULT 'Description'::character varying NOT NULL,
    description_required boolean DEFAULT false NOT NULL,
    team_picker_enabled boolean DEFAULT false NOT NULL
);


--
-- Name: github_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.github_connections (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    base_url character varying(500) NOT NULL,
    api_token text NOT NULL,
    webhook_secret text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    verify_ssl boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: github_repos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.github_repos (
    id uuid NOT NULL,
    connection_id uuid NOT NULL,
    full_name character varying(300) NOT NULL,
    project_id uuid,
    default_branch character varying(200) NOT NULL,
    last_backfill_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    time_category_id uuid,
    mirror_time boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    link_all_projects boolean DEFAULT true NOT NULL,
    move_on_merge boolean DEFAULT false NOT NULL,
    publish_on_release boolean DEFAULT false NOT NULL
);


--
-- Name: gitlab_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gitlab_connections (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    base_url character varying(500) NOT NULL,
    api_token text NOT NULL,
    webhook_secret text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    verify_ssl boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: gitlab_repos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.gitlab_repos (
    id uuid NOT NULL,
    connection_id uuid NOT NULL,
    full_name character varying(300) NOT NULL,
    project_id uuid,
    default_branch character varying(200) NOT NULL,
    last_backfill_at timestamp without time zone,
    time_category_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    mirror_time boolean DEFAULT false NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    link_all_projects boolean DEFAULT true NOT NULL,
    move_on_merge boolean DEFAULT false NOT NULL,
    publish_on_release boolean DEFAULT false NOT NULL
);


--
-- Name: global_role_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.global_role_grants (
    id uuid NOT NULL,
    role_id uuid NOT NULL,
    user_id uuid,
    team_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    project_id uuid,
    space_id uuid,
    group_id uuid,
    expires_at timestamp without time zone,
    granted_by uuid,
    CONSTRAINT ck_global_role_grants_ck_global_role_grants_one_scope CHECK (((project_id IS NULL) OR (space_id IS NULL))),
    CONSTRAINT ck_global_role_grants_ck_global_role_grants_one_subject CHECK ((num_nonnulls(user_id, team_id, group_id) = 1))
);


--
-- Name: group_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.group_members (
    group_id uuid NOT NULL,
    user_id uuid NOT NULL
);


--
-- Name: group_parents; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.group_parents (
    child_id uuid NOT NULL,
    parent_id uuid NOT NULL
);


--
-- Name: groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.groups (
    id uuid NOT NULL,
    dn text NOT NULL,
    name character varying(200) NOT NULL,
    directory_missing_since timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: installed_plugins; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.installed_plugins (
    id character varying(200) NOT NULL,
    version character varying(50) NOT NULL,
    state character varying(20) NOT NULL,
    config json NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: issue_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.issue_types (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    color character varying(7) NOT NULL,
    icon character varying(40),
    "position" integer NOT NULL,
    is_default boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    description_template text
);


--
-- Name: item_cycle_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_cycle_records (
    id uuid NOT NULL,
    item_id uuid NOT NULL,
    cycle_id uuid NOT NULL,
    added_at timestamp without time zone NOT NULL,
    removed_at timestamp without time zone
);


--
-- Name: item_estimates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_estimates (
    item_id uuid NOT NULL,
    original_estimate_seconds integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: item_key_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_key_aliases (
    old_key character varying(60) NOT NULL,
    item_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: item_labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_labels (
    item_id uuid NOT NULL,
    label_id uuid NOT NULL
);


--
-- Name: item_link_type_projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_link_type_projects (
    link_type_id uuid NOT NULL,
    project_id uuid NOT NULL
);


--
-- Name: item_link_types; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_link_types (
    id uuid NOT NULL,
    key character varying(30) NOT NULL,
    name character varying(60) NOT NULL,
    outward_name character varying(60) NOT NULL,
    inward_name character varying(60) NOT NULL,
    direction character varying(20) NOT NULL,
    system boolean NOT NULL,
    auto_managed boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: item_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_links (
    id uuid NOT NULL,
    source_item_id uuid NOT NULL,
    target_item_id uuid NOT NULL,
    link_type character varying(20) NOT NULL
);


--
-- Name: item_page_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_page_links (
    item_id uuid NOT NULL,
    page_id uuid NOT NULL,
    created_by uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    derived boolean DEFAULT false NOT NULL
);


--
-- Name: item_participants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_participants (
    id uuid NOT NULL,
    item_id uuid NOT NULL,
    user_id uuid,
    team_id uuid,
    added_by uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ck_item_participants_one_subject CHECK (((user_id IS NULL) <> (team_id IS NULL)))
);


--
-- Name: item_stars; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_stars (
    user_id uuid NOT NULL,
    item_id uuid NOT NULL
);


--
-- Name: item_vcs_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_vcs_links (
    id uuid NOT NULL,
    item_id uuid NOT NULL,
    ref_type character varying(20) NOT NULL,
    provider character varying(20) NOT NULL,
    title character varying(300) NOT NULL,
    url character varying(2000) NOT NULL,
    status character varying(40) NOT NULL,
    external_id character varying(200) NOT NULL,
    created_by uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    ci_state character varying(20) DEFAULT ''::character varying NOT NULL,
    ci_url character varying(2000) DEFAULT ''::character varying NOT NULL,
    ci_updated_at timestamp without time zone,
    ci_run_id bigint,
    ci_source_updated_at timestamp without time zone,
    connection_id uuid,
    ci_reports jsonb DEFAULT '{}'::jsonb NOT NULL,
    ci_head_sha character varying(100) DEFAULT ''::character varying NOT NULL,
    ci_head_started_at timestamp without time zone
);


--
-- Name: item_watchers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_watchers (
    item_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: item_web_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.item_web_links (
    id uuid NOT NULL,
    item_id uuid NOT NULL,
    url character varying(2000) NOT NULL,
    title character varying(300) NOT NULL,
    category character varying(20) NOT NULL,
    created_by uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: jira_connections; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_connections (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    base_url character varying(500) NOT NULL,
    auth_mode character varying(20) NOT NULL,
    username character varying(200) NOT NULL,
    credential text NOT NULL,
    verify_ssl boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    source character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: jira_import_records; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_import_records (
    id bigint NOT NULL,
    run_id uuid NOT NULL,
    entity_type character varying(40) NOT NULL,
    entity_id character varying(64) NOT NULL,
    action character varying(10) NOT NULL,
    subject character varying(200) NOT NULL,
    before jsonb NOT NULL,
    is_schema boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: jira_import_records_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.jira_import_records ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.jira_import_records_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: jira_pending_refs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_pending_refs (
    id uuid NOT NULL,
    run_id uuid,
    source_item_id uuid NOT NULL,
    kind character varying(20) NOT NULL,
    target_jira_key character varying(100) NOT NULL,
    link_type character varying(30) NOT NULL,
    inward boolean DEFAULT false NOT NULL,
    web_link_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: jira_plans; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_plans (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    snapshot_id uuid NOT NULL,
    radd_project_id uuid,
    radd_project_key character varying(20) NOT NULL,
    radd_project_name character varying(200) NOT NULL,
    mappings jsonb NOT NULL,
    options jsonb NOT NULL,
    provisioned_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: jira_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_runs (
    id uuid NOT NULL,
    plan_id uuid,
    snapshot_id uuid,
    actor_id uuid,
    project_id uuid,
    kind character varying(20) NOT NULL,
    dry_run boolean DEFAULT false NOT NULL,
    plan_snapshot jsonb NOT NULL,
    stage character varying(20) NOT NULL,
    counts jsonb NOT NULL,
    problems jsonb NOT NULL,
    report jsonb NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: jira_snapshot_blobs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_snapshot_blobs (
    snapshot_id uuid NOT NULL,
    jira_attachment_id character varying(30) NOT NULL,
    jira_key character varying(100) NOT NULL,
    storage_name character varying(64) NOT NULL,
    filename character varying(300) NOT NULL,
    content_type character varying(120) NOT NULL,
    size_bytes bigint NOT NULL,
    storage_host_id uuid
);


--
-- Name: jira_snapshot_issues; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_snapshot_issues (
    snapshot_id uuid NOT NULL,
    jira_key character varying(100) NOT NULL,
    jira_id character varying(30) NOT NULL,
    jira_updated_at timestamp without time zone,
    payload jsonb NOT NULL
);


--
-- Name: jira_snapshots; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.jira_snapshots (
    id uuid NOT NULL,
    connection_id uuid,
    actor_id uuid,
    name character varying(200) NOT NULL,
    jira_project_key character varying(100) NOT NULL,
    jql text NOT NULL,
    include_attachments boolean DEFAULT false NOT NULL,
    include_history boolean DEFAULT false NOT NULL,
    stage character varying(20) NOT NULL,
    counts jsonb NOT NULL,
    problems jsonb NOT NULL,
    catalogs jsonb NOT NULL,
    issue_count integer NOT NULL,
    byte_size bigint NOT NULL,
    started_at timestamp without time zone,
    finished_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.labels (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    color character varying(7),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: leave_periods; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.leave_periods (
    id uuid NOT NULL,
    user_id uuid,
    team_id uuid,
    kind character varying(20) NOT NULL,
    label character varying(200) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    created_by uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    start_time time without time zone,
    end_time time without time zone,
    timezone character varying(64) DEFAULT ''::character varying NOT NULL,
    CONSTRAINT ck_leave_periods_ck_leave_dates_ordered CHECK (((start_date < end_date) OR ((start_date = end_date) AND ((start_time IS NULL) OR (end_time IS NULL) OR (start_time < end_time))))),
    CONSTRAINT ck_leave_periods_ck_leave_holiday_all_day CHECK (((team_id IS NULL) OR ((start_time IS NULL) AND (end_time IS NULL)))),
    CONSTRAINT ck_leave_periods_ck_leave_one_subject CHECK (((user_id IS NULL) <> (team_id IS NULL)))
);


--
-- Name: mail_contacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mail_contacts (
    item_id uuid NOT NULL,
    email character varying(320) NOT NULL,
    name character varying(200) NOT NULL,
    last_message_id character varying(998),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    id uuid NOT NULL,
    is_primary boolean DEFAULT false NOT NULL
);


--
-- Name: mail_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mail_messages (
    id uuid NOT NULL,
    message_id character varying(998) NOT NULL,
    item_id uuid NOT NULL,
    comment_id uuid,
    direction character varying(16) NOT NULL,
    subject character varying(998) DEFAULT ''::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    source_id uuid,
    raw_storage_name character varying(255),
    raw_host_id uuid,
    raw_size_bytes integer
);


--
-- Name: mail_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mail_rules (
    id uuid NOT NULL,
    source_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    rule_type character varying(32) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    "position" double precision DEFAULT '0'::double precision NOT NULL,
    config jsonb DEFAULT '{}'::jsonb NOT NULL,
    project_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: mail_senders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mail_senders (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    kind character varying(32) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    from_address character varying(320) DEFAULT ''::character varying NOT NULL,
    reply_to character varying(320) DEFAULT ''::character varying NOT NULL,
    host character varying(255) DEFAULT ''::character varying NOT NULL,
    port integer DEFAULT 587 NOT NULL,
    username character varying(320) DEFAULT ''::character varying NOT NULL,
    secret text DEFAULT ''::text NOT NULL,
    starttls boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: mail_signature_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mail_signature_settings (
    id integer NOT NULL,
    rules jsonb NOT NULL
);


--
-- Name: mail_signature_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.mail_signature_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: mail_signature_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.mail_signature_settings_id_seq OWNED BY public.mail_signature_settings.id;


--
-- Name: mail_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mail_sources (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    kind character varying(32) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    address character varying(320) DEFAULT ''::character varying NOT NULL,
    secret text DEFAULT ''::text NOT NULL,
    host character varying(255) DEFAULT ''::character varying NOT NULL,
    port integer DEFAULT 993 NOT NULL,
    username character varying(320) DEFAULT ''::character varying NOT NULL,
    folder character varying(120) DEFAULT 'INBOX'::character varying NOT NULL,
    default_project_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    sender_id uuid,
    trusted_authserv_id character varying(255)
);


--
-- Name: mfa_enrollment_tickets; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.mfa_enrollment_tickets (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    used_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: milestones; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.milestones (
    id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    project_id uuid NOT NULL,
    title character varying(255) NOT NULL,
    description text,
    due_on date,
    status character varying(255) NOT NULL
);


--
-- Name: notification_prefs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_prefs (
    user_id uuid NOT NULL,
    email_digest boolean NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: notification_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_rules (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    scope character varying(20) NOT NULL,
    scope_id uuid,
    channels jsonb NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: notifications; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notifications (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    event_id bigint,
    type character varying(30) NOT NULL,
    item_id uuid,
    actor_id uuid,
    payload jsonb NOT NULL,
    read_at timestamp without time zone,
    emailed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    email_attempts integer DEFAULT 0 NOT NULL,
    email_next_try timestamp without time zone,
    inbox boolean DEFAULT true NOT NULL,
    email boolean DEFAULT false NOT NULL,
    delivery character varying(20) DEFAULT 'pending'::character varying NOT NULL
);


--
-- Name: page_collab_docs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_collab_docs (
    page_id uuid NOT NULL,
    state bytea NOT NULL,
    page_version integer NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: page_labels; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_labels (
    page_id uuid NOT NULL,
    label_id uuid NOT NULL
);


--
-- Name: page_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_links (
    source_page_id uuid NOT NULL,
    target_page_id uuid NOT NULL
);


--
-- Name: page_path_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_path_history (
    id uuid NOT NULL,
    page_id uuid NOT NULL,
    space_id uuid NOT NULL,
    path text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: page_spaces; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_spaces (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    slug character varying(100) NOT NULL,
    description text NOT NULL,
    "position" double precision DEFAULT '0'::double precision NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    external_source character varying(200) DEFAULT ''::character varying NOT NULL,
    external_id character varying(200) DEFAULT ''::character varying NOT NULL
);


--
-- Name: page_templates; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_templates (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    icon character varying(40) DEFAULT ''::character varying NOT NULL,
    body text DEFAULT ''::text NOT NULL,
    space_id uuid,
    created_by uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: page_versions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_versions (
    id uuid NOT NULL,
    page_id uuid NOT NULL,
    version integer NOT NULL,
    title character varying(500) NOT NULL,
    body text NOT NULL,
    author_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: page_watchers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.page_watchers (
    page_id uuid NOT NULL,
    user_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: pages_number_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pages_number_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pages (
    id uuid NOT NULL,
    space_id uuid NOT NULL,
    parent_id uuid,
    title character varying(500) NOT NULL,
    body text NOT NULL,
    "position" double precision DEFAULT '0'::double precision NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    created_by uuid NOT NULL,
    updated_by uuid NOT NULL,
    archived_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    slug character varying(120) NOT NULL,
    external_source character varying(200) DEFAULT ''::character varying NOT NULL,
    external_id character varying(200) DEFAULT ''::character varying NOT NULL,
    number bigint DEFAULT nextval('public.pages_number_seq'::regclass) NOT NULL
);


--
-- Name: plugin_processes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.plugin_processes (
    process_id character varying(200) NOT NULL,
    report json NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


--
-- Name: project_timelogging; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.project_timelogging (
    project_id uuid NOT NULL,
    enabled boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: projects; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.projects (
    id uuid NOT NULL,
    key character varying(10) NOT NULL,
    name character varying(200) NOT NULL,
    next_number integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    description text DEFAULT ''::text NOT NULL
);


--
-- Name: releases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.releases (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    version character varying(100) NOT NULL,
    status character varying(20) NOT NULL,
    released_at timestamp without time zone,
    description text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: roles; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.roles (
    id uuid NOT NULL,
    key character varying(100) NOT NULL,
    name character varying(200) NOT NULL,
    description character varying(500) NOT NULL,
    permissions jsonb NOT NULL,
    is_builtin boolean NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: scoped_settings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.scoped_settings (
    id uuid NOT NULL,
    scope character varying(20) NOT NULL,
    scope_id uuid,
    key character varying(64) NOT NULL,
    value jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: screen_fields; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screen_fields (
    id uuid NOT NULL,
    screen_id uuid NOT NULL,
    field character varying(60) NOT NULL,
    placement character varying(10) NOT NULL,
    "position" integer NOT NULL
);


--
-- Name: screens; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.screens (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    issue_type_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: script_interpreter; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.script_interpreter (
    id integer NOT NULL,
    python_version character varying(20) DEFAULT '3.12'::character varying NOT NULL,
    status character varying(16) DEFAULT 'missing'::character varying NOT NULL,
    resolved character varying(100) DEFAULT ''::character varying NOT NULL,
    log text DEFAULT ''::text NOT NULL,
    built_at timestamp without time zone,
    index_url character varying(500) DEFAULT ''::character varying NOT NULL,
    offline boolean DEFAULT false NOT NULL
);


--
-- Name: script_interpreter_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.script_interpreter_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: script_interpreter_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.script_interpreter_id_seq OWNED BY public.script_interpreter.id;


--
-- Name: script_packages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.script_packages (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    spec character varying(300) NOT NULL,
    resolved_version character varying(100) DEFAULT ''::character varying NOT NULL,
    status character varying(16) DEFAULT 'pending'::character varying NOT NULL,
    log text DEFAULT ''::text NOT NULL,
    created_at timestamp without time zone NOT NULL,
    installed_at timestamp without time zone
);


--
-- Name: search_index; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.search_index (
    item_id uuid NOT NULL,
    project_id uuid NOT NULL,
    key character varying(30) NOT NULL,
    title character varying(500) NOT NULL,
    description text NOT NULL,
    comments_text text NOT NULL,
    tsv tsvector,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    reporter_id uuid,
    assignee_id uuid,
    team_id uuid,
    visibility character varying(20) DEFAULT 'public'::character varying NOT NULL
);


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    view_as_user_id uuid
);


--
-- Name: sla_item_states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sla_item_states (
    item_id uuid NOT NULL,
    policy_id uuid NOT NULL,
    response_due_at timestamp without time zone,
    response_met_at timestamp without time zone,
    response_breached_at timestamp without time zone,
    resolution_due_at timestamp without time zone,
    resolution_met_at timestamp without time zone,
    resolution_breached_at timestamp without time zone,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    warned_response_at timestamp without time zone,
    warned_resolution_at timestamp without time zone
);


--
-- Name: sla_policies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sla_policies (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    enabled boolean NOT NULL,
    response_minutes integer,
    resolution_minutes integer,
    pause_state_names jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    work_week_only boolean DEFAULT false NOT NULL,
    priorities jsonb DEFAULT '[]'::jsonb NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    business_start_minute integer,
    business_end_minute integer,
    warning_minutes integer,
    issue_type_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    reporter_team_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    response_state_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    response_team_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    resolution_state_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    resolution_team_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    response_met_on character varying(32) DEFAULT 'first_reply'::character varying NOT NULL,
    resolution_met_on character varying(32) DEFAULT 'done'::character varying NOT NULL
);


--
-- Name: sso_provider_default_grants; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sso_provider_default_grants (
    id uuid NOT NULL,
    role_id uuid NOT NULL,
    project_id uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    rule_id uuid NOT NULL
);


--
-- Name: sso_provider_default_teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sso_provider_default_teams (
    id uuid NOT NULL,
    team_id uuid NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    rule_id uuid NOT NULL
);


--
-- Name: sso_providers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sso_providers (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    kind character varying(20) NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    "position" integer NOT NULL,
    issuer character varying(500) NOT NULL,
    client_id character varying(500) NOT NULL,
    client_secret text NOT NULL,
    scopes character varying(500) NOT NULL,
    auto_provision boolean DEFAULT true NOT NULL,
    allowed_signup_domains jsonb DEFAULT '[]'::jsonb NOT NULL,
    require_verified_email boolean DEFAULT true NOT NULL,
    group_claim character varying(100) NOT NULL,
    admin_groups character varying(1000) NOT NULL,
    source character varying(10) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: sso_provisioning_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sso_provisioning_rules (
    id uuid NOT NULL,
    provider_id uuid NOT NULL,
    name character varying(200) DEFAULT ''::character varying NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    domains jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: state_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.state_categories (
    id uuid NOT NULL,
    key character varying(60) NOT NULL,
    name character varying(100) NOT NULL,
    color character varying(20),
    "position" integer NOT NULL,
    behaves_as character varying(20) NOT NULL,
    is_builtin boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: states; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.states (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    category character varying(20) NOT NULL,
    "position" integer NOT NULL,
    is_default boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    category_key character varying(60) NOT NULL
);


--
-- Name: storage_hosts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storage_hosts (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    host_type character varying(20) NOT NULL,
    endpoint character varying(500) NOT NULL,
    access_key text NOT NULL,
    secret_key text NOT NULL,
    bucket character varying(200) NOT NULL,
    region character varying(100) NOT NULL,
    secure boolean DEFAULT false NOT NULL,
    root_dir character varying(500) NOT NULL,
    delivery_mode character varying(20) NOT NULL,
    presign_expiry_seconds integer,
    user_selectable boolean DEFAULT false NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    source character varying(10) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    email_images_allowed boolean DEFAULT false NOT NULL
);


--
-- Name: storage_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.storage_rules (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    rule_type character varying(20) NOT NULL,
    "position" integer NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    config jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: team_assignment_cursors; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_assignment_cursors (
    team_id uuid NOT NULL,
    last_assigned_user_id uuid
);


--
-- Name: team_managers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_managers (
    team_id uuid NOT NULL,
    user_id uuid NOT NULL
);


--
-- Name: team_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.team_members (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    team_id uuid NOT NULL,
    user_id uuid,
    group_id uuid,
    CONSTRAINT ck_team_members_ck_team_members_one_subject CHECK (((user_id IS NULL) <> (group_id IS NULL)))
);


--
-- Name: teams; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.teams (
    id uuid NOT NULL,
    name character varying(200) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    owner_id uuid
);


--
-- Name: thread_resolution_rules; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.thread_resolution_rules (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    issue_type_id uuid,
    resolvers character varying(16) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: totp_recovery_codes; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.totp_recovery_codes (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    code_hash character varying(64) NOT NULL,
    used_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_identities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_identities (
    id uuid NOT NULL,
    provider_id uuid NOT NULL,
    user_id uuid NOT NULL,
    subject character varying(255) NOT NULL,
    email character varying(320) NOT NULL,
    claims jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: user_totp; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_totp (
    user_id uuid NOT NULL,
    secret text NOT NULL,
    confirmed_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying(320) NOT NULL,
    name character varying(200) NOT NULL,
    password_hash character varying(255),
    instance_role character varying(20) NOT NULL,
    active boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    avatar_color character varying(7),
    avatar_emoji character varying(16),
    timezone character varying(64) DEFAULT ''::character varying NOT NULL,
    source character varying(20) DEFAULT 'local'::character varying NOT NULL,
    last_login_at timestamp without time zone,
    preferences jsonb DEFAULT '{}'::jsonb NOT NULL,
    avatar_blob character varying(64),
    avatar_blob_host_id uuid,
    avatar_idp_url character varying(1024)
);


--
-- Name: vcs_deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vcs_deliveries (
    provider character varying(20) NOT NULL,
    connection_id uuid NOT NULL,
    digest character varying(64) NOT NULL
);


--
-- Name: vcs_pending_worklogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vcs_pending_worklogs (
    id uuid NOT NULL,
    provider character varying(20) NOT NULL,
    connection_id uuid NOT NULL,
    external_scope character varying(512) NOT NULL,
    external_id character varying(512) NOT NULL,
    external_username character varying(200) NOT NULL,
    external_email character varying(320) DEFAULT ''::character varying NOT NULL,
    item_id uuid NOT NULL,
    category_id uuid,
    worked_on date NOT NULL,
    time_spent_seconds integer NOT NULL,
    note text DEFAULT ''::text NOT NULL,
    last_seen_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: vcs_seeds; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vcs_seeds (
    provider character varying(20) NOT NULL
);


--
-- Name: vcs_user_links; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.vcs_user_links (
    id uuid NOT NULL,
    provider character varying(20) NOT NULL,
    connection_id uuid NOT NULL,
    external_username character varying(200) NOT NULL,
    user_id uuid NOT NULL,
    matched_by character varying(20) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: view_members; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.view_members (
    view_id uuid NOT NULL,
    item_id uuid NOT NULL,
    "position" integer NOT NULL,
    added_by uuid,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: views; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.views (
    id uuid NOT NULL,
    project_id uuid,
    name character varying(100) NOT NULL,
    view_type character varying(20) NOT NULL,
    group_by text,
    owner_id uuid,
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    query text DEFAULT ''::text NOT NULL,
    swimlane_by text,
    cycle_filter text,
    quick_filters jsonb DEFAULT '[]'::jsonb NOT NULL,
    global_access character varying(10),
    wip_limits jsonb,
    columns jsonb,
    card_layout jsonb,
    column_order jsonb,
    swimlane_order jsonb,
    collapse_empty_columns boolean DEFAULT false NOT NULL,
    hidden_columns jsonb
);


--
-- Name: webhook_deliveries; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_deliveries (
    id uuid NOT NULL,
    endpoint_id uuid NOT NULL,
    event_id bigint NOT NULL,
    status character varying(10) NOT NULL,
    attempts integer NOT NULL,
    next_attempt_at timestamp without time zone NOT NULL,
    last_status_code integer,
    last_error character varying(500),
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: webhook_endpoints; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.webhook_endpoints (
    id uuid NOT NULL,
    url character varying(1000) NOT NULL,
    secret text NOT NULL,
    description character varying(500) NOT NULL,
    event_types jsonb,
    active boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: work_categories; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_categories (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    "position" integer NOT NULL,
    archived boolean NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


--
-- Name: work_items; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.work_items (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    number integer NOT NULL,
    title character varying(500) NOT NULL,
    description text NOT NULL,
    priority character varying(20) NOT NULL,
    custom_fields jsonb NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    state_id uuid NOT NULL,
    kind character varying(20) DEFAULT 'issue'::character varying NOT NULL,
    parent_id uuid,
    assignee_id uuid,
    team_id uuid,
    start_date date,
    target_date date,
    cycle_id uuid,
    release_id uuid,
    flagged boolean DEFAULT false NOT NULL,
    rank double precision DEFAULT '0'::double precision NOT NULL,
    reporter_id uuid,
    archived_at timestamp without time zone,
    type_id uuid,
    estimate_points numeric(6,1),
    visibility character varying(20) DEFAULT 'public'::character varying NOT NULL,
    email_signature text
);


--
-- Name: workflow_transitions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_transitions (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    from_state_id uuid,
    to_state_id uuid NOT NULL,
    rules jsonb NOT NULL,
    "position" integer NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    applies_when jsonb DEFAULT '[]'::jsonb NOT NULL,
    on_release boolean DEFAULT false NOT NULL
);


--
-- Name: worklogs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.worklogs (
    id uuid NOT NULL,
    item_id uuid,
    author_id uuid NOT NULL,
    category_id uuid,
    worked_on date NOT NULL,
    time_spent_seconds integer NOT NULL,
    note text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    project_id uuid,
    external_source character varying(20) DEFAULT ''::character varying NOT NULL,
    external_scope character varying(512) DEFAULT ''::character varying NOT NULL,
    external_id character varying(512) DEFAULT ''::character varying NOT NULL,
    CONSTRAINT ck_worklogs_ck_worklogs_scope CHECK (((item_id IS NOT NULL) OR (category_id IS NOT NULL)))
);


--
-- Name: mail_signature_settings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_signature_settings ALTER COLUMN id SET DEFAULT nextval('public.mail_signature_settings_id_seq'::regclass);


--
-- Name: script_interpreter id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.script_interpreter ALTER COLUMN id SET DEFAULT nextval('public.script_interpreter_id_seq'::regclass);


--
-- Data for Name: access_grants; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: access_restrictions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: ai_model_roles; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: ai_preset_prompts; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: ai_providers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.alembic_version VALUES ('d1499svcauto');


--
-- Data for Name: alert_items; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: alertmanager_receivers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: alertmanager_seed; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: api_tokens; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: approval_requests; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: approval_votes; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: attachment_move_jobs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: attachments; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: automation_runs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: automation_schedule_state; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: automation_triggers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: automation_validations; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: automation_versions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: automations; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: backup_runs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: backup_schedules; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: canned_responses; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: card_layout_presets; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: comment_visibility_teams; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: comments; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.comments VALUES ('304e86a6-ba61-47b7-b0cd-2785a878dbb9', 'c7f79859-1816-4707-bf4b-b30ba7350926', 'Comment on 0', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'public', 'item', 'ec4e2875-1924-4c2c-918d-113af787b19a', 'null', NULL, NULL, NULL, false, NULL, NULL);
INSERT INTO public.comments VALUES ('a98dedb9-1773-4519-9977-6eb5447d5770', 'c7f79859-1816-4707-bf4b-b30ba7350926', 'Comment on 5', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'public', 'item', 'b3c20177-7e9a-46a1-9224-21a85f262a39', 'null', NULL, NULL, NULL, false, NULL, NULL);
INSERT INTO public.comments VALUES ('deed63a2-d64b-47d0-9114-9fa90b763143', 'c7f79859-1816-4707-bf4b-b30ba7350926', 'Comment on 10', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'public', 'item', '9049350b-0ad5-4e6f-936f-bc4fa6bb4030', 'null', NULL, NULL, NULL, false, NULL, NULL);
INSERT INTO public.comments VALUES ('1262f1da-798f-4a76-a687-44bca9af2465', 'c7f79859-1816-4707-bf4b-b30ba7350926', 'Comment on 15', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'public', 'item', '72f745a4-a50f-4147-a68b-b1674dd772e8', 'null', NULL, NULL, NULL, false, NULL, NULL);
INSERT INTO public.comments VALUES ('ea94e58f-1c3e-4b38-b4dd-782c84ca3f65', 'c7f79859-1816-4707-bf4b-b30ba7350926', 'Comment on 20', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'public', 'item', 'a1b3bb49-61a3-467f-861a-8fec6eba0c9f', 'null', NULL, NULL, NULL, false, NULL, NULL);


--
-- Data for Name: confluence_connections; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_import_records; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_pending_refs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_plans; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_runs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_snapshot_attachments; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_snapshot_comments; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_snapshot_pages; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: confluence_snapshots; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: consumer_offsets; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: csat_surveys; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: cycle_series; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: cycle_teams; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: cycles; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: dashboard_widgets; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: dashboards; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: directory_sync_state; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: events; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.events VALUES (1, 'user.created', 'user', 'c7f79859-1816-4707-bf4b-b30ba7350926', '{"name": "Drill Admin", "user": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "email": "drill-admin@example.com"}, "email": "drill-admin@example.com", "instance_role": "admin"}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'Drill Admin', 'user created Drill Admin', NULL, 0);
INSERT INTO public.events VALUES (2, 'role.created', 'role', 'b26ea62f-fa21-415a-9994-0d9449dfd605', '{"key": "baseline", "name": "Baseline", "permissions": ["item.read@own", "item.read@participant", "comment.write@own", "attachment.create@own", "participant.manage@own", "comment.delete@own", "attachment.delete@own", "comment.write@participant", "attachment.create@participant", "worklog.delete@own", "label.read", "cycle.read", "canned.read", "team.read", "role.read", "cardpreset.read"]}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'baseline Baseline', 'role created baseline Baseline', NULL, 0);
INSERT INTO public.events VALUES (3, 'role.created', 'role', '0b50c6ab-6e1e-4c7d-b2a9-23aa7bc007ca', '{"key": "manager", "name": "Manager", "permissions": ["project.manage", "item.read", "item.create", "item.update", "worklog.write", "comment.write", "comment.read_internal", "form.manage", "participant.manage", "state.manage", "field.manage", "item.delete", "comment.delete", "worklog.delete", "attachment.create", "attachment.delete", "state.create", "state.update", "state.delete", "field.create", "field.update", "field.delete", "release.create", "release.update", "release.delete", "form.create", "form.update", "form.delete", "view.create", "view.update", "view.delete", "member.create", "member.update", "member.delete", "issue_type.create", "issue_type.update", "issue_type.delete", "sla.create", "sla.update", "sla.delete", "page.manage", "dashboard.create"]}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'manager Manager', 'role created manager Manager', NULL, 0);
INSERT INTO public.events VALUES (4, 'role.created', 'role', '1adbfabb-0168-4a15-8e0b-b9cbcc63df67', '{"key": "member", "name": "Member", "permissions": ["item.read", "page.read", "item.create", "item.update", "worklog.write", "comment.write", "comment.read_internal", "view.create", "view.update", "view.delete", "page.write"]}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'member Member', 'role created member Member', NULL, 0);
INSERT INTO public.events VALUES (5, 'role.created', 'role', 'c8d265c5-3bda-49e8-b081-87a4c7155048', '{"key": "viewer", "name": "Viewer", "permissions": ["item.read", "page.read"]}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'viewer Viewer', 'role created viewer Viewer', NULL, 0);
INSERT INTO public.events VALUES (6, 'role.created', 'role', '59826152-9e1f-43a4-8a0d-80e2f1bdadae', '{"key": "requester", "name": "Requester", "permissions": ["item.read@own", "item.read@participant", "comment.write@own", "attachment.create@own", "participant.manage@own", "comment.delete@own", "attachment.delete@own", "comment.write@participant", "attachment.create@participant"]}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'requester Requester', 'role created requester Requester', NULL, 0);
INSERT INTO public.events VALUES (7, 'role.created', 'role', '7d13e551-5345-446e-acec-8aca53c07b0c', '{"key": "public", "name": "Public", "permissions": ["item.read@public", "page.read", "label.read", "cycle.read", "team.read"]}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'public Public', 'role created public Public', NULL, 0);
INSERT INTO public.events VALUES (8, 'role.created', 'role', '7ae8a17d-59e8-4315-80d2-df6351503016', '{"key": "contributor", "name": "Contributor", "permissions": ["item.create", "item.update@own", "comment.write", "attachment.create", "participant.manage@own", "comment.delete@own", "attachment.delete@own"]}', '2026-11-16 13:32:49.266329', NULL, false, false, NULL, 'contributor Contributor', 'role created contributor Contributor', NULL, 0);
INSERT INTO public.events VALUES (9, 'project.created', 'project', '5c60685c-1578-4394-bfb2-7168dac59ad2', '{"key": "DRILL", "name": "Drill", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL Drill', 'project created DRILL Drill', NULL, 0);
INSERT INTO public.events VALUES (10, 'state.created', 'state', 'c5fe1393-9341-40f3-8731-07638de3dfca', '{"name": "Triage", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "category": "triage", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Triage', 'state created Triage', NULL, 0);
INSERT INTO public.events VALUES (11, 'state.created', 'state', 'fe25a5f9-3c6e-4c78-a445-1100cb7fea77', '{"name": "Backlog", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "category": "backlog", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Backlog', 'state created Backlog', NULL, 0);
INSERT INTO public.events VALUES (12, 'state.created', 'state', '3be9cf08-9523-442d-bdf9-4ac89cda31fc', '{"name": "Todo", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "category": "todo", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Todo', 'state created Todo', NULL, 0);
INSERT INTO public.events VALUES (13, 'state.created', 'state', 'c0db3227-ff7f-4d40-92cc-7d813c1e5026', '{"name": "In Progress", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "category": "in_progress", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'In Progress', 'state created In Progress', NULL, 0);
INSERT INTO public.events VALUES (14, 'state.created', 'state', '91e173fa-0169-4fa4-a7fb-1ee84323e5a4', '{"name": "Code Review", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "category": "in_progress", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Code Review', 'state created Code Review', NULL, 0);
INSERT INTO public.events VALUES (15, 'state.created', 'state', '7ac435e2-d7f3-47d8-8a83-416a2c2f856a', '{"name": "Done", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "category": "done", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Done', 'state created Done', NULL, 0);
INSERT INTO public.events VALUES (16, 'state.created', 'state', '9ebfcd0b-eaad-45c6-9c96-90e3a57a5842', '{"name": "Canceled", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "category": "canceled", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Canceled', 'state created Canceled', NULL, 0);
INSERT INTO public.events VALUES (17, 'issue_type.created', 'issue_type', '1c3f47eb-d780-40d0-974b-614829cccff4', '{"name": "Task", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Task', 'issue type created Task', NULL, 0);
INSERT INTO public.events VALUES (18, 'issue_type.created', 'issue_type', '4665ce7a-3773-4071-a6c1-f983c6096541', '{"name": "Bug", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Bug', 'issue type created Bug', NULL, 0);
INSERT INTO public.events VALUES (19, 'issue_type.created', 'issue_type', '294d1f08-4b99-47a1-8787-d713d3cd8b37', '{"name": "Story", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Story', 'issue type created Story', NULL, 0);
INSERT INTO public.events VALUES (20, 'issue_type.created', 'issue_type', '343d3b58-2ffb-4b91-9f4b-2bde018e3916', '{"name": "Feature", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Feature', 'issue type created Feature', NULL, 0);
INSERT INTO public.events VALUES (21, 'issue_type.created', 'issue_type', 'a3d6e14c-9f1d-4f56-b658-1e4f20696e31', '{"name": "Epic", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2"}', '2026-11-16 13:32:49.337369', NULL, false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Epic', 'issue type created Epic', NULL, 0);
INSERT INTO public.events VALUES (22, 'item.created', 'item', 'ec4e2875-1924-4c2c-918d-113af787b19a', '{"item": {"id": "ec4e2875-1924-4c2c-918d-113af787b19a", "key": "DRILL-1", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 0", "labels": [], "number": 1, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-1 Drill item 0', 'item created DRILL-1 Drill item 0', NULL, 0);
INSERT INTO public.events VALUES (23, 'comment.created', 'comment', '304e86a6-ba61-47b7-b0cd-2785a878dbb9', '{"item": {"id": "ec4e2875-1924-4c2c-918d-113af787b19a", "key": "DRILL-1", "kind": "issue", "team": null, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 0", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "assignee": null, "priority": "normal"}, "page": null, "author": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "email": "drill-admin@example.com"}, "origin": null, "excerpt": "Comment on 0", "entity_id": "ec4e2875-1924-4c2c-918d-113af787b19a", "is_thread": false, "visibility": "public", "entity_type": "item", "visible_to_teams": [], "parent_comment_id": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', NULL, 'comment created', NULL, 0);
INSERT INTO public.events VALUES (24, 'item.created', 'item', '1306e55b-9224-4556-9983-84b0db1c61c3', '{"item": {"id": "1306e55b-9224-4556-9983-84b0db1c61c3", "key": "DRILL-2", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 1", "labels": [], "number": 2, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-2 Drill item 1', 'item created DRILL-2 Drill item 1', NULL, 0);
INSERT INTO public.events VALUES (25, 'item.created', 'item', '903f0445-048e-4512-8518-aeb113b30a98', '{"item": {"id": "903f0445-048e-4512-8518-aeb113b30a98", "key": "DRILL-3", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 2", "labels": [], "number": 3, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-3 Drill item 2', 'item created DRILL-3 Drill item 2', NULL, 0);
INSERT INTO public.events VALUES (26, 'item.created', 'item', '5385dfec-e956-4f75-a127-bd8e4dc07a0c', '{"item": {"id": "5385dfec-e956-4f75-a127-bd8e4dc07a0c", "key": "DRILL-4", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 3", "labels": [], "number": 4, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-4 Drill item 3', 'item created DRILL-4 Drill item 3', NULL, 0);
INSERT INTO public.events VALUES (27, 'item.created', 'item', '9709b7ae-ff2e-424e-a29a-3d1ac5744433', '{"item": {"id": "9709b7ae-ff2e-424e-a29a-3d1ac5744433", "key": "DRILL-5", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 4", "labels": [], "number": 5, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-5 Drill item 4', 'item created DRILL-5 Drill item 4', NULL, 0);
INSERT INTO public.events VALUES (28, 'item.created', 'item', 'b3c20177-7e9a-46a1-9224-21a85f262a39', '{"item": {"id": "b3c20177-7e9a-46a1-9224-21a85f262a39", "key": "DRILL-6", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 5", "labels": [], "number": 6, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-6 Drill item 5', 'item created DRILL-6 Drill item 5', NULL, 0);
INSERT INTO public.events VALUES (29, 'comment.created', 'comment', 'a98dedb9-1773-4519-9977-6eb5447d5770', '{"item": {"id": "b3c20177-7e9a-46a1-9224-21a85f262a39", "key": "DRILL-6", "kind": "issue", "team": null, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 5", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "assignee": null, "priority": "normal"}, "page": null, "author": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "email": "drill-admin@example.com"}, "origin": null, "excerpt": "Comment on 5", "entity_id": "b3c20177-7e9a-46a1-9224-21a85f262a39", "is_thread": false, "visibility": "public", "entity_type": "item", "visible_to_teams": [], "parent_comment_id": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', NULL, 'comment created', NULL, 0);
INSERT INTO public.events VALUES (30, 'item.created', 'item', '368d5b71-0e16-47c2-9cff-773a4824f908', '{"item": {"id": "368d5b71-0e16-47c2-9cff-773a4824f908", "key": "DRILL-7", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 6", "labels": [], "number": 7, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-7 Drill item 6', 'item created DRILL-7 Drill item 6', NULL, 0);
INSERT INTO public.events VALUES (31, 'item.created', 'item', 'ea4c93ab-c39c-4a8e-8af7-5b82894855bb', '{"item": {"id": "ea4c93ab-c39c-4a8e-8af7-5b82894855bb", "key": "DRILL-8", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 7", "labels": [], "number": 8, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-8 Drill item 7', 'item created DRILL-8 Drill item 7', NULL, 0);
INSERT INTO public.events VALUES (47, 'comment.created', 'comment', 'ea94e58f-1c3e-4b38-b4dd-782c84ca3f65', '{"item": {"id": "a1b3bb49-61a3-467f-861a-8fec6eba0c9f", "key": "DRILL-21", "kind": "issue", "team": null, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 20", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "assignee": null, "priority": "normal"}, "page": null, "author": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "email": "drill-admin@example.com"}, "origin": null, "excerpt": "Comment on 20", "entity_id": "a1b3bb49-61a3-467f-861a-8fec6eba0c9f", "is_thread": false, "visibility": "public", "entity_type": "item", "visible_to_teams": [], "parent_comment_id": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', NULL, 'comment created', NULL, 0);
INSERT INTO public.events VALUES (32, 'item.created', 'item', '03802b6f-05a4-405f-8898-cae8ebaee77e', '{"item": {"id": "03802b6f-05a4-405f-8898-cae8ebaee77e", "key": "DRILL-9", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 8", "labels": [], "number": 9, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-9 Drill item 8', 'item created DRILL-9 Drill item 8', NULL, 0);
INSERT INTO public.events VALUES (33, 'item.created', 'item', '1c4e9081-7b3e-4b17-bf86-ea08ac2fba32', '{"item": {"id": "1c4e9081-7b3e-4b17-bf86-ea08ac2fba32", "key": "DRILL-10", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 9", "labels": [], "number": 10, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-10 Drill item 9', 'item created DRILL-10 Drill item 9', NULL, 0);
INSERT INTO public.events VALUES (34, 'item.created', 'item', '9049350b-0ad5-4e6f-936f-bc4fa6bb4030', '{"item": {"id": "9049350b-0ad5-4e6f-936f-bc4fa6bb4030", "key": "DRILL-11", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 10", "labels": [], "number": 11, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-11 Drill item 10', 'item created DRILL-11 Drill item 10', NULL, 0);
INSERT INTO public.events VALUES (35, 'comment.created', 'comment', 'deed63a2-d64b-47d0-9114-9fa90b763143', '{"item": {"id": "9049350b-0ad5-4e6f-936f-bc4fa6bb4030", "key": "DRILL-11", "kind": "issue", "team": null, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 10", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "assignee": null, "priority": "normal"}, "page": null, "author": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "email": "drill-admin@example.com"}, "origin": null, "excerpt": "Comment on 10", "entity_id": "9049350b-0ad5-4e6f-936f-bc4fa6bb4030", "is_thread": false, "visibility": "public", "entity_type": "item", "visible_to_teams": [], "parent_comment_id": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', NULL, 'comment created', NULL, 0);
INSERT INTO public.events VALUES (36, 'item.created', 'item', 'cb2ba76b-b7dc-415e-8252-73299feeeac0', '{"item": {"id": "cb2ba76b-b7dc-415e-8252-73299feeeac0", "key": "DRILL-12", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 11", "labels": [], "number": 12, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-12 Drill item 11', 'item created DRILL-12 Drill item 11', NULL, 0);
INSERT INTO public.events VALUES (37, 'item.created', 'item', 'bb144115-19c2-43b3-90c1-498bf339772e', '{"item": {"id": "bb144115-19c2-43b3-90c1-498bf339772e", "key": "DRILL-13", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 12", "labels": [], "number": 13, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-13 Drill item 12', 'item created DRILL-13 Drill item 12', NULL, 0);
INSERT INTO public.events VALUES (38, 'item.created', 'item', 'f16a2f47-bd47-4ecf-973b-d10f52f7404b', '{"item": {"id": "f16a2f47-bd47-4ecf-973b-d10f52f7404b", "key": "DRILL-14", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 13", "labels": [], "number": 14, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-14 Drill item 13', 'item created DRILL-14 Drill item 13', NULL, 0);
INSERT INTO public.events VALUES (39, 'item.created', 'item', '9ca77841-f7e3-4a1f-a035-6ed618e5b13c', '{"item": {"id": "9ca77841-f7e3-4a1f-a035-6ed618e5b13c", "key": "DRILL-15", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 14", "labels": [], "number": 15, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-15 Drill item 14', 'item created DRILL-15 Drill item 14', NULL, 0);
INSERT INTO public.events VALUES (40, 'item.created', 'item', '72f745a4-a50f-4147-a68b-b1674dd772e8', '{"item": {"id": "72f745a4-a50f-4147-a68b-b1674dd772e8", "key": "DRILL-16", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 15", "labels": [], "number": 16, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-16 Drill item 15', 'item created DRILL-16 Drill item 15', NULL, 0);
INSERT INTO public.events VALUES (41, 'comment.created', 'comment', '1262f1da-798f-4a76-a687-44bca9af2465', '{"item": {"id": "72f745a4-a50f-4147-a68b-b1674dd772e8", "key": "DRILL-16", "kind": "issue", "team": null, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 15", "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "assignee": null, "priority": "normal"}, "page": null, "author": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "email": "drill-admin@example.com"}, "origin": null, "excerpt": "Comment on 15", "entity_id": "72f745a4-a50f-4147-a68b-b1674dd772e8", "is_thread": false, "visibility": "public", "entity_type": "item", "visible_to_teams": [], "parent_comment_id": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', NULL, 'comment created', NULL, 0);
INSERT INTO public.events VALUES (42, 'item.created', 'item', '4dbd52dc-9f81-4914-aa52-97ef7b78e914', '{"item": {"id": "4dbd52dc-9f81-4914-aa52-97ef7b78e914", "key": "DRILL-17", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 16", "labels": [], "number": 17, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-17 Drill item 16', 'item created DRILL-17 Drill item 16', NULL, 0);
INSERT INTO public.events VALUES (43, 'item.created', 'item', '64449402-9333-4063-9204-46fc166a81ee', '{"item": {"id": "64449402-9333-4063-9204-46fc166a81ee", "key": "DRILL-18", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 17", "labels": [], "number": 18, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-18 Drill item 17', 'item created DRILL-18 Drill item 17', NULL, 0);
INSERT INTO public.events VALUES (44, 'item.created', 'item', 'da64513b-deb1-4a7d-9dc7-162fa5685fb7', '{"item": {"id": "da64513b-deb1-4a7d-9dc7-162fa5685fb7", "key": "DRILL-19", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 18", "labels": [], "number": 19, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-19 Drill item 18', 'item created DRILL-19 Drill item 18', NULL, 0);
INSERT INTO public.events VALUES (45, 'item.created', 'item', '239453b4-24c6-44e4-90a2-862d48fbdcd1', '{"item": {"id": "239453b4-24c6-44e4-90a2-862d48fbdcd1", "key": "DRILL-20", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 19", "labels": [], "number": 20, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-20 Drill item 19', 'item created DRILL-20 Drill item 19', NULL, 0);
INSERT INTO public.events VALUES (46, 'item.created', 'item', 'a1b3bb49-61a3-467f-861a-8fec6eba0c9f', '{"item": {"id": "a1b3bb49-61a3-467f-861a-8fec6eba0c9f", "key": "DRILL-21", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 20", "labels": [], "number": 21, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-21 Drill item 20', 'item created DRILL-21 Drill item 20', NULL, 0);
INSERT INTO public.events VALUES (48, 'item.created', 'item', 'bfb55556-eed3-4b60-8e90-cb02db2c464f', '{"item": {"id": "bfb55556-eed3-4b60-8e90-cb02db2c464f", "key": "DRILL-22", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 21", "labels": [], "number": 22, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-22 Drill item 21', 'item created DRILL-22 Drill item 21', NULL, 0);
INSERT INTO public.events VALUES (49, 'item.created', 'item', '2a1ea6f3-36a8-4e58-abd7-5e96c2480da1', '{"item": {"id": "2a1ea6f3-36a8-4e58-abd7-5e96c2480da1", "key": "DRILL-23", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 22", "labels": [], "number": 23, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-23 Drill item 22', 'item created DRILL-23 Drill item 22', NULL, 0);
INSERT INTO public.events VALUES (50, 'item.created', 'item', '7017bda8-f806-413e-a848-eab87145fe10', '{"item": {"id": "7017bda8-f806-413e-a848-eab87145fe10", "key": "DRILL-24", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 23", "labels": [], "number": 24, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-24 Drill item 23', 'item created DRILL-24 Drill item 23', NULL, 0);
INSERT INTO public.events VALUES (51, 'item.created', 'item', '861396e6-3327-43bc-ab45-29349fc8983d', '{"item": {"id": "861396e6-3327-43bc-ab45-29349fc8983d", "key": "DRILL-25", "epic": null, "kind": "issue", "team": null, "type": {"id": "1c3f47eb-d780-40d0-974b-614829cccff4", "icon": "square-check-big", "name": "Task", "color": "#64748b"}, "cycle": null, "links": {"incoming": [], "outgoing": []}, "state": {"id": "c5fe1393-9341-40f3-8731-07638de3dfca", "name": "Triage", "category": "triage"}, "title": "Drill item 24", "labels": [], "number": 25, "parent": null, "flagged": false, "project": {"id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "key": "DRILL", "name": "Drill"}, "release": null, "starred": false, "assignee": null, "priority": "normal", "reporter": {"id": "c7f79859-1816-4707-bf4b-b30ba7350926", "name": "Drill Admin", "avatar_url": null, "avatar_color": null, "avatar_emoji": null}, "created_at": "2026-11-16T13:32:49.337369Z", "project_id": "5c60685c-1578-4394-bfb2-7168dac59ad2", "start_date": null, "updated_at": "2026-11-16T13:32:49.337369Z", "visibility": "public", "archived_at": null, "child_count": 0, "description": "", "epic_hidden": false, "past_cycles": [], "target_date": null, "capabilities": null, "comment_count": 0, "custom_fields": {}, "parent_hidden": false, "email_signature": null, "estimate_points": null}, "origin": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, '5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL-25 Drill item 24', 'item created DRILL-25 Drill item 24', NULL, 0);
INSERT INTO public.events VALUES (52, 'webhook_endpoint.created', 'webhook_endpoint', '87fdb8b0-5987-46d1-8bbb-e72957f0d75a', '{"url": "https://example.invalid/drill", "event_types": null}', '2026-11-16 13:32:49.337369', 'c7f79859-1816-4707-bf4b-b30ba7350926', false, false, NULL, 'https://example.invalid/drill', 'webhook endpoint created https://example.invalid/drill', NULL, 0);


--
-- Data for Name: field_definition_projects; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: field_definitions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: forgejo_connections; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: forgejo_repos; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: form_shares; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: forms; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: github_connections; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: github_repos; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: gitlab_connections; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: gitlab_repos; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: global_role_grants; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: group_members; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: group_parents; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: groups; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: installed_plugins; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: issue_types; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.issue_types VALUES ('1c3f47eb-d780-40d0-974b-614829cccff4', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Task', '#64748b', 'square-check-big', 1, true, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', NULL);
INSERT INTO public.issue_types VALUES ('4665ce7a-3773-4071-a6c1-f983c6096541', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Bug', '#ef4444', 'bug', 2, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', NULL);
INSERT INTO public.issue_types VALUES ('294d1f08-4b99-47a1-8787-d713d3cd8b37', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Story', '#22c55e', 'bookmark', 3, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', NULL);
INSERT INTO public.issue_types VALUES ('343d3b58-2ffb-4b91-9f4b-2bde018e3916', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Feature', '#3b82f6', 'sparkles', 4, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', NULL);
INSERT INTO public.issue_types VALUES ('a3d6e14c-9f1d-4f56-b658-1e4f20696e31', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Epic', '#a855f7', 'gem', 5, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', NULL);


--
-- Data for Name: item_cycle_records; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_estimates; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_key_aliases; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_labels; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_link_type_projects; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_link_types; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.item_link_types VALUES ('86c6867f-cf73-4e61-ae62-972a4d03f2dd', 'blocks', 'Blocks', 'blocks', 'is blocked by', 'directed', true, false, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.item_link_types VALUES ('c9710a01-7c69-4b04-85e9-0670edeaa993', 'relates', 'Relates', 'relates to', 'relates to', 'symmetric', true, false, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.item_link_types VALUES ('6d088e9d-343d-46eb-a099-47f810bf335e', 'duplicates', 'Duplicates', 'duplicates', 'is duplicated by', 'directed', true, false, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.item_link_types VALUES ('c2c54fbf-06c0-4394-9dda-26518460f981', 'mentions', 'Mentions', 'mentions', 'mentioned by', 'directed', true, true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');


--
-- Data for Name: item_links; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_page_links; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_participants; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_stars; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_vcs_links; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_watchers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: item_web_links; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_connections; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_import_records; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_pending_refs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_plans; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_runs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_snapshot_blobs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_snapshot_issues; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: jira_snapshots; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: labels; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: leave_periods; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: mail_contacts; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: mail_messages; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: mail_rules; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: mail_senders; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: mail_signature_settings; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.mail_signature_settings VALUES (1, '[]');


--
-- Data for Name: mail_sources; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: mfa_enrollment_tickets; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: milestones; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: notification_prefs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: notification_rules; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: notifications; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_collab_docs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_labels; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_links; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_path_history; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_spaces; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_templates; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_versions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: page_watchers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: pages; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: plugin_processes; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: project_timelogging; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: projects; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.projects VALUES ('5c60685c-1578-4394-bfb2-7168dac59ad2', 'DRILL', 'Drill', 26, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', '');


--
-- Data for Name: releases; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: roles; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.roles VALUES ('b26ea62f-fa21-415a-9994-0d9449dfd605', 'baseline', 'Baseline', 'What everyone with an account gets, on every project, without being granted anything. Edit this to widen or narrow the floor.', '["item.read@own", "item.read@participant", "comment.write@own", "attachment.create@own", "participant.manage@own", "comment.delete@own", "attachment.delete@own", "comment.write@participant", "attachment.create@participant", "worklog.delete@own", "label.read", "cycle.read", "canned.read", "team.read", "role.read", "cardpreset.read"]', true, -1, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.roles VALUES ('0b50c6ab-6e1e-4c7d-b2a9-23aa7bc007ca', 'manager', 'Manager', 'Runs a project or a wiki space. On a project: everything a Member does, plus its settings — workflow, fields, issue types, members, releases, SLAs and intake forms. On a space: edit, delete and restore its pages.', '["project.manage", "item.read", "item.create", "item.update", "worklog.write", "comment.write", "comment.read_internal", "form.manage", "participant.manage", "state.manage", "field.manage", "item.delete", "comment.delete", "worklog.delete", "attachment.create", "attachment.delete", "state.create", "state.update", "state.delete", "field.create", "field.update", "field.delete", "release.create", "release.update", "release.delete", "form.create", "form.update", "form.delete", "view.create", "view.update", "view.delete", "member.create", "member.update", "member.delete", "issue_type.create", "issue_type.update", "issue_type.delete", "sla.create", "sla.update", "sla.delete", "page.manage", "dashboard.create"]', true, 0, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.roles VALUES ('1adbfabb-0168-4a15-8e0b-b9cbcc63df67', 'member', 'Member', 'Day-to-day work. On a project: create and edit issues, comment (internal notes too), log time and keep views. On a space: write pages.', '["item.read", "page.read", "item.create", "item.update", "worklog.write", "comment.write", "comment.read_internal", "view.create", "view.update", "view.delete", "page.write"]', true, 1, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.roles VALUES ('c8d265c5-3bda-49e8-b081-87a4c7155048', 'viewer', 'Viewer', 'Read-only. On a project: its issues. On a space: its pages.', '["item.read", "page.read"]', true, 2, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.roles VALUES ('59826152-9e1f-43a4-8a0d-80e2f1bdadae', 'requester', 'Requester', 'The floor for email-provisioned requester accounts (never the Baseline): their own tickets, commenting and attaching on them, and nothing else — not other items, not the wiki.', '["item.read@own", "item.read@participant", "comment.write@own", "attachment.create@own", "participant.manage@own", "comment.delete@own", "attachment.delete@own", "comment.write@participant", "attachment.create@participant"]', true, 3, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.roles VALUES ('7d13e551-5345-446e-acec-8aca53c07b0c', 'public', 'Public', 'What the world holds on a public project: its public issues, their public comments and attachments, and the labels, cycles and teams needed to render them. Granted to Anyone by the Public project switch.', '["item.read@public", "page.read", "label.read", "cycle.read", "team.read"]', true, 4, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.roles VALUES ('7ae8a17d-59e8-4315-80d2-df6351503016', 'contributor', 'Contributor', 'What anyone with an account may do on a public project: file issues, comment, attach, and edit what they filed. Reading comes from Public. Granted to Signed-in users by the contributions switch.', '["item.create", "item.update@own", "comment.write", "attachment.create", "participant.manage@own", "comment.delete@own", "attachment.delete@own"]', true, 5, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');


--
-- Data for Name: scoped_settings; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: screen_fields; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: screens; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: script_interpreter; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: script_packages; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: search_index; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sessions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sla_item_states; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sla_policies; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sso_provider_default_grants; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sso_provider_default_teams; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sso_providers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: sso_provisioning_rules; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: state_categories; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.state_categories VALUES ('400965e1-5974-4824-9fe3-516a224264e7', 'triage', 'Triage', NULL, 0, 'triage', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.state_categories VALUES ('9920d2ef-8d2f-40db-8460-790ba78b2104', 'backlog', 'Backlog', NULL, 1, 'backlog', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.state_categories VALUES ('6e859bab-dc35-47a9-895c-83beacd0c714', 'todo', 'Todo', NULL, 2, 'todo', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.state_categories VALUES ('07400d9b-1aeb-4412-a614-f619464bb834', 'in_progress', 'In Progress', NULL, 3, 'in_progress', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.state_categories VALUES ('1773197b-8207-484e-b607-b57f60588838', 'done', 'Done', NULL, 4, 'done', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');
INSERT INTO public.state_categories VALUES ('cc67f3a5-0159-4e0b-b9d6-30cf6b2cda69', 'canceled', 'Canceled', NULL, 5, 'canceled', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718');


--
-- Data for Name: states; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.states VALUES ('c5fe1393-9341-40f3-8731-07638de3dfca', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Triage', 'triage', 1, true, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'triage');
INSERT INTO public.states VALUES ('fe25a5f9-3c6e-4c78-a445-1100cb7fea77', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Backlog', 'backlog', 2, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'backlog');
INSERT INTO public.states VALUES ('3be9cf08-9523-442d-bdf9-4ac89cda31fc', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Todo', 'todo', 3, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'todo');
INSERT INTO public.states VALUES ('c0db3227-ff7f-4d40-92cc-7d813c1e5026', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'In Progress', 'in_progress', 4, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'in_progress');
INSERT INTO public.states VALUES ('91e173fa-0169-4fa4-a7fb-1ee84323e5a4', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Code Review', 'in_progress', 5, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'in_progress');
INSERT INTO public.states VALUES ('7ac435e2-d7f3-47d8-8a83-416a2c2f856a', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Done', 'done', 6, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'done');
INSERT INTO public.states VALUES ('9ebfcd0b-eaad-45c6-9c96-90e3a57a5842', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Canceled', 'canceled', 7, false, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'canceled');


--
-- Data for Name: storage_hosts; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: storage_rules; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: team_assignment_cursors; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: team_managers; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: team_members; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: teams; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: thread_resolution_rules; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: totp_recovery_codes; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_identities; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: user_totp; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.users VALUES ('00000000-0000-0000-0000-000000a4104e', 'anyone@principals.invalid', 'Anyone', NULL, 'member', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718', NULL, NULL, '', 'principal', NULL, '{}', NULL, NULL, NULL);
INSERT INTO public.users VALUES ('00000000-0000-0000-0000-0000005160ed', 'signed-in@principals.invalid', 'Signed-in users', NULL, 'member', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718', NULL, NULL, '', 'principal', NULL, '{}', NULL, NULL, NULL);
INSERT INTO public.users VALUES ('00000000-0000-0000-0000-000000a70a70', 'automation@radd.system', 'Automation', NULL, 'admin', true, '2026-11-16 13:32:44.82718', '2026-11-16 13:32:44.82718', NULL, NULL, '', 'service', NULL, '{}', NULL, NULL, NULL);
INSERT INTO public.users VALUES ('c7f79859-1816-4707-bf4b-b30ba7350926', 'drill-admin@example.com', 'Drill Admin', '$argon2id$v=19$m=65536,t=3,p=4$rdP0l1qXuckuPahKetzfSw$sLDIkjRBG9LNwuyIozqNNzvV7YXZS4OEDDjgmq/CsnI', 'admin', true, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329', NULL, NULL, '', 'local', NULL, '{}', NULL, NULL, NULL);


--
-- Data for Name: vcs_deliveries; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: vcs_pending_worklogs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: vcs_seeds; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: vcs_user_links; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: view_members; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: views; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.views VALUES ('ceebbbcc-228c-4249-91bf-945dc4a5ee3a', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Board', 'board', 'state', NULL, 0, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', '', NULL, NULL, '[]', 'viewer', NULL, NULL, NULL, NULL, NULL, false, NULL);
INSERT INTO public.views VALUES ('6324d8f4-701b-49c5-9b69-b30d51c9ceec', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'List', 'list', NULL, NULL, 0, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', '', NULL, NULL, '[]', 'viewer', NULL, NULL, NULL, NULL, NULL, false, NULL);
INSERT INTO public.views VALUES ('1b075395-9159-4d15-9234-f9424eefcf40', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Planning', 'planning', NULL, NULL, 0, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', '', NULL, NULL, '[]', 'viewer', NULL, NULL, NULL, NULL, NULL, false, NULL);
INSERT INTO public.views VALUES ('1b729efb-6f4b-4d79-af93-810fd0db76f9', '5c60685c-1578-4394-bfb2-7168dac59ad2', 'Roadmap', 'roadmap', NULL, NULL, 0, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', '', NULL, NULL, '[]', 'viewer', NULL, NULL, NULL, NULL, NULL, false, NULL);


--
-- Data for Name: webhook_deliveries; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: webhook_endpoints; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.webhook_endpoints VALUES ('87fdb8b0-5987-46d1-8bbb-e72957f0d75a', 'https://example.invalid/drill', 'enc1:eObT4rAT51AFQR+QbXJO+3yWA8FTHGfMdXJ/1mWHnZbur17sGfpC0krywBA1IfWSWWwnJrxssyvppOZopARrgXgCAPsZ54ZqNpMi42M1', 'drill', 'null', true, '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369');


--
-- Data for Name: work_categories; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.work_categories VALUES ('b475527a-110e-45b9-9961-7db08115fc1e', 'Development', 0, false, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.work_categories VALUES ('df68d0a3-b8f8-4ccd-9470-3966418418f4', 'Investigation', 1, false, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.work_categories VALUES ('c9772330-7db5-44b9-9d5e-99dc38a86fd3', 'Code Review', 2, false, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.work_categories VALUES ('86e9d122-6ec3-4e8b-9ab2-8a685d309d58', 'Meeting', 3, false, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.work_categories VALUES ('ebd1ae3b-5411-430e-a577-f90c242e4be3', 'Discussion', 4, false, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.work_categories VALUES ('5bbcf5dc-1d43-4d75-84a3-38260c68292c', 'Documentation', 5, false, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');
INSERT INTO public.work_categories VALUES ('fa6c7345-04d4-4c4f-803f-7a9098e5dade', 'Testing', 6, false, '2026-11-16 13:32:49.266329', '2026-11-16 13:32:49.266329');


--
-- Data for Name: work_items; Type: TABLE DATA; Schema: public; Owner: -
--

INSERT INTO public.work_items VALUES ('ec4e2875-1924-4c2c-918d-113af787b19a', '5c60685c-1578-4394-bfb2-7168dac59ad2', 1, 'Drill item 0', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -1024, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('1306e55b-9224-4556-9983-84b0db1c61c3', '5c60685c-1578-4394-bfb2-7168dac59ad2', 2, 'Drill item 1', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -2048, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('903f0445-048e-4512-8518-aeb113b30a98', '5c60685c-1578-4394-bfb2-7168dac59ad2', 3, 'Drill item 2', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -3072, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('5385dfec-e956-4f75-a127-bd8e4dc07a0c', '5c60685c-1578-4394-bfb2-7168dac59ad2', 4, 'Drill item 3', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -4096, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('9709b7ae-ff2e-424e-a29a-3d1ac5744433', '5c60685c-1578-4394-bfb2-7168dac59ad2', 5, 'Drill item 4', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -5120, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('b3c20177-7e9a-46a1-9224-21a85f262a39', '5c60685c-1578-4394-bfb2-7168dac59ad2', 6, 'Drill item 5', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -6144, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('368d5b71-0e16-47c2-9cff-773a4824f908', '5c60685c-1578-4394-bfb2-7168dac59ad2', 7, 'Drill item 6', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -7168, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('ea4c93ab-c39c-4a8e-8af7-5b82894855bb', '5c60685c-1578-4394-bfb2-7168dac59ad2', 8, 'Drill item 7', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -8192, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('03802b6f-05a4-405f-8898-cae8ebaee77e', '5c60685c-1578-4394-bfb2-7168dac59ad2', 9, 'Drill item 8', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -9216, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('1c4e9081-7b3e-4b17-bf86-ea08ac2fba32', '5c60685c-1578-4394-bfb2-7168dac59ad2', 10, 'Drill item 9', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -10240, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('9049350b-0ad5-4e6f-936f-bc4fa6bb4030', '5c60685c-1578-4394-bfb2-7168dac59ad2', 11, 'Drill item 10', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -11264, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('cb2ba76b-b7dc-415e-8252-73299feeeac0', '5c60685c-1578-4394-bfb2-7168dac59ad2', 12, 'Drill item 11', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -12288, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('bb144115-19c2-43b3-90c1-498bf339772e', '5c60685c-1578-4394-bfb2-7168dac59ad2', 13, 'Drill item 12', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -13312, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('f16a2f47-bd47-4ecf-973b-d10f52f7404b', '5c60685c-1578-4394-bfb2-7168dac59ad2', 14, 'Drill item 13', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -14336, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('9ca77841-f7e3-4a1f-a035-6ed618e5b13c', '5c60685c-1578-4394-bfb2-7168dac59ad2', 15, 'Drill item 14', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -15360, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('72f745a4-a50f-4147-a68b-b1674dd772e8', '5c60685c-1578-4394-bfb2-7168dac59ad2', 16, 'Drill item 15', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -16384, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('4dbd52dc-9f81-4914-aa52-97ef7b78e914', '5c60685c-1578-4394-bfb2-7168dac59ad2', 17, 'Drill item 16', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -17408, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('64449402-9333-4063-9204-46fc166a81ee', '5c60685c-1578-4394-bfb2-7168dac59ad2', 18, 'Drill item 17', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -18432, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('da64513b-deb1-4a7d-9dc7-162fa5685fb7', '5c60685c-1578-4394-bfb2-7168dac59ad2', 19, 'Drill item 18', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -19456, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('239453b4-24c6-44e4-90a2-862d48fbdcd1', '5c60685c-1578-4394-bfb2-7168dac59ad2', 20, 'Drill item 19', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -20480, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('a1b3bb49-61a3-467f-861a-8fec6eba0c9f', '5c60685c-1578-4394-bfb2-7168dac59ad2', 21, 'Drill item 20', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -21504, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('bfb55556-eed3-4b60-8e90-cb02db2c464f', '5c60685c-1578-4394-bfb2-7168dac59ad2', 22, 'Drill item 21', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -22528, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('2a1ea6f3-36a8-4e58-abd7-5e96c2480da1', '5c60685c-1578-4394-bfb2-7168dac59ad2', 23, 'Drill item 22', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -23552, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('7017bda8-f806-413e-a848-eab87145fe10', '5c60685c-1578-4394-bfb2-7168dac59ad2', 24, 'Drill item 23', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -24576, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);
INSERT INTO public.work_items VALUES ('861396e6-3327-43bc-ab45-29349fc8983d', '5c60685c-1578-4394-bfb2-7168dac59ad2', 25, 'Drill item 24', '', 'normal', '{}', '2026-11-16 13:32:49.337369', '2026-11-16 13:32:49.337369', 'c5fe1393-9341-40f3-8731-07638de3dfca', 'issue', NULL, NULL, NULL, NULL, NULL, NULL, NULL, false, -25600, 'c7f79859-1816-4707-bf4b-b30ba7350926', NULL, '1c3f47eb-d780-40d0-974b-614829cccff4', NULL, 'public', NULL);


--
-- Data for Name: workflow_transitions; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Data for Name: worklogs; Type: TABLE DATA; Schema: public; Owner: -
--



--
-- Name: confluence_import_records_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.confluence_import_records_id_seq', 1, false);


--
-- Name: events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.events_id_seq', 52, true);


--
-- Name: jira_import_records_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.jira_import_records_id_seq', 1, false);


--
-- Name: mail_signature_settings_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.mail_signature_settings_id_seq', 1, false);


--
-- Name: pages_number_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pages_number_seq', 1, false);


--
-- Name: script_interpreter_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.script_interpreter_id_seq', 1, false);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: access_grants pk_access_grants; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT pk_access_grants PRIMARY KEY (id);


--
-- Name: access_restrictions pk_access_restrictions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_restrictions
    ADD CONSTRAINT pk_access_restrictions PRIMARY KEY (id);


--
-- Name: ai_model_roles pk_ai_model_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_model_roles
    ADD CONSTRAINT pk_ai_model_roles PRIMARY KEY (role);


--
-- Name: ai_preset_prompts pk_ai_preset_prompts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_preset_prompts
    ADD CONSTRAINT pk_ai_preset_prompts PRIMARY KEY (id);


--
-- Name: ai_providers pk_ai_providers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_providers
    ADD CONSTRAINT pk_ai_providers PRIMARY KEY (id);


--
-- Name: alert_items pk_alert_items; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_items
    ADD CONSTRAINT pk_alert_items PRIMARY KEY (id);


--
-- Name: alertmanager_receivers pk_alertmanager_receivers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertmanager_receivers
    ADD CONSTRAINT pk_alertmanager_receivers PRIMARY KEY (id);


--
-- Name: alertmanager_seed pk_alertmanager_seed; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertmanager_seed
    ADD CONSTRAINT pk_alertmanager_seed PRIMARY KEY (key);


--
-- Name: api_tokens pk_api_tokens; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_tokens
    ADD CONSTRAINT pk_api_tokens PRIMARY KEY (id);


--
-- Name: approval_requests pk_approval_requests; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT pk_approval_requests PRIMARY KEY (id);


--
-- Name: approval_votes pk_approval_votes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_votes
    ADD CONSTRAINT pk_approval_votes PRIMARY KEY (id);


--
-- Name: attachment_move_jobs pk_attachment_move_jobs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment_move_jobs
    ADD CONSTRAINT pk_attachment_move_jobs PRIMARY KEY (id);


--
-- Name: attachments pk_attachments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT pk_attachments PRIMARY KEY (id);


--
-- Name: automation_runs pk_automation_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT pk_automation_runs PRIMARY KEY (id);


--
-- Name: automation_schedule_state pk_automation_schedule_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_schedule_state
    ADD CONSTRAINT pk_automation_schedule_state PRIMARY KEY (automation_id, node_id);


--
-- Name: automation_triggers pk_automation_triggers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_triggers
    ADD CONSTRAINT pk_automation_triggers PRIMARY KEY (automation_id, node_id);


--
-- Name: automation_validations pk_automation_validations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_validations
    ADD CONSTRAINT pk_automation_validations PRIMARY KEY (automation_id, node_id, target_kind, target_id);


--
-- Name: automation_versions pk_automation_versions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_versions
    ADD CONSTRAINT pk_automation_versions PRIMARY KEY (id);


--
-- Name: automations pk_automations; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automations
    ADD CONSTRAINT pk_automations PRIMARY KEY (id);


--
-- Name: backup_runs pk_backup_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_runs
    ADD CONSTRAINT pk_backup_runs PRIMARY KEY (id);


--
-- Name: backup_schedules pk_backup_schedules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_schedules
    ADD CONSTRAINT pk_backup_schedules PRIMARY KEY (id);


--
-- Name: canned_responses pk_canned_responses; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.canned_responses
    ADD CONSTRAINT pk_canned_responses PRIMARY KEY (id);


--
-- Name: card_layout_presets pk_card_layout_presets; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.card_layout_presets
    ADD CONSTRAINT pk_card_layout_presets PRIMARY KEY (id);


--
-- Name: comment_visibility_teams pk_comment_visibility_teams; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment_visibility_teams
    ADD CONSTRAINT pk_comment_visibility_teams PRIMARY KEY (comment_id, team_id);


--
-- Name: comments pk_comments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT pk_comments PRIMARY KEY (id);


--
-- Name: confluence_connections pk_confluence_connections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_connections
    ADD CONSTRAINT pk_confluence_connections PRIMARY KEY (id);


--
-- Name: confluence_import_records pk_confluence_import_records; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_import_records
    ADD CONSTRAINT pk_confluence_import_records PRIMARY KEY (id);


--
-- Name: confluence_pending_refs pk_confluence_pending_refs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_pending_refs
    ADD CONSTRAINT pk_confluence_pending_refs PRIMARY KEY (id);


--
-- Name: confluence_plans pk_confluence_plans; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_plans
    ADD CONSTRAINT pk_confluence_plans PRIMARY KEY (id);


--
-- Name: confluence_runs pk_confluence_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_runs
    ADD CONSTRAINT pk_confluence_runs PRIMARY KEY (id);


--
-- Name: confluence_snapshot_attachments pk_confluence_snapshot_attachments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshot_attachments
    ADD CONSTRAINT pk_confluence_snapshot_attachments PRIMARY KEY (snapshot_id, attachment_id);


--
-- Name: confluence_snapshot_comments pk_confluence_snapshot_comments; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshot_comments
    ADD CONSTRAINT pk_confluence_snapshot_comments PRIMARY KEY (snapshot_id, comment_id);


--
-- Name: confluence_snapshot_pages pk_confluence_snapshot_pages; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshot_pages
    ADD CONSTRAINT pk_confluence_snapshot_pages PRIMARY KEY (snapshot_id, page_id);


--
-- Name: confluence_snapshots pk_confluence_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshots
    ADD CONSTRAINT pk_confluence_snapshots PRIMARY KEY (id);


--
-- Name: consumer_offsets pk_consumer_offsets; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.consumer_offsets
    ADD CONSTRAINT pk_consumer_offsets PRIMARY KEY (name);


--
-- Name: csat_surveys pk_csat_surveys; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.csat_surveys
    ADD CONSTRAINT pk_csat_surveys PRIMARY KEY (id);


--
-- Name: cycle_series pk_cycle_series; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_series
    ADD CONSTRAINT pk_cycle_series PRIMARY KEY (id);


--
-- Name: cycle_teams pk_cycle_teams; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_teams
    ADD CONSTRAINT pk_cycle_teams PRIMARY KEY (cycle_id, team_id);


--
-- Name: cycles pk_cycles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycles
    ADD CONSTRAINT pk_cycles PRIMARY KEY (id);


--
-- Name: dashboard_widgets pk_dashboard_widgets; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_widgets
    ADD CONSTRAINT pk_dashboard_widgets PRIMARY KEY (id);


--
-- Name: dashboards pk_dashboards; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboards
    ADD CONSTRAINT pk_dashboards PRIMARY KEY (id);


--
-- Name: directory_sync_state pk_directory_sync_state; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.directory_sync_state
    ADD CONSTRAINT pk_directory_sync_state PRIMARY KEY (kind);


--
-- Name: page_versions pk_doc_page_versions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_versions
    ADD CONSTRAINT pk_doc_page_versions PRIMARY KEY (id);


--
-- Name: pages pk_doc_pages; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT pk_doc_pages PRIMARY KEY (id);


--
-- Name: page_spaces pk_doc_spaces; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_spaces
    ADD CONSTRAINT pk_doc_spaces PRIMARY KEY (id);


--
-- Name: events pk_events; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.events
    ADD CONSTRAINT pk_events PRIMARY KEY (id);


--
-- Name: field_definition_projects pk_field_definition_projects; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_definition_projects
    ADD CONSTRAINT pk_field_definition_projects PRIMARY KEY (field_id, project_id);


--
-- Name: field_definitions pk_field_definitions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_definitions
    ADD CONSTRAINT pk_field_definitions PRIMARY KEY (id);


--
-- Name: forgejo_connections pk_forgejo_connections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forgejo_connections
    ADD CONSTRAINT pk_forgejo_connections PRIMARY KEY (id);


--
-- Name: forgejo_repos pk_forgejo_repos; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forgejo_repos
    ADD CONSTRAINT pk_forgejo_repos PRIMARY KEY (id);


--
-- Name: form_shares pk_form_shares; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.form_shares
    ADD CONSTRAINT pk_form_shares PRIMARY KEY (id);


--
-- Name: forms pk_forms; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forms
    ADD CONSTRAINT pk_forms PRIMARY KEY (id);


--
-- Name: github_connections pk_github_connections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_connections
    ADD CONSTRAINT pk_github_connections PRIMARY KEY (id);


--
-- Name: github_repos pk_github_repos; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_repos
    ADD CONSTRAINT pk_github_repos PRIMARY KEY (id);


--
-- Name: gitlab_connections pk_gitlab_connections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gitlab_connections
    ADD CONSTRAINT pk_gitlab_connections PRIMARY KEY (id);


--
-- Name: gitlab_repos pk_gitlab_repos; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gitlab_repos
    ADD CONSTRAINT pk_gitlab_repos PRIMARY KEY (id);


--
-- Name: global_role_grants pk_global_role_grants; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT pk_global_role_grants PRIMARY KEY (id);


--
-- Name: group_members pk_group_members; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_members
    ADD CONSTRAINT pk_group_members PRIMARY KEY (group_id, user_id);


--
-- Name: group_parents pk_group_parents; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_parents
    ADD CONSTRAINT pk_group_parents PRIMARY KEY (child_id, parent_id);


--
-- Name: groups pk_groups; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.groups
    ADD CONSTRAINT pk_groups PRIMARY KEY (id);


--
-- Name: installed_plugins pk_installed_plugins; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.installed_plugins
    ADD CONSTRAINT pk_installed_plugins PRIMARY KEY (id);


--
-- Name: issue_types pk_issue_types; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_types
    ADD CONSTRAINT pk_issue_types PRIMARY KEY (id);


--
-- Name: item_cycle_records pk_item_cycle_records; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_cycle_records
    ADD CONSTRAINT pk_item_cycle_records PRIMARY KEY (id);


--
-- Name: item_page_links pk_item_doc_links; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_page_links
    ADD CONSTRAINT pk_item_doc_links PRIMARY KEY (item_id, page_id);


--
-- Name: item_estimates pk_item_estimates; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_estimates
    ADD CONSTRAINT pk_item_estimates PRIMARY KEY (item_id);


--
-- Name: item_key_aliases pk_item_key_aliases; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_key_aliases
    ADD CONSTRAINT pk_item_key_aliases PRIMARY KEY (old_key);


--
-- Name: item_labels pk_item_labels; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_labels
    ADD CONSTRAINT pk_item_labels PRIMARY KEY (item_id, label_id);


--
-- Name: item_link_type_projects pk_item_link_type_projects; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link_type_projects
    ADD CONSTRAINT pk_item_link_type_projects PRIMARY KEY (link_type_id, project_id);


--
-- Name: item_link_types pk_item_link_types; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link_types
    ADD CONSTRAINT pk_item_link_types PRIMARY KEY (id);


--
-- Name: item_links pk_item_links; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_links
    ADD CONSTRAINT pk_item_links PRIMARY KEY (id);


--
-- Name: item_participants pk_item_participants; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_participants
    ADD CONSTRAINT pk_item_participants PRIMARY KEY (id);


--
-- Name: item_stars pk_item_stars; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_stars
    ADD CONSTRAINT pk_item_stars PRIMARY KEY (user_id, item_id);


--
-- Name: item_vcs_links pk_item_vcs_links; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_vcs_links
    ADD CONSTRAINT pk_item_vcs_links PRIMARY KEY (id);


--
-- Name: item_watchers pk_item_watchers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_watchers
    ADD CONSTRAINT pk_item_watchers PRIMARY KEY (item_id, user_id);


--
-- Name: item_web_links pk_item_web_links; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_web_links
    ADD CONSTRAINT pk_item_web_links PRIMARY KEY (id);


--
-- Name: jira_connections pk_jira_connections; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_connections
    ADD CONSTRAINT pk_jira_connections PRIMARY KEY (id);


--
-- Name: jira_import_records pk_jira_import_records; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_import_records
    ADD CONSTRAINT pk_jira_import_records PRIMARY KEY (id);


--
-- Name: jira_pending_refs pk_jira_pending_refs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_pending_refs
    ADD CONSTRAINT pk_jira_pending_refs PRIMARY KEY (id);


--
-- Name: jira_plans pk_jira_plans; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_plans
    ADD CONSTRAINT pk_jira_plans PRIMARY KEY (id);


--
-- Name: jira_runs pk_jira_runs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_runs
    ADD CONSTRAINT pk_jira_runs PRIMARY KEY (id);


--
-- Name: jira_snapshot_blobs pk_jira_snapshot_blobs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_snapshot_blobs
    ADD CONSTRAINT pk_jira_snapshot_blobs PRIMARY KEY (snapshot_id, jira_attachment_id);


--
-- Name: jira_snapshot_issues pk_jira_snapshot_issues; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_snapshot_issues
    ADD CONSTRAINT pk_jira_snapshot_issues PRIMARY KEY (snapshot_id, jira_key);


--
-- Name: jira_snapshots pk_jira_snapshots; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_snapshots
    ADD CONSTRAINT pk_jira_snapshots PRIMARY KEY (id);


--
-- Name: labels pk_labels; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.labels
    ADD CONSTRAINT pk_labels PRIMARY KEY (id);


--
-- Name: leave_periods pk_leave_periods; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leave_periods
    ADD CONSTRAINT pk_leave_periods PRIMARY KEY (id);


--
-- Name: mail_contacts pk_mail_contacts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_contacts
    ADD CONSTRAINT pk_mail_contacts PRIMARY KEY (id);


--
-- Name: mail_messages pk_mail_messages; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_messages
    ADD CONSTRAINT pk_mail_messages PRIMARY KEY (id);


--
-- Name: mail_rules pk_mail_rules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_rules
    ADD CONSTRAINT pk_mail_rules PRIMARY KEY (id);


--
-- Name: mail_senders pk_mail_senders; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_senders
    ADD CONSTRAINT pk_mail_senders PRIMARY KEY (id);


--
-- Name: mail_signature_settings pk_mail_signature_settings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_signature_settings
    ADD CONSTRAINT pk_mail_signature_settings PRIMARY KEY (id);


--
-- Name: mail_sources pk_mail_sources; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_sources
    ADD CONSTRAINT pk_mail_sources PRIMARY KEY (id);


--
-- Name: mfa_enrollment_tickets pk_mfa_enrollment_tickets; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mfa_enrollment_tickets
    ADD CONSTRAINT pk_mfa_enrollment_tickets PRIMARY KEY (id);


--
-- Name: milestones pk_milestones; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.milestones
    ADD CONSTRAINT pk_milestones PRIMARY KEY (id);


--
-- Name: notification_prefs pk_notification_prefs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_prefs
    ADD CONSTRAINT pk_notification_prefs PRIMARY KEY (user_id);


--
-- Name: notification_rules pk_notification_rules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_rules
    ADD CONSTRAINT pk_notification_rules PRIMARY KEY (id);


--
-- Name: notifications pk_notifications; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notifications
    ADD CONSTRAINT pk_notifications PRIMARY KEY (id);


--
-- Name: page_collab_docs pk_page_collab_docs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_collab_docs
    ADD CONSTRAINT pk_page_collab_docs PRIMARY KEY (page_id);


--
-- Name: page_labels pk_page_labels; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_labels
    ADD CONSTRAINT pk_page_labels PRIMARY KEY (page_id, label_id);


--
-- Name: page_links pk_page_links; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_links
    ADD CONSTRAINT pk_page_links PRIMARY KEY (source_page_id, target_page_id);


--
-- Name: page_path_history pk_page_path_history; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_path_history
    ADD CONSTRAINT pk_page_path_history PRIMARY KEY (id);


--
-- Name: page_templates pk_page_templates; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_templates
    ADD CONSTRAINT pk_page_templates PRIMARY KEY (id);


--
-- Name: page_watchers pk_page_watchers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_watchers
    ADD CONSTRAINT pk_page_watchers PRIMARY KEY (page_id, user_id);


--
-- Name: plugin_processes pk_plugin_processes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.plugin_processes
    ADD CONSTRAINT pk_plugin_processes PRIMARY KEY (process_id);


--
-- Name: project_timelogging pk_project_timelogging; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_timelogging
    ADD CONSTRAINT pk_project_timelogging PRIMARY KEY (project_id);


--
-- Name: projects pk_projects; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT pk_projects PRIMARY KEY (id);


--
-- Name: releases pk_releases; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.releases
    ADD CONSTRAINT pk_releases PRIMARY KEY (id);


--
-- Name: roles pk_roles; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT pk_roles PRIMARY KEY (id);


--
-- Name: scoped_settings pk_scoped_settings; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoped_settings
    ADD CONSTRAINT pk_scoped_settings PRIMARY KEY (id);


--
-- Name: screen_fields pk_screen_fields; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screen_fields
    ADD CONSTRAINT pk_screen_fields PRIMARY KEY (id);


--
-- Name: screens pk_screens; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screens
    ADD CONSTRAINT pk_screens PRIMARY KEY (id);


--
-- Name: script_interpreter pk_script_interpreter; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.script_interpreter
    ADD CONSTRAINT pk_script_interpreter PRIMARY KEY (id);


--
-- Name: script_packages pk_script_packages; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.script_packages
    ADD CONSTRAINT pk_script_packages PRIMARY KEY (id);


--
-- Name: search_index pk_search_index; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index
    ADD CONSTRAINT pk_search_index PRIMARY KEY (item_id);


--
-- Name: sessions pk_sessions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT pk_sessions PRIMARY KEY (id);


--
-- Name: sla_item_states pk_sla_item_states; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_item_states
    ADD CONSTRAINT pk_sla_item_states PRIMARY KEY (item_id, policy_id);


--
-- Name: sla_policies pk_sla_policies; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_policies
    ADD CONSTRAINT pk_sla_policies PRIMARY KEY (id);


--
-- Name: sso_provider_default_grants pk_sso_provider_default_grants; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_grants
    ADD CONSTRAINT pk_sso_provider_default_grants PRIMARY KEY (id);


--
-- Name: sso_provider_default_teams pk_sso_provider_default_teams; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_teams
    ADD CONSTRAINT pk_sso_provider_default_teams PRIMARY KEY (id);


--
-- Name: sso_providers pk_sso_providers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_providers
    ADD CONSTRAINT pk_sso_providers PRIMARY KEY (id);


--
-- Name: sso_provisioning_rules pk_sso_provisioning_rules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provisioning_rules
    ADD CONSTRAINT pk_sso_provisioning_rules PRIMARY KEY (id);


--
-- Name: state_categories pk_state_categories; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.state_categories
    ADD CONSTRAINT pk_state_categories PRIMARY KEY (id);


--
-- Name: states pk_states; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT pk_states PRIMARY KEY (id);


--
-- Name: storage_hosts pk_storage_hosts; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_hosts
    ADD CONSTRAINT pk_storage_hosts PRIMARY KEY (id);


--
-- Name: storage_rules pk_storage_rules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_rules
    ADD CONSTRAINT pk_storage_rules PRIMARY KEY (id);


--
-- Name: team_assignment_cursors pk_team_assignment_cursors; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_assignment_cursors
    ADD CONSTRAINT pk_team_assignment_cursors PRIMARY KEY (team_id);


--
-- Name: team_managers pk_team_managers; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_managers
    ADD CONSTRAINT pk_team_managers PRIMARY KEY (team_id, user_id);


--
-- Name: team_members pk_team_members; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT pk_team_members PRIMARY KEY (id);


--
-- Name: teams pk_teams; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT pk_teams PRIMARY KEY (id);


--
-- Name: thread_resolution_rules pk_thread_resolution_rules; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_resolution_rules
    ADD CONSTRAINT pk_thread_resolution_rules PRIMARY KEY (id);


--
-- Name: totp_recovery_codes pk_totp_recovery_codes; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.totp_recovery_codes
    ADD CONSTRAINT pk_totp_recovery_codes PRIMARY KEY (id);


--
-- Name: user_identities pk_user_identities; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_identities
    ADD CONSTRAINT pk_user_identities PRIMARY KEY (id);


--
-- Name: user_totp pk_user_totp; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_totp
    ADD CONSTRAINT pk_user_totp PRIMARY KEY (user_id);


--
-- Name: users pk_users; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT pk_users PRIMARY KEY (id);


--
-- Name: vcs_deliveries pk_vcs_deliveries; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_deliveries
    ADD CONSTRAINT pk_vcs_deliveries PRIMARY KEY (provider, connection_id, digest);


--
-- Name: vcs_pending_worklogs pk_vcs_pending_worklogs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_pending_worklogs
    ADD CONSTRAINT pk_vcs_pending_worklogs PRIMARY KEY (id);


--
-- Name: vcs_seeds pk_vcs_seeds; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_seeds
    ADD CONSTRAINT pk_vcs_seeds PRIMARY KEY (provider);


--
-- Name: vcs_user_links pk_vcs_user_links; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_user_links
    ADD CONSTRAINT pk_vcs_user_links PRIMARY KEY (id);


--
-- Name: view_members pk_view_members; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.view_members
    ADD CONSTRAINT pk_view_members PRIMARY KEY (view_id, item_id);


--
-- Name: views pk_views; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.views
    ADD CONSTRAINT pk_views PRIMARY KEY (id);


--
-- Name: webhook_deliveries pk_webhook_deliveries; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT pk_webhook_deliveries PRIMARY KEY (id);


--
-- Name: webhook_endpoints pk_webhook_endpoints; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_endpoints
    ADD CONSTRAINT pk_webhook_endpoints PRIMARY KEY (id);


--
-- Name: work_categories pk_work_categories; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_categories
    ADD CONSTRAINT pk_work_categories PRIMARY KEY (id);


--
-- Name: work_items pk_work_items; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT pk_work_items PRIMARY KEY (id);


--
-- Name: workflow_transitions pk_workflow_transitions; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_transitions
    ADD CONSTRAINT pk_workflow_transitions PRIMARY KEY (id);


--
-- Name: worklogs pk_worklogs; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT pk_worklogs PRIMARY KEY (id);


--
-- Name: access_grants uq_access_grants_row; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT uq_access_grants_row UNIQUE (resource_type, resource_id, subject_type, subject_id, access, project_id);


--
-- Name: access_restrictions uq_access_restriction_scope; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_restrictions
    ADD CONSTRAINT uq_access_restriction_scope UNIQUE NULLS NOT DISTINCT (resource_type, resource_id, access, project_id);


--
-- Name: ai_providers uq_ai_providers_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_providers
    ADD CONSTRAINT uq_ai_providers_name UNIQUE (name);


--
-- Name: alert_items uq_alert_items_receiver_fingerprint; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_items
    ADD CONSTRAINT uq_alert_items_receiver_fingerprint UNIQUE (receiver_id, fingerprint);


--
-- Name: alertmanager_receivers uq_alertmanager_receivers_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertmanager_receivers
    ADD CONSTRAINT uq_alertmanager_receivers_name UNIQUE (name);


--
-- Name: api_tokens uq_api_tokens_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_tokens
    ADD CONSTRAINT uq_api_tokens_token_hash UNIQUE (token_hash);


--
-- Name: approval_votes uq_approval_votes_request_id_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_votes
    ADD CONSTRAINT uq_approval_votes_request_id_user_id UNIQUE (request_id, user_id);


--
-- Name: attachments uq_attachments_storage_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT uq_attachments_storage_name UNIQUE (storage_name);


--
-- Name: automation_versions uq_automation_versions_automation_id_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_versions
    ADD CONSTRAINT uq_automation_versions_automation_id_version UNIQUE (automation_id, version);


--
-- Name: confluence_connections uq_confluence_connections_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_connections
    ADD CONSTRAINT uq_confluence_connections_name UNIQUE (name);


--
-- Name: confluence_plans uq_confluence_plans_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_plans
    ADD CONSTRAINT uq_confluence_plans_name UNIQUE (name);


--
-- Name: csat_surveys uq_csat_surveys_item_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.csat_surveys
    ADD CONSTRAINT uq_csat_surveys_item_id UNIQUE (item_id);


--
-- Name: csat_surveys uq_csat_surveys_token; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.csat_surveys
    ADD CONSTRAINT uq_csat_surveys_token UNIQUE (token);


--
-- Name: cycle_series uq_cycle_series_label; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_series
    ADD CONSTRAINT uq_cycle_series_label UNIQUE (label);


--
-- Name: page_versions uq_doc_page_versions_page_id_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_versions
    ADD CONSTRAINT uq_doc_page_versions_page_id_version UNIQUE (page_id, version);


--
-- Name: page_spaces uq_doc_spaces_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_spaces
    ADD CONSTRAINT uq_doc_spaces_slug UNIQUE (slug);


--
-- Name: field_definitions uq_field_definitions_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_definitions
    ADD CONSTRAINT uq_field_definitions_key UNIQUE (key);


--
-- Name: forgejo_connections uq_forgejo_connections_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forgejo_connections
    ADD CONSTRAINT uq_forgejo_connections_name UNIQUE (name);


--
-- Name: forgejo_repos uq_forgejo_repos_connection_id_full_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forgejo_repos
    ADD CONSTRAINT uq_forgejo_repos_connection_id_full_name UNIQUE (connection_id, full_name);


--
-- Name: form_shares uq_form_shares_form_id_team_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.form_shares
    ADD CONSTRAINT uq_form_shares_form_id_team_id UNIQUE (form_id, team_id);


--
-- Name: form_shares uq_form_shares_form_id_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.form_shares
    ADD CONSTRAINT uq_form_shares_form_id_user_id UNIQUE (form_id, user_id);


--
-- Name: github_connections uq_github_connections_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_connections
    ADD CONSTRAINT uq_github_connections_name UNIQUE (name);


--
-- Name: github_repos uq_github_repos_connection_id_full_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_repos
    ADD CONSTRAINT uq_github_repos_connection_id_full_name UNIQUE (connection_id, full_name);


--
-- Name: gitlab_connections uq_gitlab_connections_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gitlab_connections
    ADD CONSTRAINT uq_gitlab_connections_name UNIQUE (name);


--
-- Name: gitlab_repos uq_gitlab_repos_connection_id_full_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gitlab_repos
    ADD CONSTRAINT uq_gitlab_repos_connection_id_full_name UNIQUE (connection_id, full_name);


--
-- Name: global_role_grants uq_global_role_grants_role_id_group_id_project_id_space_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT uq_global_role_grants_role_id_group_id_project_id_space_id UNIQUE (role_id, group_id, project_id, space_id);


--
-- Name: global_role_grants uq_global_role_grants_role_id_team_id_project_id_space_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT uq_global_role_grants_role_id_team_id_project_id_space_id UNIQUE (role_id, team_id, project_id, space_id);


--
-- Name: global_role_grants uq_global_role_grants_role_id_user_id_project_id_space_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT uq_global_role_grants_role_id_user_id_project_id_space_id UNIQUE (role_id, user_id, project_id, space_id);


--
-- Name: groups uq_groups_dn; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.groups
    ADD CONSTRAINT uq_groups_dn UNIQUE (dn);


--
-- Name: issue_types uq_issue_types_project_id_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_types
    ADD CONSTRAINT uq_issue_types_project_id_name UNIQUE (project_id, name);


--
-- Name: item_link_types uq_item_link_types_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link_types
    ADD CONSTRAINT uq_item_link_types_key UNIQUE (key);


--
-- Name: item_links uq_item_links_source_item_id_target_item_id_link_type; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_links
    ADD CONSTRAINT uq_item_links_source_item_id_target_item_id_link_type UNIQUE (source_item_id, target_item_id, link_type);


--
-- Name: item_participants uq_item_participants_item_id_team_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_participants
    ADD CONSTRAINT uq_item_participants_item_id_team_id UNIQUE (item_id, team_id);


--
-- Name: item_participants uq_item_participants_item_id_user_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_participants
    ADD CONSTRAINT uq_item_participants_item_id_user_id UNIQUE (item_id, user_id);


--
-- Name: jira_connections uq_jira_connections_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_connections
    ADD CONSTRAINT uq_jira_connections_name UNIQUE (name);


--
-- Name: jira_plans uq_jira_plans_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_plans
    ADD CONSTRAINT uq_jira_plans_name UNIQUE (name);


--
-- Name: labels uq_labels_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.labels
    ADD CONSTRAINT uq_labels_name UNIQUE (name);


--
-- Name: mail_contacts uq_mail_contacts_item_id_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_contacts
    ADD CONSTRAINT uq_mail_contacts_item_id_email UNIQUE (item_id, email);


--
-- Name: mail_messages uq_mail_messages_message_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_messages
    ADD CONSTRAINT uq_mail_messages_message_id UNIQUE (message_id);


--
-- Name: mfa_enrollment_tickets uq_mfa_enrollment_tickets_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mfa_enrollment_tickets
    ADD CONSTRAINT uq_mfa_enrollment_tickets_token_hash UNIQUE (token_hash);


--
-- Name: page_templates uq_page_templates_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_templates
    ADD CONSTRAINT uq_page_templates_name UNIQUE (name);


--
-- Name: projects uq_projects_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT uq_projects_key UNIQUE (key);


--
-- Name: releases uq_releases_project_id_version; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.releases
    ADD CONSTRAINT uq_releases_project_id_version UNIQUE (project_id, version);


--
-- Name: roles uq_roles_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.roles
    ADD CONSTRAINT uq_roles_key UNIQUE (key);


--
-- Name: scoped_settings uq_scoped_settings_scope_scope_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.scoped_settings
    ADD CONSTRAINT uq_scoped_settings_scope_scope_id_key UNIQUE (scope, scope_id, key);


--
-- Name: screen_fields uq_screen_fields_screen_id_field; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screen_fields
    ADD CONSTRAINT uq_screen_fields_screen_id_field UNIQUE (screen_id, field);


--
-- Name: screens uq_screens_project_id_issue_type_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screens
    ADD CONSTRAINT uq_screens_project_id_issue_type_id UNIQUE (project_id, issue_type_id);


--
-- Name: script_packages uq_script_packages_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.script_packages
    ADD CONSTRAINT uq_script_packages_name UNIQUE (name);


--
-- Name: sessions uq_sessions_token_hash; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT uq_sessions_token_hash UNIQUE (token_hash);


--
-- Name: sso_provider_default_grants uq_sso_default_grant; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_grants
    ADD CONSTRAINT uq_sso_default_grant UNIQUE (rule_id, role_id, project_id);


--
-- Name: sso_provider_default_teams uq_sso_default_team; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_teams
    ADD CONSTRAINT uq_sso_default_team UNIQUE (rule_id, team_id);


--
-- Name: sso_providers uq_sso_providers_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_providers
    ADD CONSTRAINT uq_sso_providers_name UNIQUE (name);


--
-- Name: state_categories uq_state_categories_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.state_categories
    ADD CONSTRAINT uq_state_categories_key UNIQUE (key);


--
-- Name: state_categories uq_state_categories_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.state_categories
    ADD CONSTRAINT uq_state_categories_name UNIQUE (name);


--
-- Name: states uq_states_project_id_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT uq_states_project_id_name UNIQUE (project_id, name);


--
-- Name: storage_hosts uq_storage_hosts_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.storage_hosts
    ADD CONSTRAINT uq_storage_hosts_name UNIQUE (name);


--
-- Name: team_members uq_team_members_group; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT uq_team_members_group UNIQUE (team_id, group_id);


--
-- Name: team_members uq_team_members_user; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT uq_team_members_user UNIQUE (team_id, user_id);


--
-- Name: teams uq_teams_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT uq_teams_name UNIQUE (name);


--
-- Name: thread_resolution_rules uq_thread_resolution_rules_scope; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_resolution_rules
    ADD CONSTRAINT uq_thread_resolution_rules_scope UNIQUE NULLS NOT DISTINCT (project_id, issue_type_id);


--
-- Name: user_identities uq_user_identities_provider_id_subject; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_identities
    ADD CONSTRAINT uq_user_identities_provider_id_subject UNIQUE (provider_id, subject);


--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);


--
-- Name: vcs_pending_worklogs uq_vcs_pending_worklogs_entry; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_pending_worklogs
    ADD CONSTRAINT uq_vcs_pending_worklogs_entry UNIQUE (provider, external_id);


--
-- Name: vcs_user_links uq_vcs_user_links_account; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_user_links
    ADD CONSTRAINT uq_vcs_user_links_account UNIQUE (provider, connection_id, external_username);


--
-- Name: work_categories uq_work_categories_name; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_categories
    ADD CONSTRAINT uq_work_categories_name UNIQUE (name);


--
-- Name: work_items uq_work_items_project_id_number; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT uq_work_items_project_id_number UNIQUE (project_id, number);


--
-- Name: ix_access_grants_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_access_grants_project_id ON public.access_grants USING btree (project_id);


--
-- Name: ix_access_grants_resource; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_access_grants_resource ON public.access_grants USING btree (resource_type, resource_id);


--
-- Name: ix_access_grants_subject_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_access_grants_subject_id ON public.access_grants USING btree (subject_id);


--
-- Name: ix_api_tokens_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_api_tokens_user_id ON public.api_tokens USING btree (user_id);


--
-- Name: ix_approval_requests_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_approval_requests_item_id ON public.approval_requests USING btree (item_id);


--
-- Name: ix_approval_requests_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_approval_requests_status ON public.approval_requests USING btree (status);


--
-- Name: ix_approval_votes_request_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_approval_votes_request_id ON public.approval_votes USING btree (request_id);


--
-- Name: ix_attachments_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_entity ON public.attachments USING btree (entity_type, entity_id);


--
-- Name: ix_attachments_storage_host_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_attachments_storage_host_id ON public.attachments USING btree (storage_host_id);


--
-- Name: ix_automation_runs_automation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_automation_id ON public.automation_runs USING btree (automation_id);


--
-- Name: ix_automation_runs_automation_started; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_automation_started ON public.automation_runs USING btree (automation_id, started_at);


--
-- Name: ix_automation_runs_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_started_at ON public.automation_runs USING btree (started_at);


--
-- Name: ix_automation_runs_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_runs_status ON public.automation_runs USING btree (status);


--
-- Name: ix_automation_triggers_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_triggers_event_type ON public.automation_triggers USING btree (event_type);


--
-- Name: ix_automation_validations_target_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_validations_target_id ON public.automation_validations USING btree (target_id);


--
-- Name: ix_automation_validations_target_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_validations_target_kind ON public.automation_validations USING btree (target_kind);


--
-- Name: ix_automation_versions_automation_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_automation_versions_automation_id ON public.automation_versions USING btree (automation_id);


--
-- Name: ix_backup_runs_started_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_backup_runs_started_at ON public.backup_runs USING btree (started_at);


--
-- Name: ix_backup_schedules_due; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_backup_schedules_due ON public.backup_schedules USING btree (next_run_at) WHERE enabled;


--
-- Name: ix_comments_author_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_comments_author_id ON public.comments USING btree (author_id);


--
-- Name: ix_comments_entity_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_comments_entity_id ON public.comments USING btree (entity_id);


--
-- Name: ix_comments_parent_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_comments_parent_order ON public.comments USING btree (entity_type, entity_id, created_at, id);


--
-- Name: ix_comments_thread_order; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_comments_thread_order ON public.comments USING btree (parent_comment_id, created_at, id);


--
-- Name: ix_comments_unresolved_inline; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_comments_unresolved_inline ON public.comments USING btree (entity_type, entity_id) WHERE ((anchor IS NOT NULL) AND (resolved_at IS NULL));


--
-- Name: ix_comments_unresolved_threads; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_comments_unresolved_threads ON public.comments USING btree (entity_type, entity_id) WHERE (is_thread AND (resolved_at IS NULL) AND (parent_comment_id IS NULL));


--
-- Name: ix_confluence_import_records_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_confluence_import_records_run ON public.confluence_import_records USING btree (run_id, id);


--
-- Name: ix_confluence_pending_refs_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_confluence_pending_refs_target ON public.confluence_pending_refs USING btree (target_page_id);


--
-- Name: ix_confluence_snapshot_attachments_page; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_confluence_snapshot_attachments_page ON public.confluence_snapshot_attachments USING btree (snapshot_id, page_id);


--
-- Name: ix_confluence_snapshot_comments_page; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_confluence_snapshot_comments_page ON public.confluence_snapshot_comments USING btree (snapshot_id, page_id);


--
-- Name: ix_confluence_snapshot_pages_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_confluence_snapshot_pages_parent ON public.confluence_snapshot_pages USING btree (snapshot_id, parent_id);


--
-- Name: ix_confluence_snapshot_pages_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_confluence_snapshot_pages_snapshot ON public.confluence_snapshot_pages USING btree (snapshot_id, page_id);


--
-- Name: ix_cycles_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_cycles_project_id ON public.cycles USING btree (project_id);


--
-- Name: ix_dashboard_widgets_dashboard_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dashboard_widgets_dashboard_id ON public.dashboard_widgets USING btree (dashboard_id);


--
-- Name: ix_dashboards_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_dashboards_owner_id ON public.dashboards USING btree (owner_id);


--
-- Name: ix_doc_page_versions_page_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_doc_page_versions_page_id ON public.page_versions USING btree (page_id);


--
-- Name: ix_doc_pages_fts; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_doc_pages_fts ON public.pages USING gin (to_tsvector('english'::regconfig, (((title)::text || ' '::text) || body)));


--
-- Name: ix_doc_pages_space_parent; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_doc_pages_space_parent ON public.pages USING btree (space_id, parent_id);


--
-- Name: ix_events_actor_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_actor_id ON public.events USING btree (actor_id);


--
-- Name: ix_events_automated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_automated ON public.events USING btree (id) WHERE automated;


--
-- Name: ix_events_changes; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_changes ON public.events USING gin (((payload -> 'changes'::text)) jsonb_path_ops);


--
-- Name: ix_events_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_entity ON public.events USING btree (entity_type, entity_id);


--
-- Name: ix_events_event_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_event_type ON public.events USING btree (event_type);


--
-- Name: ix_events_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_project_id ON public.events USING btree (project_id);


--
-- Name: ix_events_search_trgm; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_events_search_trgm ON public.events USING gin (search_text public.gin_trgm_ops);


--
-- Name: ix_forgejo_repos_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_forgejo_repos_connection_id ON public.forgejo_repos USING btree (connection_id);


--
-- Name: ix_forgejo_repos_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_forgejo_repos_project_id ON public.forgejo_repos USING btree (project_id);


--
-- Name: ix_form_shares_form_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_form_shares_form_id ON public.form_shares USING btree (form_id);


--
-- Name: ix_form_shares_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_form_shares_team_id ON public.form_shares USING btree (team_id);


--
-- Name: ix_form_shares_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_form_shares_user_id ON public.form_shares USING btree (user_id);


--
-- Name: ix_forms_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_forms_project_id ON public.forms USING btree (project_id);


--
-- Name: ix_github_repos_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_github_repos_connection_id ON public.github_repos USING btree (connection_id);


--
-- Name: ix_github_repos_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_github_repos_project_id ON public.github_repos USING btree (project_id);


--
-- Name: ix_gitlab_repos_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_gitlab_repos_connection_id ON public.gitlab_repos USING btree (connection_id);


--
-- Name: ix_gitlab_repos_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_gitlab_repos_project_id ON public.gitlab_repos USING btree (project_id);


--
-- Name: ix_global_role_grants_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_global_role_grants_group_id ON public.global_role_grants USING btree (group_id);


--
-- Name: ix_global_role_grants_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_global_role_grants_project_id ON public.global_role_grants USING btree (project_id);


--
-- Name: ix_global_role_grants_role_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_global_role_grants_role_id ON public.global_role_grants USING btree (role_id);


--
-- Name: ix_global_role_grants_space_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_global_role_grants_space_id ON public.global_role_grants USING btree (space_id);


--
-- Name: ix_global_role_grants_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_global_role_grants_team_id ON public.global_role_grants USING btree (team_id);


--
-- Name: ix_global_role_grants_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_global_role_grants_user_id ON public.global_role_grants USING btree (user_id);


--
-- Name: ix_issue_types_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_issue_types_project_id ON public.issue_types USING btree (project_id);


--
-- Name: ix_item_cycle_records_cycle_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_cycle_records_cycle_id ON public.item_cycle_records USING btree (cycle_id);


--
-- Name: ix_item_cycle_records_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_cycle_records_item_id ON public.item_cycle_records USING btree (item_id);


--
-- Name: ix_item_doc_links_page_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_doc_links_page_id ON public.item_page_links USING btree (page_id);


--
-- Name: ix_item_key_aliases_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_key_aliases_item_id ON public.item_key_aliases USING btree (item_id);


--
-- Name: ix_item_links_source_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_links_source_item_id ON public.item_links USING btree (source_item_id);


--
-- Name: ix_item_links_target_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_links_target_item_id ON public.item_links USING btree (target_item_id);


--
-- Name: ix_item_participants_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_participants_item_id ON public.item_participants USING btree (item_id);


--
-- Name: ix_item_participants_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_participants_team_id ON public.item_participants USING btree (team_id);


--
-- Name: ix_item_participants_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_participants_user_id ON public.item_participants USING btree (user_id);


--
-- Name: ix_item_vcs_links_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_vcs_links_connection_id ON public.item_vcs_links USING btree (connection_id);


--
-- Name: ix_item_vcs_links_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_vcs_links_item_id ON public.item_vcs_links USING btree (item_id);


--
-- Name: ix_item_web_links_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_item_web_links_item_id ON public.item_web_links USING btree (item_id);


--
-- Name: ix_jira_import_records_run; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jira_import_records_run ON public.jira_import_records USING btree (run_id, id);


--
-- Name: ix_jira_import_records_run_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jira_import_records_run_id ON public.jira_import_records USING btree (run_id);


--
-- Name: ix_jira_pending_refs_source_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jira_pending_refs_source_item_id ON public.jira_pending_refs USING btree (source_item_id);


--
-- Name: ix_jira_pending_refs_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jira_pending_refs_target ON public.jira_pending_refs USING btree (target_jira_key);


--
-- Name: ix_jira_snapshot_blobs_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jira_snapshot_blobs_snapshot ON public.jira_snapshot_blobs USING btree (snapshot_id);


--
-- Name: ix_jira_snapshot_issues_snapshot; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_jira_snapshot_issues_snapshot ON public.jira_snapshot_issues USING btree (snapshot_id, jira_key);


--
-- Name: ix_leave_periods_end_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leave_periods_end_date ON public.leave_periods USING btree (end_date);


--
-- Name: ix_leave_periods_start_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leave_periods_start_date ON public.leave_periods USING btree (start_date);


--
-- Name: ix_leave_periods_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leave_periods_team_id ON public.leave_periods USING btree (team_id);


--
-- Name: ix_leave_periods_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_leave_periods_user_id ON public.leave_periods USING btree (user_id);


--
-- Name: ix_mail_contacts_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_contacts_item_id ON public.mail_contacts USING btree (item_id);


--
-- Name: ix_mail_messages_created_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_messages_created_at ON public.mail_messages USING btree (created_at);


--
-- Name: ix_mail_messages_item_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_messages_item_created ON public.mail_messages USING btree (item_id, created_at);


--
-- Name: ix_mail_messages_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_messages_item_id ON public.mail_messages USING btree (item_id);


--
-- Name: ix_mail_messages_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_messages_source_id ON public.mail_messages USING btree (source_id);


--
-- Name: ix_mail_rules_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_rules_source_id ON public.mail_rules USING btree (source_id);


--
-- Name: ix_mail_rules_source_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_rules_source_position ON public.mail_rules USING btree (source_id, "position");


--
-- Name: ix_mail_sources_default_project; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mail_sources_default_project ON public.mail_sources USING btree (default_project_id);


--
-- Name: ix_mfa_enrollment_tickets_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_mfa_enrollment_tickets_user_id ON public.mfa_enrollment_tickets USING btree (user_id);


--
-- Name: ix_milestones_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_milestones_project_id ON public.milestones USING btree (project_id);


--
-- Name: ix_notification_rules_target; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notification_rules_target ON public.notification_rules USING btree (scope, scope_id);


--
-- Name: ix_notification_rules_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notification_rules_user_id ON public.notification_rules USING btree (user_id);


--
-- Name: ix_notifications_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_item_id ON public.notifications USING btree (item_id);


--
-- Name: ix_notifications_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_id ON public.notifications USING btree (user_id);


--
-- Name: ix_notifications_user_read; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_notifications_user_read ON public.notifications USING btree (user_id, read_at, inbox);


--
-- Name: ix_page_labels_label_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_labels_label_id ON public.page_labels USING btree (label_id);


--
-- Name: ix_page_links_target_page_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_links_target_page_id ON public.page_links USING btree (target_page_id);


--
-- Name: ix_page_path_history_page_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_path_history_page_id ON public.page_path_history USING btree (page_id);


--
-- Name: ix_page_path_history_space_path; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_path_history_space_path ON public.page_path_history USING btree (space_id, path);


--
-- Name: ix_page_watchers_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_page_watchers_user_id ON public.page_watchers USING btree (user_id);


--
-- Name: ix_releases_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_releases_project_id ON public.releases USING btree (project_id);


--
-- Name: ix_scoped_settings_key; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scoped_settings_key ON public.scoped_settings USING btree (key);


--
-- Name: ix_scoped_settings_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scoped_settings_scope ON public.scoped_settings USING btree (scope);


--
-- Name: ix_scoped_settings_scope_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_scoped_settings_scope_id ON public.scoped_settings USING btree (scope_id);


--
-- Name: ix_screen_fields_screen_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_screen_fields_screen_id ON public.screen_fields USING btree (screen_id);


--
-- Name: ix_screens_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_screens_project_id ON public.screens USING btree (project_id);


--
-- Name: ix_search_index_assignee_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_search_index_assignee_id ON public.search_index USING btree (assignee_id);


--
-- Name: ix_search_index_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_search_index_project_id ON public.search_index USING btree (project_id);


--
-- Name: ix_search_index_reporter_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_search_index_reporter_id ON public.search_index USING btree (reporter_id);


--
-- Name: ix_search_index_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_search_index_team_id ON public.search_index USING btree (team_id);


--
-- Name: ix_search_index_tsv; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_search_index_tsv ON public.search_index USING gin (tsv);


--
-- Name: ix_search_key_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_search_key_prefix ON public.search_index USING btree (lower((key)::text) text_pattern_ops);


--
-- Name: ix_search_number_prefix; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_search_number_prefix ON public.search_index USING btree (split_part((key)::text, '-'::text, 2) text_pattern_ops);


--
-- Name: ix_sessions_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_user_id ON public.sessions USING btree (user_id);


--
-- Name: ix_sso_provider_default_grants_rule_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sso_provider_default_grants_rule_id ON public.sso_provider_default_grants USING btree (rule_id);


--
-- Name: ix_sso_provider_default_teams_rule_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sso_provider_default_teams_rule_id ON public.sso_provider_default_teams USING btree (rule_id);


--
-- Name: ix_sso_provisioning_rules_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sso_provisioning_rules_provider_id ON public.sso_provisioning_rules USING btree (provider_id);


--
-- Name: ix_states_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_states_project_id ON public.states USING btree (project_id);


--
-- Name: ix_team_members_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_team_members_group_id ON public.team_members USING btree (group_id);


--
-- Name: ix_team_members_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_team_members_team_id ON public.team_members USING btree (team_id);


--
-- Name: ix_team_members_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_team_members_user_id ON public.team_members USING btree (user_id);


--
-- Name: ix_teams_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_teams_owner_id ON public.teams USING btree (owner_id);


--
-- Name: ix_thread_resolution_rules_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_thread_resolution_rules_project_id ON public.thread_resolution_rules USING btree (project_id);


--
-- Name: ix_totp_recovery_codes_code_hash; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_totp_recovery_codes_code_hash ON public.totp_recovery_codes USING btree (code_hash);


--
-- Name: ix_totp_recovery_codes_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_totp_recovery_codes_user_id ON public.totp_recovery_codes USING btree (user_id);


--
-- Name: ix_user_identities_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_identities_provider_id ON public.user_identities USING btree (provider_id);


--
-- Name: ix_user_identities_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_user_identities_user_id ON public.user_identities USING btree (user_id);


--
-- Name: ix_vcs_pending_worklogs_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vcs_pending_worklogs_connection_id ON public.vcs_pending_worklogs USING btree (connection_id);


--
-- Name: ix_vcs_pending_worklogs_external_scope; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vcs_pending_worklogs_external_scope ON public.vcs_pending_worklogs USING btree (external_scope);


--
-- Name: ix_vcs_pending_worklogs_external_username; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vcs_pending_worklogs_external_username ON public.vcs_pending_worklogs USING btree (external_username);


--
-- Name: ix_vcs_pending_worklogs_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vcs_pending_worklogs_item_id ON public.vcs_pending_worklogs USING btree (item_id);


--
-- Name: ix_vcs_user_links_connection_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vcs_user_links_connection_id ON public.vcs_user_links USING btree (connection_id);


--
-- Name: ix_vcs_user_links_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_vcs_user_links_user_id ON public.vcs_user_links USING btree (user_id);


--
-- Name: ix_view_members_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_view_members_item_id ON public.view_members USING btree (item_id);


--
-- Name: ix_views_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_views_owner_id ON public.views USING btree (owner_id);


--
-- Name: ix_views_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_views_project_id ON public.views USING btree (project_id);


--
-- Name: ix_webhook_deliveries_endpoint_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_deliveries_endpoint_id ON public.webhook_deliveries USING btree (endpoint_id);


--
-- Name: ix_webhook_deliveries_next_attempt_at; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_deliveries_next_attempt_at ON public.webhook_deliveries USING btree (next_attempt_at);


--
-- Name: ix_webhook_deliveries_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_webhook_deliveries_status ON public.webhook_deliveries USING btree (status);


--
-- Name: ix_work_items_assignee_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_assignee_id ON public.work_items USING btree (assignee_id);


--
-- Name: ix_work_items_cycle_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_cycle_id ON public.work_items USING btree (cycle_id);


--
-- Name: ix_work_items_parent_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_parent_id ON public.work_items USING btree (parent_id);


--
-- Name: ix_work_items_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_project_id ON public.work_items USING btree (project_id);


--
-- Name: ix_work_items_project_rank; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_project_rank ON public.work_items USING btree (project_id, rank);


--
-- Name: ix_work_items_rank; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_rank ON public.work_items USING btree (rank);


--
-- Name: ix_work_items_release_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_release_id ON public.work_items USING btree (release_id);


--
-- Name: ix_work_items_reporter_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_reporter_id ON public.work_items USING btree (reporter_id);


--
-- Name: ix_work_items_state_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_state_id ON public.work_items USING btree (state_id);


--
-- Name: ix_work_items_team_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_team_id ON public.work_items USING btree (team_id);


--
-- Name: ix_work_items_type_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_type_id ON public.work_items USING btree (type_id);


--
-- Name: ix_work_items_visibility; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_work_items_visibility ON public.work_items USING btree (visibility);


--
-- Name: ix_workflow_transitions_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_workflow_transitions_project_id ON public.workflow_transitions USING btree (project_id);


--
-- Name: ix_worklogs_author_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_worklogs_author_id ON public.worklogs USING btree (author_id);


--
-- Name: ix_worklogs_category_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_worklogs_category_id ON public.worklogs USING btree (category_id);


--
-- Name: ix_worklogs_item_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_worklogs_item_id ON public.worklogs USING btree (item_id);


--
-- Name: ix_worklogs_project_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_worklogs_project_id ON public.worklogs USING btree (project_id);


--
-- Name: ix_worklogs_worked_on; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_worklogs_worked_on ON public.worklogs USING btree (worked_on);


--
-- Name: uq_item_vcs_links_legacy_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_item_vcs_links_legacy_ref ON public.item_vcs_links USING btree (item_id, provider, external_id) WHERE (((external_id)::text <> ''::text) AND (connection_id IS NULL));


--
-- Name: uq_item_vcs_links_ref; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_item_vcs_links_ref ON public.item_vcs_links USING btree (item_id, provider, connection_id, external_id) WHERE (((external_id)::text <> ''::text) AND (connection_id IS NOT NULL));


--
-- Name: uq_notification_rules_relationship; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_notification_rules_relationship ON public.notification_rules USING btree (user_id, scope) WHERE (scope_id IS NULL);


--
-- Name: uq_notification_rules_subscription; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_notification_rules_subscription ON public.notification_rules USING btree (user_id, scope, scope_id) WHERE (scope_id IS NOT NULL);


--
-- Name: uq_page_spaces_external; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_page_spaces_external ON public.page_spaces USING btree (external_source, external_id) WHERE ((external_id)::text <> ''::text);


--
-- Name: uq_pages_external; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_pages_external ON public.pages USING btree (external_source, external_id) WHERE ((external_id)::text <> ''::text);


--
-- Name: uq_pages_live_sibling_slug; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_pages_live_sibling_slug ON public.pages USING btree (space_id, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), slug) WHERE (archived_at IS NULL);


--
-- Name: uq_pages_number; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_pages_number ON public.pages USING btree (number);


--
-- Name: uq_worklogs_external; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uq_worklogs_external ON public.worklogs USING btree (external_source, external_id) WHERE ((external_id)::text <> ''::text);


--
-- Name: access_grants fk_access_grants_granted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT fk_access_grants_granted_by_users FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: access_grants fk_access_grants_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_grants
    ADD CONSTRAINT fk_access_grants_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: access_restrictions fk_access_restrictions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.access_restrictions
    ADD CONSTRAINT fk_access_restrictions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: ai_model_roles fk_ai_model_roles_provider_id_ai_providers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ai_model_roles
    ADD CONSTRAINT fk_ai_model_roles_provider_id_ai_providers FOREIGN KEY (provider_id) REFERENCES public.ai_providers(id) ON DELETE CASCADE;


--
-- Name: alert_items fk_alert_items_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_items
    ADD CONSTRAINT fk_alert_items_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: alert_items fk_alert_items_receiver_id_alertmanager_receivers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alert_items
    ADD CONSTRAINT fk_alert_items_receiver_id_alertmanager_receivers FOREIGN KEY (receiver_id) REFERENCES public.alertmanager_receivers(id) ON DELETE SET NULL;


--
-- Name: alertmanager_receivers fk_alertmanager_receivers_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertmanager_receivers
    ADD CONSTRAINT fk_alertmanager_receivers_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: alertmanager_receivers fk_alertmanager_receivers_resolve_state; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alertmanager_receivers
    ADD CONSTRAINT fk_alertmanager_receivers_resolve_state FOREIGN KEY (resolve_state_id) REFERENCES public.states(id) ON DELETE SET NULL;


--
-- Name: api_tokens fk_api_tokens_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.api_tokens
    ADD CONSTRAINT fk_api_tokens_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: approval_requests fk_approval_requests_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT fk_approval_requests_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: approval_requests fk_approval_requests_requested_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT fk_approval_requests_requested_by_users FOREIGN KEY (requested_by) REFERENCES public.users(id);


--
-- Name: approval_requests fk_approval_requests_to_state_id_states; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT fk_approval_requests_to_state_id_states FOREIGN KEY (to_state_id) REFERENCES public.states(id);


--
-- Name: approval_requests fk_approval_requests_transition_id_workflow_transitions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_requests
    ADD CONSTRAINT fk_approval_requests_transition_id_workflow_transitions FOREIGN KEY (transition_id) REFERENCES public.workflow_transitions(id) ON DELETE SET NULL;


--
-- Name: approval_votes fk_approval_votes_request_id_approval_requests; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_votes
    ADD CONSTRAINT fk_approval_votes_request_id_approval_requests FOREIGN KEY (request_id) REFERENCES public.approval_requests(id) ON DELETE CASCADE;


--
-- Name: approval_votes fk_approval_votes_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approval_votes
    ADD CONSTRAINT fk_approval_votes_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id);


--
-- Name: attachment_move_jobs fk_attachment_move_jobs_source_host_id_storage_hosts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment_move_jobs
    ADD CONSTRAINT fk_attachment_move_jobs_source_host_id_storage_hosts FOREIGN KEY (source_host_id) REFERENCES public.storage_hosts(id) ON DELETE CASCADE;


--
-- Name: attachment_move_jobs fk_attachment_move_jobs_target_host_id_storage_hosts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachment_move_jobs
    ADD CONSTRAINT fk_attachment_move_jobs_target_host_id_storage_hosts FOREIGN KEY (target_host_id) REFERENCES public.storage_hosts(id) ON DELETE CASCADE;


--
-- Name: attachments fk_attachments_storage_host_id_storage_hosts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attachments
    ADD CONSTRAINT fk_attachments_storage_host_id_storage_hosts FOREIGN KEY (storage_host_id) REFERENCES public.storage_hosts(id) ON DELETE RESTRICT;


--
-- Name: automation_runs fk_automation_runs_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT fk_automation_runs_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: automation_runs fk_automation_runs_automation_id_automations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_runs
    ADD CONSTRAINT fk_automation_runs_automation_id_automations FOREIGN KEY (automation_id) REFERENCES public.automations(id) ON DELETE CASCADE;


--
-- Name: automation_schedule_state fk_automation_schedule_state_automation_id_automations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_schedule_state
    ADD CONSTRAINT fk_automation_schedule_state_automation_id_automations FOREIGN KEY (automation_id) REFERENCES public.automations(id) ON DELETE CASCADE;


--
-- Name: automation_triggers fk_automation_triggers_automation_id_automations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_triggers
    ADD CONSTRAINT fk_automation_triggers_automation_id_automations FOREIGN KEY (automation_id) REFERENCES public.automations(id) ON DELETE CASCADE;


--
-- Name: automation_validations fk_automation_validations_automation_id_automations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_validations
    ADD CONSTRAINT fk_automation_validations_automation_id_automations FOREIGN KEY (automation_id) REFERENCES public.automations(id) ON DELETE CASCADE;


--
-- Name: automation_versions fk_automation_versions_automation_id_automations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_versions
    ADD CONSTRAINT fk_automation_versions_automation_id_automations FOREIGN KEY (automation_id) REFERENCES public.automations(id) ON DELETE CASCADE;


--
-- Name: automation_versions fk_automation_versions_created_by_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.automation_versions
    ADD CONSTRAINT fk_automation_versions_created_by_id_users FOREIGN KEY (created_by_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: backup_runs fk_backup_runs_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_runs
    ADD CONSTRAINT fk_backup_runs_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: backup_runs fk_backup_runs_schedule_id_backup_schedules; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_runs
    ADD CONSTRAINT fk_backup_runs_schedule_id_backup_schedules FOREIGN KEY (schedule_id) REFERENCES public.backup_schedules(id) ON DELETE SET NULL;


--
-- Name: backup_schedules fk_backup_schedules_created_by_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.backup_schedules
    ADD CONSTRAINT fk_backup_schedules_created_by_id_users FOREIGN KEY (created_by_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: comment_visibility_teams fk_comment_visibility_teams_comment_id_comments; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment_visibility_teams
    ADD CONSTRAINT fk_comment_visibility_teams_comment_id_comments FOREIGN KEY (comment_id) REFERENCES public.comments(id) ON DELETE CASCADE;


--
-- Name: comment_visibility_teams fk_comment_visibility_teams_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comment_visibility_teams
    ADD CONSTRAINT fk_comment_visibility_teams_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: comments fk_comments_author_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT fk_comments_author_id_users FOREIGN KEY (author_id) REFERENCES public.users(id);


--
-- Name: comments fk_comments_resolved_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT fk_comments_resolved_by_users FOREIGN KEY (resolved_by) REFERENCES public.users(id);


--
-- Name: comments fk_comments_thread; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.comments
    ADD CONSTRAINT fk_comments_thread FOREIGN KEY (parent_comment_id) REFERENCES public.comments(id) ON DELETE CASCADE;


--
-- Name: confluence_import_records fk_confluence_import_records_run_id_confluence_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_import_records
    ADD CONSTRAINT fk_confluence_import_records_run_id_confluence_runs FOREIGN KEY (run_id) REFERENCES public.confluence_runs(id) ON DELETE CASCADE;


--
-- Name: confluence_pending_refs fk_confluence_pending_refs_run_id_confluence_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_pending_refs
    ADD CONSTRAINT fk_confluence_pending_refs_run_id_confluence_runs FOREIGN KEY (run_id) REFERENCES public.confluence_runs(id) ON DELETE SET NULL;


--
-- Name: confluence_pending_refs fk_confluence_pending_refs_source_page_id_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_pending_refs
    ADD CONSTRAINT fk_confluence_pending_refs_source_page_id_pages FOREIGN KEY (source_page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: confluence_plans fk_confluence_plans_snapshot_id_confluence_snapshots; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_plans
    ADD CONSTRAINT fk_confluence_plans_snapshot_id_confluence_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.confluence_snapshots(id) ON DELETE CASCADE;


--
-- Name: confluence_runs fk_confluence_runs_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_runs
    ADD CONSTRAINT fk_confluence_runs_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: confluence_runs fk_confluence_runs_plan_id_confluence_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_runs
    ADD CONSTRAINT fk_confluence_runs_plan_id_confluence_plans FOREIGN KEY (plan_id) REFERENCES public.confluence_plans(id) ON DELETE SET NULL;


--
-- Name: confluence_runs fk_confluence_runs_snapshot_id_confluence_snapshots; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_runs
    ADD CONSTRAINT fk_confluence_runs_snapshot_id_confluence_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.confluence_snapshots(id) ON DELETE SET NULL;


--
-- Name: confluence_snapshot_attachments fk_confluence_snapshot_attachments_snapshot_id_confluen_6f0e; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshot_attachments
    ADD CONSTRAINT fk_confluence_snapshot_attachments_snapshot_id_confluen_6f0e FOREIGN KEY (snapshot_id) REFERENCES public.confluence_snapshots(id) ON DELETE CASCADE;


--
-- Name: confluence_snapshot_comments fk_confluence_snapshot_comments_snapshot_id_confluence__14be; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshot_comments
    ADD CONSTRAINT fk_confluence_snapshot_comments_snapshot_id_confluence__14be FOREIGN KEY (snapshot_id) REFERENCES public.confluence_snapshots(id) ON DELETE CASCADE;


--
-- Name: confluence_snapshot_pages fk_confluence_snapshot_pages_snapshot_id_confluence_snapshots; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshot_pages
    ADD CONSTRAINT fk_confluence_snapshot_pages_snapshot_id_confluence_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.confluence_snapshots(id) ON DELETE CASCADE;


--
-- Name: confluence_snapshots fk_confluence_snapshots_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshots
    ADD CONSTRAINT fk_confluence_snapshots_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: confluence_snapshots fk_confluence_snapshots_connection_id_confluence_connections; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.confluence_snapshots
    ADD CONSTRAINT fk_confluence_snapshots_connection_id_confluence_connections FOREIGN KEY (connection_id) REFERENCES public.confluence_connections(id) ON DELETE SET NULL;


--
-- Name: csat_surveys fk_csat_surveys_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.csat_surveys
    ADD CONSTRAINT fk_csat_surveys_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: cycle_teams fk_cycle_teams_cycle_id_cycles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_teams
    ADD CONSTRAINT fk_cycle_teams_cycle_id_cycles FOREIGN KEY (cycle_id) REFERENCES public.cycles(id) ON DELETE CASCADE;


--
-- Name: cycle_teams fk_cycle_teams_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_teams
    ADD CONSTRAINT fk_cycle_teams_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: cycles fk_cycles_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycles
    ADD CONSTRAINT fk_cycles_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: dashboard_widgets fk_dashboard_widgets_dashboard_id_dashboards; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboard_widgets
    ADD CONSTRAINT fk_dashboard_widgets_dashboard_id_dashboards FOREIGN KEY (dashboard_id) REFERENCES public.dashboards(id) ON DELETE CASCADE;


--
-- Name: dashboards fk_dashboards_owner_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.dashboards
    ADD CONSTRAINT fk_dashboards_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id);


--
-- Name: page_versions fk_doc_page_versions_author_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_versions
    ADD CONSTRAINT fk_doc_page_versions_author_id_users FOREIGN KEY (author_id) REFERENCES public.users(id);


--
-- Name: page_versions fk_doc_page_versions_page_id_doc_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_versions
    ADD CONSTRAINT fk_doc_page_versions_page_id_doc_pages FOREIGN KEY (page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: pages fk_doc_pages_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT fk_doc_pages_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: pages fk_doc_pages_parent_id_doc_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT fk_doc_pages_parent_id_doc_pages FOREIGN KEY (parent_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: pages fk_doc_pages_space_id_doc_spaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT fk_doc_pages_space_id_doc_spaces FOREIGN KEY (space_id) REFERENCES public.page_spaces(id) ON DELETE CASCADE;


--
-- Name: pages fk_doc_pages_updated_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pages
    ADD CONSTRAINT fk_doc_pages_updated_by_users FOREIGN KEY (updated_by) REFERENCES public.users(id);


--
-- Name: field_definition_projects fk_field_definition_projects_field_id_field_definitions; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_definition_projects
    ADD CONSTRAINT fk_field_definition_projects_field_id_field_definitions FOREIGN KEY (field_id) REFERENCES public.field_definitions(id) ON DELETE CASCADE;


--
-- Name: field_definition_projects fk_field_definition_projects_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.field_definition_projects
    ADD CONSTRAINT fk_field_definition_projects_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: forgejo_repos fk_forgejo_repos_connection_id_forgejo_connections; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forgejo_repos
    ADD CONSTRAINT fk_forgejo_repos_connection_id_forgejo_connections FOREIGN KEY (connection_id) REFERENCES public.forgejo_connections(id) ON DELETE CASCADE;


--
-- Name: forgejo_repos fk_forgejo_repos_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forgejo_repos
    ADD CONSTRAINT fk_forgejo_repos_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: forgejo_repos fk_forgejo_repos_time_category_id_work_categories; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forgejo_repos
    ADD CONSTRAINT fk_forgejo_repos_time_category_id_work_categories FOREIGN KEY (time_category_id) REFERENCES public.work_categories(id) ON DELETE SET NULL;


--
-- Name: form_shares fk_form_shares_form_id_forms; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.form_shares
    ADD CONSTRAINT fk_form_shares_form_id_forms FOREIGN KEY (form_id) REFERENCES public.forms(id) ON DELETE CASCADE;


--
-- Name: form_shares fk_form_shares_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.form_shares
    ADD CONSTRAINT fk_form_shares_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: form_shares fk_form_shares_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.form_shares
    ADD CONSTRAINT fk_form_shares_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: forms fk_forms_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forms
    ADD CONSTRAINT fk_forms_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: github_repos fk_github_repos_connection_id_github_connections; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_repos
    ADD CONSTRAINT fk_github_repos_connection_id_github_connections FOREIGN KEY (connection_id) REFERENCES public.github_connections(id) ON DELETE CASCADE;


--
-- Name: github_repos fk_github_repos_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_repos
    ADD CONSTRAINT fk_github_repos_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: github_repos fk_github_repos_time_category_id_work_categories; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.github_repos
    ADD CONSTRAINT fk_github_repos_time_category_id_work_categories FOREIGN KEY (time_category_id) REFERENCES public.work_categories(id) ON DELETE SET NULL;


--
-- Name: gitlab_repos fk_gitlab_repos_connection_id_gitlab_connections; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gitlab_repos
    ADD CONSTRAINT fk_gitlab_repos_connection_id_gitlab_connections FOREIGN KEY (connection_id) REFERENCES public.gitlab_connections(id) ON DELETE CASCADE;


--
-- Name: gitlab_repos fk_gitlab_repos_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gitlab_repos
    ADD CONSTRAINT fk_gitlab_repos_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: gitlab_repos fk_gitlab_repos_time_category_id_work_categories; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.gitlab_repos
    ADD CONSTRAINT fk_gitlab_repos_time_category_id_work_categories FOREIGN KEY (time_category_id) REFERENCES public.work_categories(id) ON DELETE SET NULL;


--
-- Name: global_role_grants fk_global_role_grants_granted_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT fk_global_role_grants_granted_by_users FOREIGN KEY (granted_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: global_role_grants fk_global_role_grants_group_id_groups; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT fk_global_role_grants_group_id_groups FOREIGN KEY (group_id) REFERENCES public.groups(id) ON DELETE CASCADE;


--
-- Name: global_role_grants fk_global_role_grants_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT fk_global_role_grants_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: global_role_grants fk_global_role_grants_role_id_roles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT fk_global_role_grants_role_id_roles FOREIGN KEY (role_id) REFERENCES public.roles(id);


--
-- Name: global_role_grants fk_global_role_grants_space_id_page_spaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT fk_global_role_grants_space_id_page_spaces FOREIGN KEY (space_id) REFERENCES public.page_spaces(id) ON DELETE CASCADE;


--
-- Name: global_role_grants fk_global_role_grants_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT fk_global_role_grants_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: global_role_grants fk_global_role_grants_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.global_role_grants
    ADD CONSTRAINT fk_global_role_grants_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: group_members fk_group_members_group_id_groups; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_members
    ADD CONSTRAINT fk_group_members_group_id_groups FOREIGN KEY (group_id) REFERENCES public.groups(id) ON DELETE CASCADE;


--
-- Name: group_members fk_group_members_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_members
    ADD CONSTRAINT fk_group_members_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: group_parents fk_group_parents_child_id_groups; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_parents
    ADD CONSTRAINT fk_group_parents_child_id_groups FOREIGN KEY (child_id) REFERENCES public.groups(id) ON DELETE CASCADE;


--
-- Name: group_parents fk_group_parents_parent_id_groups; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_parents
    ADD CONSTRAINT fk_group_parents_parent_id_groups FOREIGN KEY (parent_id) REFERENCES public.groups(id) ON DELETE CASCADE;


--
-- Name: issue_types fk_issue_types_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.issue_types
    ADD CONSTRAINT fk_issue_types_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: item_cycle_records fk_item_cycle_records_cycle_id_cycles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_cycle_records
    ADD CONSTRAINT fk_item_cycle_records_cycle_id_cycles FOREIGN KEY (cycle_id) REFERENCES public.cycles(id) ON DELETE CASCADE;


--
-- Name: item_cycle_records fk_item_cycle_records_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_cycle_records
    ADD CONSTRAINT fk_item_cycle_records_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_page_links fk_item_doc_links_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_page_links
    ADD CONSTRAINT fk_item_doc_links_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: item_page_links fk_item_doc_links_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_page_links
    ADD CONSTRAINT fk_item_doc_links_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_page_links fk_item_doc_links_page_id_doc_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_page_links
    ADD CONSTRAINT fk_item_doc_links_page_id_doc_pages FOREIGN KEY (page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: item_estimates fk_item_estimates_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_estimates
    ADD CONSTRAINT fk_item_estimates_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_key_aliases fk_item_key_aliases_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_key_aliases
    ADD CONSTRAINT fk_item_key_aliases_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_labels fk_item_labels_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_labels
    ADD CONSTRAINT fk_item_labels_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_labels fk_item_labels_label_id_labels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_labels
    ADD CONSTRAINT fk_item_labels_label_id_labels FOREIGN KEY (label_id) REFERENCES public.labels(id) ON DELETE CASCADE;


--
-- Name: item_link_type_projects fk_item_link_type_projects_link_type_id_item_link_types; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link_type_projects
    ADD CONSTRAINT fk_item_link_type_projects_link_type_id_item_link_types FOREIGN KEY (link_type_id) REFERENCES public.item_link_types(id) ON DELETE CASCADE;


--
-- Name: item_link_type_projects fk_item_link_type_projects_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_link_type_projects
    ADD CONSTRAINT fk_item_link_type_projects_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: item_links fk_item_links_source_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_links
    ADD CONSTRAINT fk_item_links_source_item_id_work_items FOREIGN KEY (source_item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_links fk_item_links_target_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_links
    ADD CONSTRAINT fk_item_links_target_item_id_work_items FOREIGN KEY (target_item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_participants fk_item_participants_added_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_participants
    ADD CONSTRAINT fk_item_participants_added_by_users FOREIGN KEY (added_by) REFERENCES public.users(id);


--
-- Name: item_participants fk_item_participants_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_participants
    ADD CONSTRAINT fk_item_participants_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_participants fk_item_participants_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_participants
    ADD CONSTRAINT fk_item_participants_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: item_participants fk_item_participants_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_participants
    ADD CONSTRAINT fk_item_participants_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: item_stars fk_item_stars_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_stars
    ADD CONSTRAINT fk_item_stars_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_stars fk_item_stars_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_stars
    ADD CONSTRAINT fk_item_stars_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: item_vcs_links fk_item_vcs_links_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_vcs_links
    ADD CONSTRAINT fk_item_vcs_links_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_watchers fk_item_watchers_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_watchers
    ADD CONSTRAINT fk_item_watchers_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: item_web_links fk_item_web_links_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.item_web_links
    ADD CONSTRAINT fk_item_web_links_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: jira_import_records fk_jira_import_records_run_id_jira_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_import_records
    ADD CONSTRAINT fk_jira_import_records_run_id_jira_runs FOREIGN KEY (run_id) REFERENCES public.jira_runs(id) ON DELETE CASCADE;


--
-- Name: jira_pending_refs fk_jira_pending_refs_run_id_jira_runs; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_pending_refs
    ADD CONSTRAINT fk_jira_pending_refs_run_id_jira_runs FOREIGN KEY (run_id) REFERENCES public.jira_runs(id) ON DELETE SET NULL;


--
-- Name: jira_pending_refs fk_jira_pending_refs_source_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_pending_refs
    ADD CONSTRAINT fk_jira_pending_refs_source_item_id_work_items FOREIGN KEY (source_item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: jira_plans fk_jira_plans_radd_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_plans
    ADD CONSTRAINT fk_jira_plans_radd_project_id_projects FOREIGN KEY (radd_project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: jira_plans fk_jira_plans_snapshot_id_jira_snapshots; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_plans
    ADD CONSTRAINT fk_jira_plans_snapshot_id_jira_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.jira_snapshots(id) ON DELETE CASCADE;


--
-- Name: jira_runs fk_jira_runs_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_runs
    ADD CONSTRAINT fk_jira_runs_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: jira_runs fk_jira_runs_plan_id_jira_plans; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_runs
    ADD CONSTRAINT fk_jira_runs_plan_id_jira_plans FOREIGN KEY (plan_id) REFERENCES public.jira_plans(id) ON DELETE SET NULL;


--
-- Name: jira_runs fk_jira_runs_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_runs
    ADD CONSTRAINT fk_jira_runs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: jira_runs fk_jira_runs_snapshot_id_jira_snapshots; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_runs
    ADD CONSTRAINT fk_jira_runs_snapshot_id_jira_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.jira_snapshots(id) ON DELETE SET NULL;


--
-- Name: jira_snapshot_blobs fk_jira_snapshot_blobs_snapshot_id_jira_snapshots; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_snapshot_blobs
    ADD CONSTRAINT fk_jira_snapshot_blobs_snapshot_id_jira_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.jira_snapshots(id) ON DELETE CASCADE;


--
-- Name: jira_snapshot_issues fk_jira_snapshot_issues_snapshot_id_jira_snapshots; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_snapshot_issues
    ADD CONSTRAINT fk_jira_snapshot_issues_snapshot_id_jira_snapshots FOREIGN KEY (snapshot_id) REFERENCES public.jira_snapshots(id) ON DELETE CASCADE;


--
-- Name: jira_snapshots fk_jira_snapshots_actor_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_snapshots
    ADD CONSTRAINT fk_jira_snapshots_actor_id_users FOREIGN KEY (actor_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: jira_snapshots fk_jira_snapshots_connection_id_jira_connections; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.jira_snapshots
    ADD CONSTRAINT fk_jira_snapshots_connection_id_jira_connections FOREIGN KEY (connection_id) REFERENCES public.jira_connections(id) ON DELETE SET NULL;


--
-- Name: leave_periods fk_leave_periods_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leave_periods
    ADD CONSTRAINT fk_leave_periods_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: leave_periods fk_leave_periods_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leave_periods
    ADD CONSTRAINT fk_leave_periods_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: mail_contacts fk_mail_contacts_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_contacts
    ADD CONSTRAINT fk_mail_contacts_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: mail_messages fk_mail_messages_comment_id_comments; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_messages
    ADD CONSTRAINT fk_mail_messages_comment_id_comments FOREIGN KEY (comment_id) REFERENCES public.comments(id) ON DELETE SET NULL;


--
-- Name: mail_messages fk_mail_messages_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_messages
    ADD CONSTRAINT fk_mail_messages_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: mail_messages fk_mail_messages_raw_host_id_storage_hosts; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_messages
    ADD CONSTRAINT fk_mail_messages_raw_host_id_storage_hosts FOREIGN KEY (raw_host_id) REFERENCES public.storage_hosts(id) ON DELETE SET NULL;


--
-- Name: mail_messages fk_mail_messages_source_id_mail_sources; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_messages
    ADD CONSTRAINT fk_mail_messages_source_id_mail_sources FOREIGN KEY (source_id) REFERENCES public.mail_sources(id) ON DELETE SET NULL;


--
-- Name: mail_rules fk_mail_rules_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_rules
    ADD CONSTRAINT fk_mail_rules_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: mail_rules fk_mail_rules_source_id_mail_sources; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_rules
    ADD CONSTRAINT fk_mail_rules_source_id_mail_sources FOREIGN KEY (source_id) REFERENCES public.mail_sources(id) ON DELETE CASCADE;


--
-- Name: mail_sources fk_mail_sources_default_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_sources
    ADD CONSTRAINT fk_mail_sources_default_project_id_projects FOREIGN KEY (default_project_id) REFERENCES public.projects(id) ON DELETE SET NULL;


--
-- Name: mail_sources fk_mail_sources_sender_id_mail_senders; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mail_sources
    ADD CONSTRAINT fk_mail_sources_sender_id_mail_senders FOREIGN KEY (sender_id) REFERENCES public.mail_senders(id) ON DELETE SET NULL;


--
-- Name: mfa_enrollment_tickets fk_mfa_enrollment_tickets_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.mfa_enrollment_tickets
    ADD CONSTRAINT fk_mfa_enrollment_tickets_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: milestones fk_milestones_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.milestones
    ADD CONSTRAINT fk_milestones_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: page_collab_docs fk_page_collab_docs_page_id_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_collab_docs
    ADD CONSTRAINT fk_page_collab_docs_page_id_pages FOREIGN KEY (page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: page_labels fk_page_labels_label_id_labels; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_labels
    ADD CONSTRAINT fk_page_labels_label_id_labels FOREIGN KEY (label_id) REFERENCES public.labels(id) ON DELETE CASCADE;


--
-- Name: page_labels fk_page_labels_page_id_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_labels
    ADD CONSTRAINT fk_page_labels_page_id_pages FOREIGN KEY (page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: page_links fk_page_links_source_page_id_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_links
    ADD CONSTRAINT fk_page_links_source_page_id_pages FOREIGN KEY (source_page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: page_links fk_page_links_target_page_id_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_links
    ADD CONSTRAINT fk_page_links_target_page_id_pages FOREIGN KEY (target_page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: page_path_history fk_page_path_history_page_id_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_path_history
    ADD CONSTRAINT fk_page_path_history_page_id_pages FOREIGN KEY (page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: page_path_history fk_page_path_history_space_id_page_spaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_path_history
    ADD CONSTRAINT fk_page_path_history_space_id_page_spaces FOREIGN KEY (space_id) REFERENCES public.page_spaces(id) ON DELETE CASCADE;


--
-- Name: page_templates fk_page_templates_created_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_templates
    ADD CONSTRAINT fk_page_templates_created_by_users FOREIGN KEY (created_by) REFERENCES public.users(id);


--
-- Name: page_templates fk_page_templates_space_id_page_spaces; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_templates
    ADD CONSTRAINT fk_page_templates_space_id_page_spaces FOREIGN KEY (space_id) REFERENCES public.page_spaces(id) ON DELETE CASCADE;


--
-- Name: page_watchers fk_page_watchers_page_id_pages; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.page_watchers
    ADD CONSTRAINT fk_page_watchers_page_id_pages FOREIGN KEY (page_id) REFERENCES public.pages(id) ON DELETE CASCADE;


--
-- Name: project_timelogging fk_project_timelogging_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.project_timelogging
    ADD CONSTRAINT fk_project_timelogging_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: releases fk_releases_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.releases
    ADD CONSTRAINT fk_releases_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: screen_fields fk_screen_fields_screen_id_screens; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screen_fields
    ADD CONSTRAINT fk_screen_fields_screen_id_screens FOREIGN KEY (screen_id) REFERENCES public.screens(id) ON DELETE CASCADE;


--
-- Name: screens fk_screens_issue_type_id_issue_types; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screens
    ADD CONSTRAINT fk_screens_issue_type_id_issue_types FOREIGN KEY (issue_type_id) REFERENCES public.issue_types(id) ON DELETE CASCADE;


--
-- Name: screens fk_screens_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.screens
    ADD CONSTRAINT fk_screens_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: search_index fk_search_index_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.search_index
    ADD CONSTRAINT fk_search_index_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: sessions fk_sessions_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT fk_sessions_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: sessions fk_sessions_view_as_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT fk_sessions_view_as_user_id_users FOREIGN KEY (view_as_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: sla_item_states fk_sla_item_states_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_item_states
    ADD CONSTRAINT fk_sla_item_states_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: sla_item_states fk_sla_item_states_policy_id_sla_policies; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_item_states
    ADD CONSTRAINT fk_sla_item_states_policy_id_sla_policies FOREIGN KEY (policy_id) REFERENCES public.sla_policies(id) ON DELETE CASCADE;


--
-- Name: sla_policies fk_sla_policies_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sla_policies
    ADD CONSTRAINT fk_sla_policies_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: sso_provider_default_grants fk_sso_provider_default_grants_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_grants
    ADD CONSTRAINT fk_sso_provider_default_grants_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: sso_provider_default_grants fk_sso_provider_default_grants_role_id_roles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_grants
    ADD CONSTRAINT fk_sso_provider_default_grants_role_id_roles FOREIGN KEY (role_id) REFERENCES public.roles(id) ON DELETE CASCADE;


--
-- Name: sso_provider_default_grants fk_sso_provider_default_grants_rule_id_sso_provisioning_rules; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_grants
    ADD CONSTRAINT fk_sso_provider_default_grants_rule_id_sso_provisioning_rules FOREIGN KEY (rule_id) REFERENCES public.sso_provisioning_rules(id) ON DELETE CASCADE;


--
-- Name: sso_provider_default_teams fk_sso_provider_default_teams_rule_id_sso_provisioning_rules; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_teams
    ADD CONSTRAINT fk_sso_provider_default_teams_rule_id_sso_provisioning_rules FOREIGN KEY (rule_id) REFERENCES public.sso_provisioning_rules(id) ON DELETE CASCADE;


--
-- Name: sso_provider_default_teams fk_sso_provider_default_teams_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provider_default_teams
    ADD CONSTRAINT fk_sso_provider_default_teams_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: sso_provisioning_rules fk_sso_provisioning_rules_provider_id_sso_providers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sso_provisioning_rules
    ADD CONSTRAINT fk_sso_provisioning_rules_provider_id_sso_providers FOREIGN KEY (provider_id) REFERENCES public.sso_providers(id) ON DELETE CASCADE;


--
-- Name: states fk_states_category_key_state_categories; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT fk_states_category_key_state_categories FOREIGN KEY (category_key) REFERENCES public.state_categories(key);


--
-- Name: states fk_states_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.states
    ADD CONSTRAINT fk_states_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: team_assignment_cursors fk_team_assignment_cursors_last_assigned_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_assignment_cursors
    ADD CONSTRAINT fk_team_assignment_cursors_last_assigned_user_id_users FOREIGN KEY (last_assigned_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: team_assignment_cursors fk_team_assignment_cursors_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_assignment_cursors
    ADD CONSTRAINT fk_team_assignment_cursors_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: team_managers fk_team_managers_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_managers
    ADD CONSTRAINT fk_team_managers_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: team_managers fk_team_managers_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_managers
    ADD CONSTRAINT fk_team_managers_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: team_members fk_team_members_group_id_groups; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT fk_team_members_group_id_groups FOREIGN KEY (group_id) REFERENCES public.groups(id) ON DELETE CASCADE;


--
-- Name: team_members fk_team_members_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT fk_team_members_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id) ON DELETE CASCADE;


--
-- Name: team_members fk_team_members_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.team_members
    ADD CONSTRAINT fk_team_members_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: teams fk_teams_owner_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.teams
    ADD CONSTRAINT fk_teams_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: thread_resolution_rules fk_thread_resolution_rules_issue_type_id_issue_types; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_resolution_rules
    ADD CONSTRAINT fk_thread_resolution_rules_issue_type_id_issue_types FOREIGN KEY (issue_type_id) REFERENCES public.issue_types(id) ON DELETE CASCADE;


--
-- Name: thread_resolution_rules fk_thread_resolution_rules_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.thread_resolution_rules
    ADD CONSTRAINT fk_thread_resolution_rules_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: totp_recovery_codes fk_totp_recovery_codes_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.totp_recovery_codes
    ADD CONSTRAINT fk_totp_recovery_codes_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_identities fk_user_identities_provider_id_sso_providers; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_identities
    ADD CONSTRAINT fk_user_identities_provider_id_sso_providers FOREIGN KEY (provider_id) REFERENCES public.sso_providers(id) ON DELETE CASCADE;


--
-- Name: user_identities fk_user_identities_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_identities
    ADD CONSTRAINT fk_user_identities_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: user_totp fk_user_totp_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_totp
    ADD CONSTRAINT fk_user_totp_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: vcs_pending_worklogs fk_vcs_pending_worklogs_category_id_work_categories; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_pending_worklogs
    ADD CONSTRAINT fk_vcs_pending_worklogs_category_id_work_categories FOREIGN KEY (category_id) REFERENCES public.work_categories(id) ON DELETE SET NULL;


--
-- Name: vcs_pending_worklogs fk_vcs_pending_worklogs_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_pending_worklogs
    ADD CONSTRAINT fk_vcs_pending_worklogs_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: vcs_user_links fk_vcs_user_links_user_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.vcs_user_links
    ADD CONSTRAINT fk_vcs_user_links_user_id_users FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: view_members fk_view_members_added_by_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.view_members
    ADD CONSTRAINT fk_view_members_added_by_users FOREIGN KEY (added_by) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: view_members fk_view_members_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.view_members
    ADD CONSTRAINT fk_view_members_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: view_members fk_view_members_view_id_views; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.view_members
    ADD CONSTRAINT fk_view_members_view_id_views FOREIGN KEY (view_id) REFERENCES public.views(id) ON DELETE CASCADE;


--
-- Name: views fk_views_owner_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.views
    ADD CONSTRAINT fk_views_owner_id_users FOREIGN KEY (owner_id) REFERENCES public.users(id);


--
-- Name: views fk_views_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.views
    ADD CONSTRAINT fk_views_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: webhook_deliveries fk_webhook_deliveries_endpoint_id_webhook_endpoints; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.webhook_deliveries
    ADD CONSTRAINT fk_webhook_deliveries_endpoint_id_webhook_endpoints FOREIGN KEY (endpoint_id) REFERENCES public.webhook_endpoints(id);


--
-- Name: work_items fk_work_items_assignee_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_assignee_id_users FOREIGN KEY (assignee_id) REFERENCES public.users(id);


--
-- Name: work_items fk_work_items_cycle_id_cycles; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_cycle_id_cycles FOREIGN KEY (cycle_id) REFERENCES public.cycles(id) ON DELETE SET NULL;


--
-- Name: work_items fk_work_items_parent_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_parent_id_work_items FOREIGN KEY (parent_id) REFERENCES public.work_items(id);


--
-- Name: work_items fk_work_items_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id);


--
-- Name: work_items fk_work_items_release_id_releases; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_release_id_releases FOREIGN KEY (release_id) REFERENCES public.releases(id) ON DELETE SET NULL;


--
-- Name: work_items fk_work_items_reporter_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_reporter_id_users FOREIGN KEY (reporter_id) REFERENCES public.users(id);


--
-- Name: work_items fk_work_items_state_id_states; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_state_id_states FOREIGN KEY (state_id) REFERENCES public.states(id);


--
-- Name: work_items fk_work_items_team_id_teams; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_team_id_teams FOREIGN KEY (team_id) REFERENCES public.teams(id);


--
-- Name: work_items fk_work_items_type_id_issue_types; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.work_items
    ADD CONSTRAINT fk_work_items_type_id_issue_types FOREIGN KEY (type_id) REFERENCES public.issue_types(id) ON DELETE SET NULL;


--
-- Name: workflow_transitions fk_workflow_transitions_from_state_id_states; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_transitions
    ADD CONSTRAINT fk_workflow_transitions_from_state_id_states FOREIGN KEY (from_state_id) REFERENCES public.states(id);


--
-- Name: workflow_transitions fk_workflow_transitions_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_transitions
    ADD CONSTRAINT fk_workflow_transitions_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- Name: workflow_transitions fk_workflow_transitions_to_state_id_states; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_transitions
    ADD CONSTRAINT fk_workflow_transitions_to_state_id_states FOREIGN KEY (to_state_id) REFERENCES public.states(id);


--
-- Name: worklogs fk_worklogs_author_id_users; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT fk_worklogs_author_id_users FOREIGN KEY (author_id) REFERENCES public.users(id);


--
-- Name: worklogs fk_worklogs_category_id_work_categories; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT fk_worklogs_category_id_work_categories FOREIGN KEY (category_id) REFERENCES public.work_categories(id) ON DELETE SET NULL;


--
-- Name: worklogs fk_worklogs_item_id_work_items; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT fk_worklogs_item_id_work_items FOREIGN KEY (item_id) REFERENCES public.work_items(id) ON DELETE CASCADE;


--
-- Name: worklogs fk_worklogs_project_id_projects; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.worklogs
    ADD CONSTRAINT fk_worklogs_project_id_projects FOREIGN KEY (project_id) REFERENCES public.projects(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict FXEF3ro8JEr5tKZwZeIw9VE1pL2F2RuZPfWNpSyvwNjBC66QmdTH8mY3ZixFjiI

