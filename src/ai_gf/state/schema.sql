PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
    sender_ig_id TEXT NOT NULL,
    body TEXT NOT NULL,
    trigger_kind TEXT,
    state_snapshot_id INTEGER REFERENCES state_snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);
CREATE INDEX IF NOT EXISTS idx_messages_direction_ts ON messages(direction, ts);

CREATE TABLE IF NOT EXISTS state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    affection INTEGER NOT NULL DEFAULT 50 CHECK (affection BETWEEN 0 AND 100),
    jealousy INTEGER NOT NULL DEFAULT 0 CHECK (jealousy BETWEEN 0 AND 100),
    mood TEXT NOT NULL DEFAULT 'neutral' CHECK (mood IN ('happy','neutral','upset','cold')),
    last_user_msg_at TIMESTAMP,
    last_proactive_at TIMESTAMP,
    last_proactive_kind TEXT,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO state (id, affection, jealousy, mood) VALUES (1, 50, 0, 'neutral');

CREATE TABLE IF NOT EXISTS state_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    affection INTEGER NOT NULL,
    jealousy INTEGER NOT NULL,
    mood TEXT NOT NULL,
    reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_state_snapshots_ts ON state_snapshots(ts);

CREATE TABLE IF NOT EXISTS summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    summary_text TEXT NOT NULL,
    covers_until_message_id INTEGER NOT NULL REFERENCES messages(id),
    superseded INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_summary_active ON summary(superseded, ts);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
