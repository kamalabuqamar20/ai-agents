-- institutions.sql
-- Stores places where a person has worked or studied.
-- This is the top level of the resume hierarchy:
--   institutions → positions → experiences → skills
--
-- Each institution gets a unique ID automatically (AUTOINCREMENT).
-- You never need to set inst_id yourself — SQLite handles it.

CREATE TABLE IF NOT EXISTS institutions (
    inst_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,
    name        TEXT NOT NULL,
    department  TEXT,
    address     TEXT,
    city        TEXT,
    state       TEXT,
    zip         TEXT,
    embedding   TEXT DEFAULT NULL
);