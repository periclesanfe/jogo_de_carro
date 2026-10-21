-- The database. db.migrate runs each "-- migration N" section once, in order, in one transaction, and records
-- N in PRAGMA user_version: append new sections (M3: matches and runs), never edit one that has shipped.

-- migration 1
CREATE TABLE users(
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_hash TEXT,                             -- NULL: Google only
  google_sub TEXT UNIQUE,
  nick TEXT UNIQUE COLLATE NOCASE,          -- NULL until /apelido; permanent after
  role TEXT NOT NULL DEFAULT 'player' CHECK (role IN ('player', 'admin', 'banned')),
  created REAL NOT NULL
);
CREATE TABLE sessions(                      -- id: sha256 of the cookie, never the cookie
  id BLOB PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  expires REAL NOT NULL
);
CREATE INDEX sessions_user ON sessions(user_id);
CREATE TABLE tokens(                        -- emailed links: id is sha256 of the token in the link
  id BLOB PRIMARY KEY,
  email TEXT NOT NULL COLLATE NOCASE,
  expires REAL NOT NULL
);
CREATE INDEX tokens_email ON tokens(email);
CREATE TABLE friends(
  a INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  b INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  asked_by INTEGER NOT NULL,
  accepted INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (a, b),
  CHECK (a < b)
);
CREATE INDEX friends_b ON friends(b);
