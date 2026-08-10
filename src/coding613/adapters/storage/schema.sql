PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    canonical_root TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS interactive_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_interactive_sessions_project_updated
    ON interactive_sessions(project_id, updated_at DESC, id ASC);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES interactive_sessions(id) ON DELETE SET NULL,
    options_json TEXT NOT NULL DEFAULT '{}',
    task TEXT NOT NULL,
    permission_mode TEXT NOT NULL,
    state TEXT NOT NULL,
    stop_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id);

CREATE TABLE IF NOT EXISTS iterations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    iteration_number INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    UNIQUE(run_id, iteration_number)
);

CREATE INDEX IF NOT EXISTS idx_iterations_run_time ON iterations(run_id, timestamp);

CREATE TABLE IF NOT EXISTS loop_sessions (
    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    session_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_run_time ON events(run_id, timestamp, sequence);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approvals_run ON approvals(run_id, created_at);

CREATE TABLE IF NOT EXISTS task_graphs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    graph_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    artifact_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_entries (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    memory_type TEXT NOT NULL,
    redacted_text TEXT NOT NULL,
    permission_tags_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_project_type ON memory_entries(project_id, memory_type);

CREATE TABLE IF NOT EXISTS permission_rules (
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    pattern TEXT NOT NULL,
    effect TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(project_id, scope, pattern)
);

CREATE INDEX IF NOT EXISTS idx_permission_rules_project_scope
    ON permission_rules(project_id, scope, pattern);

CREATE TABLE IF NOT EXISTS embedding_status (
    memory_id TEXT PRIMARY KEY REFERENCES memory_entries(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    indexed_at TEXT,
    error TEXT
);
