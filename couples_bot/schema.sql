PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS couples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a_id INTEGER NOT NULL,
    user_b_id INTEGER NOT NULL,
    group_chat_id INTEGER UNIQUE NOT NULL,
    tz TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    ts TEXT NOT NULL,
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_couple_ts ON messages(couple_id, ts);

CREATE TABLE IF NOT EXISTS advice (
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    for_user_id INTEGER NOT NULL,
    advice_text TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (couple_id, for_user_id)
);

CREATE TABLE IF NOT EXISTS stats (
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (couple_id, key)
);

CREATE TABLE IF NOT EXISTS thresholds (
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    direction TEXT NOT NULL,
    warn REAL NOT NULL,
    praise REAL,
    PRIMARY KEY (couple_id, key)
);

CREATE TABLE IF NOT EXISTS cooldowns (
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    metric_key TEXT NOT NULL,
    last_fired TEXT NOT NULL,
    PRIMARY KEY (couple_id, user_id, metric_key)
);

CREATE TABLE IF NOT EXISTS prefs (
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL,
    dnd_start TEXT,
    dnd_end TEXT,
    enable_alerts INTEGER DEFAULT 1,
    max_neg_per_day INTEGER DEFAULT 5,
    max_pos_per_day INTEGER DEFAULT 5,
    sla_minutes INTEGER DEFAULT 120,
    PRIMARY KEY (couple_id, user_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_ts INT NOT NULL,
    started_ts INT,
    finished_ts INT,
    status TEXT NOT NULL
        CHECK(status IN ('PENDING','RUNNING','DONE','FAILED'))
        DEFAULT 'PENDING',
    error TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_hash ON jobs(couple_id, payload_hash);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_ts);

CREATE TABLE IF NOT EXISTS reag_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    couple_id INTEGER NOT NULL REFERENCES couples(id) ON DELETE CASCADE,
    window_start_ts INT NOT NULL,
    window_end_ts INT NOT NULL,
    token_in INT,
    token_out INT,
    model TEXT NOT NULL,
    created_ts INT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reag_runs_couple ON reag_runs(couple_id, created_ts DESC);
