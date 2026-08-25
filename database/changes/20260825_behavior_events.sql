-- 新增本地多帧行为风险事件；原始人体关键点不入库。
CREATE TABLE IF NOT EXISTS behavior_events (
    id INTEGER PRIMARY KEY,
    elder_id INTEGER NOT NULL REFERENCES elders(id),
    scene VARCHAR(20) NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    confidence FLOAT NOT NULL,
    score FLOAT NOT NULL,
    evidence JSON NOT NULL,
    source VARCHAR(20) NOT NULL,
    started_at DATETIME NOT NULL,
    ended_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_behavior_events_elder_id ON behavior_events(elder_id);
CREATE INDEX IF NOT EXISTS ix_behavior_events_event_type ON behavior_events(event_type);
