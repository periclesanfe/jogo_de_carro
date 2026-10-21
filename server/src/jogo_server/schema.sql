-- The database. db.migrate runs each "-- migration N" section once, in order, in one transaction, and records
-- N in PRAGMA user_version: append new sections, never edit one that has shipped.

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

-- migration 2
CREATE TABLE runs(                          -- ranked runs, as the server simulated them (M4 adds matches)
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('solo', 'live', 'challenge')),
  mode TEXT NOT NULL,
  skin TEXT NOT NULL,
  seed INTEGER NOT NULL,
  shared INTEGER NOT NULL,
  build TEXT NOT NULL,
  started REAL NOT NULL,
  ended REAL,
  ticks INTEGER,
  outcome TEXT,
  score INTEGER,
  seconds REAL,
  client_score INTEGER,                     -- fin.score: only compared (why = 'desync')
  max_lag REAL,
  features TEXT,                            -- json (flags.py), never shown to players
  state TEXT NOT NULL CHECK (state IN ('live', 'ok', 'review', 'rejected')),
  why TEXT,
  log BLOB                                  -- zlib(json {v, ev, arr}); arr: [k, arrival ms after tick 0] per message
);
CREATE INDEX runs_best ON runs(user_id, mode, score DESC, id) WHERE kind = 'solo' AND state = 'ok';
CREATE INDEX runs_user ON runs(user_id);
CREATE INDEX runs_state ON runs(state);  -- the review queue, live runs at startup
CREATE INDEX runs_desync ON runs(ended) WHERE why = 'desync';
CREATE TABLE bests(                         -- the board: each player's best ok solo run per mode, kept by the trigger
  user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  mode TEXT NOT NULL,
  run_id INTEGER NOT NULL,
  score INTEGER NOT NULL,
  seconds REAL NOT NULL,
  PRIMARY KEY (user_id, mode)
);
CREATE INDEX bests_board ON bests(mode, score DESC, run_id);
-- a run that enters or leaves 'ok' (the hub ends it; admin aprovar, rejeitar) sets its player's best again
CREATE TRIGGER runs_bests AFTER UPDATE OF state ON runs WHEN NEW.kind = 'solo' AND 'ok' IN (OLD.state, NEW.state)
BEGIN
  DELETE FROM bests WHERE user_id = NEW.user_id AND mode = NEW.mode;
  INSERT INTO bests SELECT user_id, mode, id, score, seconds FROM runs
    WHERE kind = 'solo' AND state = 'ok' AND user_id = NEW.user_id AND mode = NEW.mode ORDER BY score DESC, id LIMIT 1;
END;

-- migration 3
CREATE TABLE matches(                       -- a live race between two friends (M5 adds challenges)
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('live', 'challenge')),
  mode TEXT NOT NULL,
  seed INTEGER NOT NULL,
  a INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,  -- who invited
  b INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('racing', 'open', 'playing_b', 'done', 'expired', 'void')),
  winner INTEGER,                           -- done and NULL: a draw
  created REAL NOT NULL,
  expires REAL
);
CREATE INDEX matches_a ON matches(a);
CREATE INDEX matches_b ON matches(b);
ALTER TABLE runs ADD COLUMN match_id INTEGER REFERENCES matches ON DELETE CASCADE;  -- kind 'live': its race
CREATE INDEX runs_match ON runs(match_id);
