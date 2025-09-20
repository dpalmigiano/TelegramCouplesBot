CREATE TABLE IF NOT EXISTS couples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a_id INTEGER NOT NULL,
    user_b_id INTEGER NOT NULL,
    group_chat_id INTEGER UNIQUE,
    tz TEXT NOT NULL DEFAULT 'UTC',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    sender_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    ts TEXT NOT NULL,
    couple_id INTEGER NOT NULL,
    FOREIGN KEY (couple_id) REFERENCES couples(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_couple_ts ON messages(couple_id, ts);

CREATE TABLE IF NOT EXISTS advice (
    couple_id INTEGER NOT NULL,
    for_user_id INTEGER NOT NULL,
    advice_text TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (couple_id, for_user_id),
    FOREIGN KEY (couple_id) REFERENCES couples(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stats (
    couple_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (couple_id, key),
    FOREIGN KEY (couple_id) REFERENCES couples(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS thresholds (
    couple_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    direction TEXT NOT NULL,
    warn REAL,
    praise REAL,
    PRIMARY KEY (couple_id, key),
    FOREIGN KEY (couple_id) REFERENCES couples(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cooldowns (
    couple_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    metric_key TEXT NOT NULL,
    last_fired TEXT NOT NULL,
    PRIMARY KEY (couple_id, user_id, metric_key),
    FOREIGN KEY (couple_id) REFERENCES couples(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prefs (
    couple_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    dnd_start TEXT,
    dnd_end TEXT,
    enable_alerts INTEGER NOT NULL DEFAULT 1,
    max_neg_per_day INTEGER NOT NULL DEFAULT 5,
    max_pos_per_day INTEGER NOT NULL DEFAULT 8,
    sla_minutes INTEGER NOT NULL DEFAULT 60,
    PRIMARY KEY (couple_id, user_id),
    FOREIGN KEY (couple_id) REFERENCES couples(id) ON DELETE CASCADE
);
