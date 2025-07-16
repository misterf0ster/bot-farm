-- init.sql

CREATE TABLE referral_links (
    id SERIAL PRIMARY KEY,
    url TEXT NOT NULL,
    status TEXT DEFAULT 'actual',
    max_sessions INT DEFAULT 40
);

CREATE TABLE sessions (
    id SERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    session_json JSONB NOT NULL,
    status TEXT DEFAULT 'active',
    reserved_for_referral_id INT NULL
);

CREATE INDEX idx_sessions_reserved ON sessions(reserved_for_referral_id);
