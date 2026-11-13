CREATE TABLE route_cache (
    cache_key TEXT PRIMARY KEY,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    mode TEXT NOT NULL,
    provider TEXT NOT NULL,
    distance_meters INTEGER,
    duration_minutes INTEGER,
    source TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    route_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    itinerary_id TEXT,
    correlation_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('completed','fallback','failed')),
    model TEXT,
    policy_version TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    error TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL
);

CREATE TABLE replan_proposals (
    id TEXT PRIMARY KEY,
    itinerary_id TEXT NOT NULL REFERENCES itineraries(id),
    base_version_id TEXT NOT NULL REFERENCES itinerary_versions(id),
    event_type TEXT NOT NULL,
    event_json TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','confirmed','rejected','expired')),
    idempotency_key TEXT UNIQUE,
    confirmed_version_id TEXT REFERENCES itinerary_versions(id),
    created_at TEXT NOT NULL
);

CREATE TABLE feedback_events (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    itinerary_id TEXT,
    proposal_id TEXT,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    label TEXT NOT NULL CHECK(label IN ('accepted','rejected','skipped','reported')),
    reason_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE strategy_releases (
    version TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK(status IN ('candidate','approved','rejected','retired')),
    metrics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    approved_at TEXT
);

CREATE INDEX idx_agent_runs_itinerary ON agent_runs(itinerary_id, started_at);
CREATE INDEX idx_replan_proposals_itinerary ON replan_proposals(itinerary_id, created_at);
CREATE INDEX idx_feedback_target ON feedback_events(target_type, target_id, created_at);
