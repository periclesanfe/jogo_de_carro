# Jogo de Carro on the web: final architecture plan

**(A)** the final plan, **(B)** the changes made from the two critiques, **(C)** the decisions only you can make.

Verified while editing this plan (scripts in `scratchpad/design-final2/`; the repo was not modified):
- **Cached road surfaces** (`cached_world.py`):
  - Cost per `World` drops from 4.1 ms / 6.4 MB to 0.12 ms / about 20 KB, with 200 Worlds alive.
  - `Assets.preload()` and `World.update` run with the pygame display never initialised.
- **Difícil win tick** (`design-scope/worldcost.py` re-run): the run wins at tick 32401, but `round(win_s/FIXED_DT)` gives 32400.
- **Collision masks** come only from the unrotated frame 0 (`player.py:103`, `obstacles.py:45-55`), plus the pothole ellipse. That is a finite set, so all of them can be hashed.
- **Click-to-start gate:** pygbag 0.9.3's `pythons.js` unlocks it in Chrome on its own by playing `empty.ogg`. So `--autoplay-policy=no-user-gesture-required` is enough for headless CI, and the mirror must include `empty.ogg`.
- **Release dates (PyPI and GitHub, today 2026-10-20):**
  - fastapi 0.148–0.151 were all released on 10-19 or 10-20.
  - With uv's `exclude-newer = "2026-10-06"`, the pinned dependency set resolves to: starlette 1.7.0, uvicorn 0.54.0, pydantic 2.13.5, authlib 1.8.0, httpx 0.28.1, jinja2 3.1.6, python-multipart 0.0.32, argon2-cffi 25.1.0, itsdangerous 2.2.0.
  - Tool versions: Caddy 2.11.7 (released 10-03), uv 0.12.23 (10-03), pygame-ce 2.5.7 (03-02), pygbag 0.9.3 (02-12).

---

# (A) FINAL PLAN

## 1. Summary
1. The existing game runs in the browser through pygbag 0.9.3 (CPython 3.12.12 + pygame-ce 2.5.7). It is self-hosted, with a mirrored runtime locked by sha256 hashes. The game page stays open for the whole visit.
2. One Starlette process on the VPS handles:
   - accounts (email link + password, or Google);
   - friends, presence and invites;
   - the public leaderboard;
   - all match traffic, over one same-origin WebSocket authenticated by an HttpOnly cookie.

   Storage is SQLite. Caddy serves TLS and the static files.
3. **No number from the client is trusted:**
   - The server sends the seed only in `go`.
   - The client sends its inputs 10 times a second.
   - The server re-simulates every run live with the same code, on a runtime that is proven bit-identical to the browser's at every startup.
   - The server enforces real-time pacing.
   - Every run that would enter a top 10 waits for a human to review it.
4. **Versus** puts two Worlds side by side on one road that does not depend on the player (rows spaced ×1.15). The rival is driven by inputs relayed by the server (a live friend, or a friend's stored run in a challenge), or by the offline Bot.
5. **Why this shape:** the simulation is deterministic and cheap (about 38 µs per tick and about 20 KB per World). So one Python codebase serves as the client, the rival renderer and the verifier. One process keeps rooms, presence and rate limits in memory. The price is about 250 lines of auth code that we own.

## 2. Components and where each runs

| Piece | Where | Tech + pin |
|---|---|---|
| Reverse proxy, TLS, static files | VPS, systemd, Caddy apt repo + `apt-mark hold` | **Caddy 2.11.7**, Let's Encrypt, `admin off`. Serves `/jogo/<build>/` and `/cdn/0.9.3/` as immutable files (`precompressed gzip`). Everything else goes to `127.0.0.1:8000` |
| `jogo` app: pages, auth, `/ws`, hub, live verifier | VPS, systemd, user `jogo`, **1 uvicorn worker** (state lives in memory) | **CPython 3.12.12**: `uv python install cpython-3.12.12-linux-x86_64-gnu` (baseline build, not the `_v2/_v3/_v4` variants) into `/opt/uv-python`. **pygame-ce==2.5.7.** Libraries: starlette 1.7.0, uvicorn 0.54.0 + websockets, jinja2 3.1.6, python-multipart 0.0.32, argon2-cffi 25.1.0, authlib 1.8.0, httpx 0.28.1, itsdangerous 2.2.0. `server/pyproject.toml` sets `[tool.uv] exclude-newer = "2026-10-06"`; `server/uv.lock` has hashes. `jogo_de_carro` is a path dependency from the same commit. No `pygame.init()` and no display |
| Database | `/var/lib/jogo/jogo.db` | SQLite (stdlib), WAL, `foreign_keys=ON`, `busy_timeout=5000` |
| Game client | browser | **pygbag 0.9.3** build. Runtime cp312 = CPython 3.12.12 + pygame-ce 2.5.7 (SDL 2.28.4). Mirrored to `/cdn/0.9.3/` and checked against `web/cdn.lock` |
| Site pages | browser | Jinja2 templates (`*.html`, so they are autoescaped) + `site.css`. **No JavaScript** |
| Email | external SMTP relay on port 587 | stdlib `smtplib` (decision C2) |
| CI/CD | GitHub Actions on ubuntu-24.04 | uv 0.12.23, pygbag 0.9.3, ffmpeg, headless Chrome |
| Monitoring | free external services | UptimeRobot on `/saude`; healthchecks.io ping from the backup job |

**Version rule:** the server must match the browser on Python version, pygame-ce version, game tree hash **and golden digest**.
- `random.choices/shuffle/expovariate` are only stable within one Python version, and the masks come from `transform.scale`.
- At startup the server asserts `python_version()=="3.12.12"` and `pygame.version.ver=="2.5.7"`. It also computes `golden.digest()` and requires it to equal `/srv/jogo/jogo/<BUILD>/golden.txt` (the digest Chrome produced in CI). If any check fails, it refuses to start.
- `pyproject.toml` relaxes `pygame-ce>=2.5.8` to `>=2.5.7`. CI tests on 3.14 + 2.5.8 (desktop) and on 3.12.12 + 2.5.7.
- Moving to the cp314 web runtime is a later, separate step, gated by the same golden check.

## 3. Game client changes (`src/jogo_de_carro`)

| File | Change |
|---|---|
| `tween.py` | `out_cubic` and `in_out_cubic` use `u*u*u` instead of `**3` (3 lines). This removes libm `pow` from every gameplay ease, including the trunk and traffic eases whose inputs are arbitrary. At most a 1-ULP change; the game feels the same |
| `world/road.py` | `@functools.cache` on `build_vignette()`, and a cached `ground(assets)` that returns `build_ground(assets, Random(2022))`. Both surfaces are deterministic and only ever blitted. Measured: World cost goes from 4.1 ms / 6.4 MB to 0.12 ms / about 20 KB |
| `world/world.py` | Integer sub-seeds `Random(rng.getrandbits(64))` (`:75-77`). A `shared_road=False` argument: when set, the spawner gets `lane=None` (`:105`) and `mode=replace(mode,row_time=tuple(t*VERSUS_ROWS …))`. `draw(..., vignette=True)` |
| `settings.py` | `VERSUS_ROWS=1.15`, `VERSUS_CAP_S=600`, `RANKED_CAP_S=1800` |
| `assets.py` | `_bounds` cache (`:113-116`). In `mask()`, any `car_*` name uses `car_yellow`, so every colour has the same hitbox. `EXT="ogg" if sys.platform=="emscripten" else "wav"` (`:136,:149`) |
| `world/autopilot.py` | `Bot(react, rng)` from `bot.diff`, without the lead or the ghost. `BOT_LEVELS={"facil":0.20,"medio":0.13,"dificil":0.07}` |
| **new** `run.py` (~150) | `Run(assets, mode_key, skin, seed, shared, driver=None)` owns a `World` and a `Score`, plus the one standing countdown tick. Members: <br>• `step(controls, boost) -> [(WorldEvent, points)]`: the **only** scoring code; RaceScene calls it too. <br>• Outcome: a CRASH event means `crash`; `world.elapsed >= win_s` means `win`. Never a tick formula. <br>• `feed(k, ev)`: the trust boundary (§5); any exception becomes `BadInput`. <br>• `advance(to)`; `.tick .known .outcome .score .end`; `log()`. <br>• `verdict(a, b) -> 1/0/-1/None`; `simulate(assets, log, driver=None)` |
| `scenes/race.py` | `RaceScene(ctx, seed=None, shared_road=False, match=None)` with `self.run`. <br>• **Racing:** while RACING, `update` calls `run.step`. `_react` keeps only the effects (popups, audio, shake). After a crash, the slow-motion is a purely cosmetic `run.world.update`. <br>• **Input log** inside `_controls` (`:165-171`). `_boosting` becomes `held == 1`: UP alone. Holding W+S no longer boosts. <br>• **Debug hooks:** class attribute `DX`. `JOGO_RECORD=<dir>` makes `finish()` write the log as JSON. <br>• **Online** (`match` set): <br>&nbsp;&nbsp;– the scene is created at `go`, so the existing 2.25 s countdown is the start sync; <br>&nbsp;&nbsp;– `realtime=True`; <br>&nbsp;&nbsp;– Esc, P and focus loss only show the toast "Sem pausa no online · R desiste"; <br>&nbsp;&nbsp;– `in` is sent every 12 ticks; <br>&nbsp;&nbsp;– a `result` that arrives while racing ends the run (the race was decided); <br>&nbsp;&nbsp;– a dropped socket shows "Conexão perdida" and ends the run |
| **new** `scenes/versus.py` (~200) | `VersusScene(RaceScene)`, see below |
| **new** `scenes/online.py` (~170) | • `WaitScene`: "Conectando…", "Preparando…", "Aguardando ana_42…", "Servidor cheio", "Servidor atualizando, tente em 1 min"; Esc cancels. <br>• `AmigosScene`: online friends with CORRER AGORA / DESAFIAR; received challenges with JOGAR; "2 pedidos de amizade — veja no site". <br>• `ConviteScene`: overlay with ACEITAR / RECUSAR and a 30 s bar. <br>• `BotScene`: FÁCIL / MÉDIO / DIFÍCIL |
| `scenes/results.py` | `RaceStats.rival / .verdict / .official`. `on_net("result")` turns "verificando…" into one of: <br>• "✓ #37 no ranking Normal" <br>• "Em análise — entra no ranking após revisão" <br>• "Corrida invalidada: ritmo irregular" <br>Buttons: JOGAR DE NOVO / REVANCHE (an ordinary `invite`: same friend, same mode) / MENU / SITE. SAIR becomes SITE on web (`:46,:80`) |
| `scenes/title.py` | Menu: JOGAR (ranked when `ctx.net`, otherwise offline), CONTRA O BOT, AMIGOS (web only), SKIN, DIFICULDADE, SAIR→SITE. No F11 hint on web |
| `scenes/base.py` | `Context.net: Net \| None = None`; `Scene.on_net(msg)` does nothing by default |
| `app.py` | `Game(net=None)`. Each frame, `net.poll()` routes messages: <br>• `match` → WaitScene("Preparando…"), then send `ready`; <br>• `go` → `RaceScene`/`VersusScene(seed=…)`; <br>• `invited` → push ConviteScene unless racing; <br>• `error version` → toast, then `/jogar` (once per build; (H)); <br>• anything else → `scenes.top.on_net`. <br>Frame cap `min(frame_dt, 1.0 if top.realtime else MAX_FRAME)` (`:98`) |
| **new** `net.py` (~40) | • One **constant** JS string passed to `window.eval` defines `window.jws = new WebSocket(wss://location.host/ws)` and the `window.jq` queue, and reopens the socket after 2 s while in menus. <br>• `send(d)` calls `window.jws.send(json.dumps(d))` when `readyState==1`, otherwise buffers. Data is never formatted into `eval`. <br>• `poll()` drains `jq` into dicts |
| `save.py` | localStorage on emscripten (`save_web.diff`) |
| **new** `golden.py` (~70) | `digest()`, and `python -m jogo_de_carro.golden` prints `GOLDEN <sha256>`. It hashes: <br>• `t**0.8` over the accumulated `elapsed` and `elapsed+3` sequences up to 216k ticks; <br>• `exp(-r*FIXED_DT)` for r ∈ {9, 18, 1.8, 2.2, 4}; <br>• the lane-tween sequence; <br>• the bytes of **every collision mask**: `Assets.mask` for each sprite and shrink the sim uses, `bounds`, and the pothole ellipse mask; <br>• the `float.hex` results of `simulate()` on `tests/replays/*.json` (including a Difícil win and a trunk-heavy Infinito run) |
| `__main__.py` | `--replay run.json` drives RaceScene from a log, for admin review (about 12 lines). Run it with `uv run --python 3.12.12 --with pygame-ce==2.5.7` |
| `_build.py` (generated, gitignored) | `BUILD="<git rev-parse HEAD:src/jogo_de_carro>"`, or `"dev"`. Written by `tools/web_build.py` in CI and by `jogo-deploy` on the server |
| **new** `web/main.py` | `import pygame`. `?golden=1` prints GOLDEN. `?selftest=1` sends `hello` and prints `NET OK` on any parsed reply. Otherwise `Game(net=Net())` |
| **new** `tools/web_build.py` (~90) | • Copy the package; convert WAV→OGG with ffmpeg (q3); write `_build.py`. <br>• `pygbag --build --cdn /cdn/0.9.3/`; if the flag is refused, sed `index.html` as the probe did. <br>• Fetch the runtime files including `empty.ogg`, check them against `web/cdn.lock`, and write `.gz` copies next to `.data`/`.wasm` |
| tests | `test_run.py`, `test_versus.py`, the `tests/replays/*.json` corpus, and a `shared_road=True` case in `test_spawner` |

**`VersusScene` on 1280×720:**
- **Layout:**
  - Left half `surface.subsurface((0,0,640,720))`, right half `subsurface((640,0,640,720))`.
  - Each World draws unchanged with `offset=(-320+shake, shake)` and `vignette=False`. `LANE_CENTERS` stay absolute, so road x 400..880 lands at 80..560 and at 720..1200 on screen.
  - One `surface.blit(vignette,(0,0))` at the end.
  - Native cost: about 1.3× a solo frame; both sims together about 40 µs per tick.
- **HUD** (column x=566..714, over the inner verges, never over a lane):
  - TEMPO `01:23 / 03:00` with a progress bar in the mode colour.
  - VOCÊ card: points, coins, combo xN, shield strip.
  - "VS".
  - Rival card: nick, plus "AO VIVO", "gravação" or "BOT MÉDIO"; points; a pill reading BATEU 1:02, SAIU or "conexão instável".
  - km/h at the bottom.
  - My popups draw at `x-320`. 3-2-1 / JÁ! / VITÓRIA! are centred on the full screen.
- **Where the rival World comes from:** always `Run(assets, mode, rival_skin, seed, shared=True, driver)`.

  | Source | Feed | Stepping |
  |---|---|---|
  | Live friend **or** challenge recording (both arrive as `op`) | `on_net("op")` → `rival.feed(k, ev)`; `op_end` marks the end | Each frame `rival.advance(min(rival.known, my_ticks - 24))`, with at most 6 catch-up ticks per frame. "conexão instável" when more than 60 ticks behind |
  | Bot (offline) | `driver=Bot(BOT_LEVELS[lvl], Random(seed ^ 0xB07))` | Lockstep |

  The server releases `op` ticks only below my last reported `k + 24`, which is the same 24-tick delay the client already uses for drawing. A lagging client therefore never sees the rival ahead of its own position. A crashed rival freezes at its crash tick, dimmed, with "BATEU! 1:02".
- **Verdict:** `run.verdict(a, b)`:
  - A run that ended (crash, give-up or `conexao`) at tick T loses to a run alive past T.
  - If both reach the win (or the 10-minute Infinito cap), the higher score wins; an equal score is a draw (C4).
  - Before a crash, distance depends only on the tick, so "goes farthest" is the same as "survives longest".
  - Online, the server's `result` decides and **ends both runs at once**; the survivor sees VITÓRIA! without driving to the end.
  - Against the bot, the verdict is local and pause is allowed.

**Versus road tuning.** The shared road drops the spawner's pull toward the player's lane (`spawner.py:187-192`), which roughly halves survival for an imperfect driver. Spacing rows ×1.15 restores it using one existing field. Judge measurement: 20 seeds, a greedy screen-reading driver, canonical masks. Cells are median / mean survival in seconds, win %, and corridor moves per row:

| Mode | Solo today | Shared, untuned | **Shared ×1.15** | ×1.25 | Sticky, bias 30 |
|---|---|---|---|---|---|
| Fácil | 79.5 / 64.3, 40%, 0.70 | 35.1 / 43.5, 10% | **69.8 / 60.8, 40%, 0.72** | 90.0 / 77.3, 70% | 49.3 / 57.6, 0.31 |
| Normal | 48.7 / 57.0, 0.53 | 29.2 / 29.6 | **49.5 / 54.3, 0.67** | 48.2 / 48.7 | 55.1 / 71.5, 0.27 |
| Difícil | 53.8 / 59.5, 0.51 | 30.6 / 35.0 | **45.3 / 47.5, 0.56** | 58.3 / 54.8 | 70.6 / 83.6, 0.28 |

- Ranked solo keeps today's road, so the board keeps its current balance.
- `VERSUS_ROWS` is the only knob; refit it from stored versus logs after the beta. Difícil is about 15% short.

**Bot ladder on the ×1.15 road** (win %, median seconds; 20 seeds):

| React | Fácil | Normal | Difícil |
|---|---|---|---|
| **0.20 fácil** | 30% / 64.8 | 0% / 35.3 | 0% / 45.3 |
| **0.13 médio** | 75% / 90 | 25% / 113.5 | 0% / 63.6 |
| **0.07 difícil** | 100% | 85% / 180 | 75% / 270 |

## 4. Site and front-end
- **HTML pages** (Jinja, server-rendered, no JavaScript; forms POST, then 303): every page where something is typed or a list is managed. Password managers, autofill and accessibility come for free.
  - `/`: landing page; ENTRAR or JOGAR; top 10 per mode.
  - `/entrar`: email + password, and an "Entrar com Google" link to `/auth/google`.
  - `/cadastro` and `/esqueci`: **the same form and handler**. You enter your email, and the page always answers "Se o e-mail puder ser usado, enviamos um link".
  - `/senha?t=`: GET shows the form ("Defina sua senha") and does **not** use up the token, so mail scanners are harmless. POST sets the password and logs you in.
  - `/apelido`: choose a nickname.
  - `/conta`:
    - "Trocar senha" emails a link (no current-password form; this also works for Google-only accounts).
    - "Sair" and "Sair de todos os aparelhos".
    - "Excluir conta" requires typing your nickname.
  - `/amigos`: add by nickname; accept, decline or remove; online dots come from the hub's memory.
  - `/ranking?modo=`: public; top 100 plus "você: #N"; cached for 10 s.
  - `/partidas`: your matches and challenges, and "em análise" runs.
  - `/privacidade`.
- **In-game (pygame):** everything about playing. That covers the menus, AMIGOS with presence, invites, waiting, bot level, races, versus, results and REVANCHE. It reuses `Menu`/`MenuScene`, so keyboard and gamepad work and no HTML ever sits over the canvas.
- **Game page:** `/jogar` requires a session and a nickname, then answers 302 to `/jogo/<BUILD>/index.html` (immutable, served by Caddy).
  - Auth: the same-origin WS carries `__Host-sid` automatically, so Python never handles a token.
  - Match parameters arrive only as WS messages. The URL carries only `?golden=1` and `?selftest=1`, both used by CI.
- **The wasm loads once per visit** (2.4 s warm, 4–5 s cold). Ranked runs, rematches, bot races, live races and challenges all start inside it. It reloads only when the player navigates to an HTML page or the server refuses its version (`error version`).
- **Mobile:** not supported. The site says "Jogue no computador (teclado ou controle)".

## 5. Backend (`server/`: `app.py` routes, `auth.py`, `hub.py`, `flags.py`, `db.py`, `mail.py`, `admin.py`, `load.py`, `templates/`)

**Auth**
- **Accounts exist only after the email or the Google account is proven.** There is no "unverified" state.
  - **Request a link:** POST `/cadastro` (or `/esqueci`, or "Trocar senha") checks the email (at most 254 characters, basic shape) and the rate limits. It stores `sha256(token_urlsafe(32))` in `tokens` together with the email (1 hour, single use) and sends `https://DOMAIN/senha?t=…`. The reply is always the same.
  - **Set the password:** POST `/senha` (`t`, `senha`, `senha2`; 8–128 characters):
    1. Use up the token.
    2. Create or update the user by email and set `pw_hash`.
    3. Call `end_sessions(uid)`.
    4. Create a new session and redirect to `/apelido` or `/`.
- **Hashing:**
  - `PasswordHasher(parallelism=1)` (Argon2id, t=3, 64 MiB), run on **one** worker thread.
  - More than 8 hashes queued gives 429 "Muitas tentativas, tente em instantes". This is the global budget.
  - Only login and POST `/senha` hash anything.
  - Login runs a dummy verify for unknown emails and for Google-only accounts, and always answers "E-mail ou senha incorretos". `check_needs_rehash` runs on login.
- **Sessions:**
  - Cookie `__Host-sid` (plain `sid` on localhost in dev): 32 random bytes; the DB stores only the sha256. HttpOnly, Secure, SameSite=Lax, Path=/.
  - 30 days, renewed when fewer than 15 remain. Rotated on login.
  - `end_sessions(uid)` deletes the user's sessions and tokens and calls `hub.kick(uid)`. It is used for: new password, "sair de todos", ban and account deletion.
- **CSRF/CSWSH:** SameSite=Lax, plus `Origin == https://DOMAIN` checked:
  - on every POST, in middleware;
  - **inside the `/ws` handler before `accept()`**, because HTTP middleware never sees WebSocket traffic.
- **Google:**
  - Authlib Starlette client with Google's discovery URL, `openid email profile`, PKCE S256.
  - `SessionMiddleware(secret=SESSION_SECRET, https_only=True, max_age=600)` holds only the OAuth state and nonce.
  - `redirect_uri` and every emailed link are built from `DOMAIN`, never from the request.
  - `info = token.get("userinfo")`; if it is missing, refuse. `ok = info["email_verified"] and (email.endswith("@gmail.com") or info.get("hd"))`.
  - **Rules, in order:**
    - `google_sub` known → log in.
    - Not `ok` → "Para este e-mail, entre com e-mail e senha" (no link, no new account).
    - Email matches an existing account → link `google_sub` and log in.
    - Otherwise → create the user, then `/apelido`.
  - **Console:**
    - Web client with redirect URI `https://DOMAIN/auth/google/callback`.
    - A separate dev client with `http://localhost:8000/auth/google/callback`.
    - Consent screen External and **Published**, basic scopes, no logo (so no brand verification), home and privacy URLs on DOMAIN.
- **Nickname:** must match `^[A-Za-z0-9_]{3,16}$`, be unique ignoring case, and not be reserved (admin, bot, sistema, moderador, suporte).
- **Rate limits** (in-process sliding windows, about 25 LOC). The client IP comes from Caddy (`--proxy-headers --forwarded-allow-ips 127.0.0.1`); **IPv6 addresses are counted per /64**.

  | Action | Limit |
  |---|---|
  | Login | 10 / 15 min per IP+email; 50 / h per IP |
  | Link emails | 3 / h per email; 10 / h per IP; **50 / h globally** (stays inside the relay's free quota) |
  | Friend requests | 30 / day |
  | Invites | 10 / 10 min |
  | Ranked starts | 60 / h |
  | Open challenges | at most 10 |
  | WebSocket | 30 messages/s; 16 KB frames; one socket per user (a new tab closes the old one: "Aberto em outra aba") |
  | Admission | at most `MAX_ATIVAS` active runs (start at 100, set from `load.py`), otherwise "Servidor cheio" |

- **LGPD:** a `/privacidade` page, and account deletion removes everything by cascade.

**Data model** (`server/schema.sql`; migrations by `PRAGMA user_version`):
```sql
CREATE TABLE users(id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE COLLATE NOCASE, pw_hash TEXT,
  google_sub TEXT UNIQUE, nick TEXT UNIQUE COLLATE NOCASE,
  role TEXT NOT NULL DEFAULT 'player' CHECK (role IN ('player','admin','banned')), created REAL NOT NULL);
CREATE TABLE sessions(id BLOB PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE, expires REAL NOT NULL);
CREATE TABLE tokens(id BLOB PRIMARY KEY, email TEXT NOT NULL COLLATE NOCASE, expires REAL NOT NULL);  -- sha256 of the link token
CREATE TABLE friends(a INTEGER NOT NULL REFERENCES users ON DELETE CASCADE, b INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  asked_by INTEGER NOT NULL, accepted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (a, b), CHECK (a < b));
CREATE TABLE matches(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('live','challenge')), mode TEXT NOT NULL,
  seed INTEGER NOT NULL, a INTEGER NOT NULL REFERENCES users ON DELETE CASCADE, b INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  state TEXT NOT NULL CHECK (state IN ('racing','open','playing_b','done','expired','void')),
  winner INTEGER, created REAL NOT NULL, expires REAL);                 -- done + winner NULL = draw
CREATE TABLE runs(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('solo','live','challenge')), match_id INTEGER REFERENCES matches ON DELETE CASCADE,
  mode TEXT NOT NULL, skin TEXT NOT NULL, seed INTEGER NOT NULL, shared INTEGER NOT NULL, build TEXT NOT NULL,
  started REAL NOT NULL, ended REAL, ticks INTEGER, outcome TEXT, score INTEGER, seconds REAL, client_score INTEGER,
  max_lag REAL, features TEXT,                                           -- json, server-only
  state TEXT NOT NULL CHECK (state IN ('live','ok','review','rejected')), why TEXT,
  log BLOB);                                                             -- zlib(json {v,ev,arr}); arr = arrival ms per message
CREATE INDEX runs_board ON runs(mode, score DESC) WHERE kind = 'solo' AND state = 'ok';
```
- **Kept in memory only:** sockets, presence, invites (30 s TTL), live `Run` objects, relay buffers.
- **On startup,** any `live` run becomes `rejected` with `why='reinicio'`.
- **Leaderboard:** `ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY score DESC, id)` over `kind='solo' AND state='ok'`, excluding banned users; best run per user; top 100; cached 10 s.

**HTTP routes**
- The pages in §4.
- `POST /amigos`, `POST /amigos/{id}/aceitar|recusar|remover`.
- `GET /jogar`.
- `GET /saude` → `{build, golden:true, ativas, loop_lag_ms, review, desync_24h}`.
- `WS /ws`.

**WebSocket `/ws`** (JSON text frames). Envelopes are checked by `hub.fits` against `hub.SHAPES` (no pydantic): every field present and no other, exact JSON types (`true` is no int), `mode`/`skin` one of the known values. Every `m` must equal `sock.match` and every `id` must belong to the sender, otherwise the server closes with 1008.
```
C→S {"t":"hello","build":"<tree>","py":"3.12.12","pg":"2.5.7","skin":"yellow"}
S→C {"t":"welcome","me":{"id":7,"nick":"pericles"},"friends":[{"id":42,"nick":"ana_42","s":"menu|racing|off"}],
     "challenges":[{"id":77,"from":"ana_42","mode":"normal","secs":83.2,"score":5321}],"requests":2}
  | {"t":"error","code":"login|version|busy|rate|bad|full|drain","msg":"<pt-BR>"} + close   (version → "Nova versão — recarregue")
S→C {"t":"presence","id":42,"s":"off|menu|racing"}

C→S {"t":"solo","mode":"normal"}
C→S {"t":"invite","to":42,"mode":"normal"}                    S→C {"t":"waiting","id":"i_9f2c"}
S→C {"t":"invited","id":"i_9f2c","from":{"id":7,"nick":"pericles"},"mode":"normal","ttl":30}
C→S {"t":"invite_reply","id":"i_9f2c","ok":true}   (invitee only)    C→S {"t":"invite_cancel","id":"i_9f2c"}   (inviter only)
S→C {"t":"invite_gone","id":"i_9f2c","why":"declined|expired|cancelled|offline|busy"}
C→S {"t":"challenge","to":42,"mode":"normal"}                  C→S {"t":"challenge_play","id":77}   (B only)
S→C {"t":"match","m":901,"kind":"solo|live|challenge","mode":"normal","op":null|{"nick":"ana_42","skin":"red","rec":false}}
C→S {"t":"ready","m":901}                       10 s deadline for every kind; missing it uses up the attempt
S→C {"t":"go","m":901,"seed":6004799503160661}  seed revealed here (53-bit); countdown 2.25 s; t0 = loop.time()+2.25
C→S {"t":"in","m":901,"k":1452,"ev":[[1440,"R"],[1446,1]]}                    every 12 ticks; prev_k ≤ tick < k
C→S {"t":"in","m":901,"k":7321,"ev":[...],"fin":{"outcome":"crash|win|giveup","score":2210}}
S→C {"t":"op","m":901,"k":1452,"ev":[...]}       only ticks < the receiver's last k + 24
S→C {"t":"op_end","m":901,"k":7321,"why":"crash|win|giveup|left"}
S→C {"t":"result","m":901,"run":5531,"state":"ok|review|rejected",
     "why":null|"top10|bot|ritmo|adiantado|invalido|conexao|prazo|desync","outcome":"crash","score":2210,"secs":12.1,
     "rank":37|null,"verdict":"win|loss|draw"|null,"op":{"nick":"ana_42","score":5321,"secs":83.2}|null}
C→S {"t":"leave","m":901}
S→C {"t":"challenge_new","id":77,...}   {"t":"challenge_done","id":77,"verdict":"loss"}   {"t":"update"}
```
**`Run.feed` validation:**
- `k` is a strict int with `prev_k < k ≤ prev_k+240` and `k ≤ cap` (ranked 30 min, versus 10 min).
- At most 64 events per message and 54k per run (30/s over the ranked cap; `Run.play` ignores input past it).
- Each event is `[tick, v]`: `tick` is a strict int, `prev_k ≤ tick < k`, never decreasing.
- `v` is `"L"`/`"R"` (at most one per tick), or `type(v) is int` in 0..3 and different from the previous held value (at most one per tick). `type(v) is int` rejects JSON `true`.

**Hub mechanics** (`hub.py`):
- **Clock:** `loop.time()`. A 100 ms ticker adds any oversleep beyond 50 ms to a global `stall`.
- **Pacing:** each run stores `stall0` at `go`, and `lag = (now - t0) - credit - k/120`, where `credit` is the server's stall of the last 3 s (after `stall0`): the backlog a hiccup piles up is never blamed on the player, and the credit then lapses ((H)). The 0.5 s sweeper skips its checks while the loop lags more than 0.5 s.
- **Sending:** `send()` is `wait_for(ws.send_text, 1)`; on timeout the socket is closed, so a client that never reads cannot stall broadcasts.
- **Drain:** when `/srv/jogo/drain` exists, `solo`, `invite`, `challenge` and `challenge_play` get `drain`.
- **Admission:** see the `MAX_ATIVAS` row above.

**Flows**
- **Ranked solo:**
  1. `solo`: one active run per user and admission checks; insert a `runs` row (`live`, seed `secrets.randbits(53)`, not shared); send `match`.
  2. The client sends `ready`; the server sends `go` with the seed.
  3. For each `in`: pacing check, then `feed`, then `advance(k)`. When the server's sim reaches an outcome, the run is over.
  4. Store `zlib(log + arrivals)`, `features` and `max_lag`. Set the state: `review` if the run would enter its mode's top 10 or the flag rule trips; otherwise `ok`. Send `result`.
- **Jogar com amigos (live):**
  1. `invite`: checks friendship, that the friend's status is `menu`, and the limits. The friend gets `invited`; it expires in 30 s.
  2. Accepting creates `matches(racing)` and two `runs` (same seed, versus road) and sends `match` to both.
  3. Both send `ready` within 10 s, otherwise the match is void. `go` goes to both in one loop iteration.
  4. Each `in` feeds that player's server `Run`. The other player's buffered events are released to them up to their `k + 24`.
  5. `verdict()` runs after every advance. When it settles, both get `result` (which ends both runs) and the rows are written.
  6. **Disconnects:** after 5 s with no `in`, that run ends as `conexao` at its last confirmed tick, and the other side gets `op_end`.
  7. **REVANCHE** is simply a new `invite`.
- **Desafiar amigo (async):**
  1. `challenge` creates `matches(challenge, racing)`. A plays an online single-column `RaceScene(shared_road=True)`.
  2. When A's run is `ok` (or `review`), the match becomes `open` for 7 days and B gets `challenge_new`.
  3. `challenge_play` checks that the sender is B and the match is `open`, then sets `playing_b` (one attempt). B gets `match` without a seed, and `go` carries the seed.
  4. The server streams A's **stored** events through the same gated `op` path as a live race, so B never holds the whole recording.
  5. The server decides against A's stored result. A gets `challenge_done`. If A's run ends up `rejected`, the match becomes `void`.
- **Desafiar um bot:** entirely in the client, with pause allowed. Nothing is sent or stored.
- **Leaderboard:** ranked solo only, per mode, all-time. Versus results appear only on `/partidas`.

## 6. Anti-cheat chain end to end
1. **Identity:**
   - Every account has a proven email (link) or a qualifying Google account.
   - One active run and one socket per user.
   - Rate limits, including IPv6 /64.
   - One board row per account. The top-10 hold (item 7) also catches a batch of alt accounts.
2. **Seed:** `secrets.randbits(53)`, bound to (user, run, mode, skin, shared, build).
   - It is revealed **only in `go`**, 2.25 s before tick 0, after `ready`.
   - Missing the 10 s `ready` deadline uses up the attempt: a solo run becomes `rejected/prazo`, and B loses the challenge.
   - The client never submits a seed. No public replay endpoint exists, so neither a seed nor a log can be fetched in any other way.
   - This removes any rehearsal of a known course or of a challenge. It does not stop seed shopping: `leave` right after `go` costs nothing, so a bot can score each road offline and keep only the good ones, up to the 60 starts an hour (§6.10).
3. **Stream:**
   - The client sends only inputs, every 100 ms.
   - The server assembles the log itself, plus the arrival time of each message.
   - There is no upload path for a log or a score; `fin.score` is only compared.
4. **Live re-simulation:**
   - Same tree hash, same runtime, and a golden digest equal to the browser's (checked at startup).
   - Only the server's outcome, ticks and score are stored.
   - When `fin` disagrees, the server's result stays official, with `why='desync'`; the log is kept and `/saude` counts it.
5. **Pacing**, on the monotonic, stall-compensated server clock:
   - `lag < -0.25 s` → rejected, `adiantado` (faster than real time).
   - `lag > 2.0 s` → `ritmo` (slow motion, frozen tab, pause), or a forfeit in versus.
   - More than 5 s with no message → `conexao`.
   - Every run stores `max_lag`. After the beta, tighten 2.0 s to the honest p99.
   - Honest clients keep pace because online scenes allow `max_frame=1.0`.
6. **Pause:** none in any online run; `R` gives up. A backgrounded tab falls behind and loses the run; the site warns "não troque de aba". Offline and bot play keep today's pause.
7. **Bot-likeness and human review:**
   - **Detector features** (`server/flags.py`, a pure function over the stored log):
     - corridor adherence;
     - reaction ticks from a corridor change to the matching steer (median, p10, n);
     - boost share;
     - `lag_up`: for each wall-clock second take the minimum lag, then sum the positive steps, per minute. This catches a sawtooth of slowing down and catching up that stays under the 2 s limit.

     Thresholds live in `/etc/jogo/env` and features never leave the server.
   - **Rule for ranks 11–100:** `(n≥30 and (p10<7 or median<12)) or adherence≥0.99` → `review/bot`. `lag_up` is only recorded until it is calibrated on beta data.
   - **Every run that would enter its mode's top 10** → `review/top10`. The player sees "Em análise".
   - **Review:** `admin revisar` lists the queue. The server emails `ADMIN_EMAIL` at most once an hour while the queue is not empty. The reviewer runs `admin export <run>` and replays it with `python -m jogo_de_carro --replay`. Then `admin aprovar | rejeitar | banir`.
   - **Check:** `tests/test_flags.py`. Logs from `autopilot` and `Bot(0.07)` are flagged. Greedy logs and human logs recorded with `JOGO_RECORD` are not. The screen-planner bot is a **documented miss**, caught only by the top-10 hold. So is a **corridor reader with a human-scale delay** (0.10 s + up to 0.15 s a move): the spawner keeps 0.12 s of slack per planned move, so it wins every Normal, Fácil and Difícil run measured and is never flagged. Not flagged does not mean human. **Open:** before trusting the 11–100 rule, calibrate on `JOGO_RECORD` human logs with another feature (the spread of reaction ticks, p90 − p10, or a cap on adherence for long Normal/Difícil wins).
8. **Versions:**
   - `hello.build/py/pg` must equal the server's values, otherwise `error version` (the game then goes to `/jogar` once per build; (H)).
   - The mirrored runtime is hash-locked.
   - The server asserts its versions and the golden digest on **its own CPU** at every start.
   - The web build and the server deploy from the same commit.
9. **Cross-platform floats:**
   - **Browser side:** `main312.wasm` has musl's pow, exp and log compiled in and imports no JS Math, so every browser computes identically. The server is the only variable.
   - **libm calls left in scoring** (the cubes are now plain multiplications): `t**0.8` in `speed_at` and the `exp(-r/120)` constants. Their inputs are fixed sequences, which `golden.py` hashes **exhaustively**.
   - **Masks** (`transform.scale`, `from_surface`, `draw.ellipse`) are hashed byte for byte. This catches a pygbag "2.5.7" that differs from the PyPI 2.5.7.
   - **Gates:**
     - CI requires native digest == Chrome digest before deploying.
     - The server requires its own digest == the Chrome digest before starting.
     - A glibc upgrade that changes libm makes the server refuse to start, on purpose.
   - **Plan B, applied only if a gate fails:**
     - pow/exp → the exp factors as `float.hex` literals, and `t**0.8` as a pure-float Newton fifth root (about 10 lines; pure IEEE operations are identical on every platform).
     - masks → ship the precomputed mask bits as package data, loaded on both sides.
10. **What can still be cheated, and why that's acceptable:**
    - **Real-time assisted play** (an in-page bot or a screen overlay). pygbag ships the source and the client must know the road to draw it. The measured screen-planner wins Normal 15 times out of 16 and is never flagged, so it can reach ranks 11–100. Top-10 human review, bans and the pacing checks limit the damage; it's a hobby game with no prizes.
    - **Corridor bots with a human-scale delay** (item 7) reach ranks 11–100 unflagged; only the top-10 hold and the reviewer's replay stop them.
    - **Seed shopping** (item 2): a bot gives up right after `go` on roads it scored badly. Accepted as within the top-10 hold's scope; a tighter budget for early give-ups is the cheap limit if it shows up.
    - **Up to about 2 s of pacing slack**, plus a server stall's length for the 3 s after it. It is bounded and leaves traces in `max_lag`, `arr` and `lag_up`.
    - **Multiple accounts:** each needs a proven email, and the top 10 is reviewed.
    - **Win-trading:** there is no public versus board.

## 7. Deployment on the VPS (Ubuntu 24.04)
- **Layout:**
  - `/srv/jogo/app`: checkout at the deployed sha, with `server/.venv`.
  - `/srv/jogo/jogo/<build>/`: web builds, each with `golden.txt`.
  - `/srv/jogo/cdn/0.9.3/`: the runtime mirror plus `.gz` copies.
  - `/srv/jogo/drain`.
  - `/opt/uv-python`.
  - `/var/lib/jogo/jogo.db`.
  - `/etc/jogo/env` (0640 root:jogo): `DOMAIN`, `GOOGLE_CLIENT_ID/SECRET`, `SESSION_SECRET`, `SMTP_*`, `ADMIN_EMAIL`, `MAX_ATIVAS`, `FLAG_*`.
- **One-time setup:** `ops/setup.sh`, re-run by hand when ops files change.
  - Installs Caddy and `uv python install` into `/opt/uv-python`.
  - Runs `caddy validate` and `systemd-analyze verify jogo.service` before installing either file.
  - Configures ufw (22/80/443 only), key-only SSH, unattended-upgrades.
  - `/etc/needrestart/conf.d/jogo.conf`: `$nrconf{override_rc}{qr(^jogo\.service$)} = 0;`, so security updates never restart a race. The next deploy restarts through the drain.
- **`jogo.service`:**
  - `User=jogo`, `EnvironmentFile=/etc/jogo/env`, `Environment=PYTHONDONTWRITEBYTECODE=1`.
  - `ExecStart=/srv/jogo/app/server/.venv/bin/uvicorn server.app:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --ws-max-size 16384 --no-access-log`
  - `Restart=always`, `MemoryMax=1G`, `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `ReadWritePaths=/var/lib/jogo`.
- **Caddyfile:**
  ```
  { admin off }
  {$DOMAIN} {
    encode zstd gzip
    header Strict-Transport-Security "max-age=63072000"
    header X-Content-Type-Options nosniff
    header Referrer-Policy same-origin
    @s path /jogo/* /cdn/*
    handle @s {
      root * /srv/jogo
      header Cache-Control "public, max-age=31536000, immutable"
      header Content-Security-Policy "frame-ancestors 'none'; connect-src 'self' wss://{$DOMAIN}"
      file_server { precompressed gzip }
    }
    handle { reverse_proxy 127.0.0.1:8000 }
  }
  ```
  - The app sets its own CSP on its HTML: `default-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'`.
  - No COOP or COEP headers.
  - DNS: A/AAAA records for DOMAIN, plus SPF, DKIM and DMARC for the relay.
  - With `admin off`, a Caddy config change needs a restart, which drops sockets. Do it while drained.
- **CI/CD:**
  - `ci.yml`: pytest on 3.14 + 2.5.8, and on 3.12.12 + 2.5.7 including `pytest server/`.
  - `web.yml` on main, in order:
    1. `tools/web_build.py`.
    2. Headless Chrome (`--headless=new --autoplay-policy=no-user-gesture-required --host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE localhost"`) on `?golden=1`. Its digest must equal the native digest; write it to `golden.txt`.
    3. Start a test uvicorn with `JOGO_DEV_STATIC=build/web`. `?selftest=1` must print `NET OK` (the `error/login` reply proves the round trip).
    4. `tar` the build, then `ssh deploy@VPS "$SHA" < web.tgz`.
  - **Deploy key line:** `restrict,command="/usr/local/bin/jogo-deploy" ssh-ed25519 …`. GitHub holds only that key and `known_hosts`.
- **`jogo-deploy`:**
  1. Validate `^[0-9a-f]{40}$`.
  2. `git fetch` and `checkout --detach`. `TREE=$(git rev-parse $SHA:src/jogo_de_carro)`; write `_build.py`.
  3. Extract stdin to `/srv/jogo/jogo/$TREE/`; it must contain `index.html` and `golden.txt`.
  4. `UV_PYTHON_INSTALL_DIR=/opt/uv-python UV_CACHE_DIR=/srv/jogo/.uv uv sync --frozen`.
  5. `touch /srv/jogo/drain`; wait until `/saude` shows `ativas==0` (at most 31 min, the ranked cap plus slack).
  6. `sudo systemctl restart jogo` (the only sudo rule).
  7. Smoke test: `/saude` must report `build==$TREE` and `golden:true`. On success, remove the drain file. On failure, check out the previous sha, restart, remove the drain file and exit 1.
- **Backups:** `jogo-backup.timer` daily at 04:00.
  1. `sqlite3 .backup`, then zstd; keep 14 local copies.
  2. `rclone copy` to a **crypt** remote (C8).
  3. Restore the newest copy to a temp file and run `PRAGMA integrity_check` plus row counts. This is the runnable check.
  4. Ping healthchecks.io.

  `/etc/jogo/env` and the rclone crypt password go in your password manager. VPS snapshots are a second layer.
- **Monitoring:**
  - UptimeRobot on `/saude`.
  - healthchecks.io for backups.
  - The review-queue email.
  - `journalctl -u jogo` with one line per finished run (state, why, max_lag, CPU ms).
  - `server/README.md` documents the `sqlite3` queries for runs per day, rejects by reason and desyncs.

## 8. Milestones (each shippable; LOC are rough)

| # | Ships | ≈ LOC | Runnable check it leaves |
|---|---|---|---|
| **S0** (days 0–1, throwaway) | **Spike 1, bit-exactness:** a digest over `simulate()` on 5 recorded logs (including a Difícil win and trunk-heavy Infinito), the pow and exp sequences, and every mask, computed in three places: pygbag in headless Chrome, `docker --platform linux/amd64 ubuntu:24.04` with uv 3.12.12-gnu + pygame-ce 2.5.7, and the VPS. **Spike 2, self-hosting:** `--cdn` mirror behind Caddy with the CSP above; a 30-line Starlette app with `__Host-sid` and an Origin-checked WS echo through `net.py`; Chrome with every external host blocked | ~150 | Pass: the three digests are equal; the title screen boots and `net.py` prints the echoed message; the mirror's sha256 values are unchanged a day later; `.wasm`/`.data` transfer sizes match GitHub Pages. Fail: apply Plan B (§6.9) and rerun |
| M0 | Determinism core: cubes, cached road surfaces, int seeds, `shared_road` + `VERSUS_ROWS`, bounds cache, canonical masks, input log, `run.py` (RaceScene steps through it), the W+S fix, `Bot`, `golden.py`, the log corpus, `JOGO_RECORD`, `--replay` | 350 | `pytest tests/test_run.py`: <br>• RaceScene with synthetic keys equals `Run` for all modes, solo and shared; <br>• 12-tick batches equal feeding the whole log; <br>• junk raises `BadInput`; <br>• the shared road gives the same placements for 3 drivers; <br>• bot levels are ordered; <br>• a Difícil win lands at the tick where `elapsed>=270`. <br>The 43 existing tests pass on both runtimes |
| M1 | Web build + offline **bot versus** at `https://DOMAIN/jogo/` (public): `web/main.py`, OGG, localStorage, SITE, `VersusScene`, `BotScene`, results with rival, CDN mirror and lock, Caddy | 550 | CI golden gate (native == wasm); boot with external hosts blocked; `tests/test_versus.py` (headless versus against the Bot reaches a verdict; the rival's result equals `simulate`). Recorded by hand: p95 frame time on a real mid-range laptop, at 1× and under a 4× CPU throttle (the ≤ 20 ms gate is open, see (E)) |
| M2 | Accounts: Starlette app, schema, email-link signup and reset, Google, sessions, `end_sessions`, Origin checks, rate limits, hashing budget, nickname, `/conta`, `/amigos`, `/privacidade`; systemd, setup.sh, backups, deploy with drain (drain moved to M3, see (F)) and the startup golden check | 1000 (450 py, 300 templates/css, 130 ops, 120 tests) | `server/tests/test_auth.py`, with a fake outbox and mocked Google: <br>• the link flow, and **GET `/senha` does not use up the token**; <br>• identical replies for known and unknown emails; <br>• the Google rules (a non-gmail address without `hd` is refused; missing userinfo fails closed); <br>• cookie flags; <br>• a new password kicks the open WS; <br>• 429s, including IPv6 /64 and the hash queue; <br>• cross-origin POST and WS are refused. <br>Also `test_friends.py` and the backup restore check |
| M3 | **Ranked solo + public leaderboard + review tooling:** hub (hello/solo/ready/go/in/result), live re-sim, stall-compensated pacing, admission and drain, runs with arrivals, `flags.py`, top-10 hold, `admin revisar/aprovar/rejeitar/banir/export`, admin email, `/ranking`, `net.py`, `WaitScene`, online RaceScene, official result line, `load.py` | 700 | `server/tests/test_ranked.py` (TestClient WS, injectable clock): <br>• an honest log gives `ok` with the same score; <br>• altered inputs are scored by the server; <br>• 10× speed gives `adiantado`; <br>• 0.5× speed gives `ritmo`; <br>• **an injected 3 s loop stall leaves the run `ok`**; <br>• `true` or garbage gives `invalido`; <br>• **no seed before `go`**; <br>• the ready timeout gives `prazo`; <br>• a version mismatch gives `error version`; <br>• a would-be top-10 run gets `review`; <br>• drain refuses `solo`; <br>• a foreign `m` gives 1008. <br>Also `test_flags.py` and the CI `NET OK` selftest. On the VPS, `python -m server.load --n 100` sets `MAX_ATIVAS`. 10 minutes over home Wi-Fi: `max_lag` < 1.0 s |
| M4 | **Jogar com amigos (live):** presence, `AmigosScene`, `ConviteScene`, invites, rooms, gated relay, live verdict ending both runs, forfeit, REVANCHE as an invite | 420 | `server/tests/test_live.py` (two WS clients streaming corpus logs): <br>• `op` order is correct; <br>• **A never receives an `op` tick ≥ A.k+24**; <br>• the decision comes at the crash tick + 1 and both receive `result`; <br>• 5 s of silence forfeits; <br>• decline and expiry work; <br>• only the invitee can reply; <br>• a third user gets 1008. <br>Plus a written two-browser playtest checklist |
| M5 | **Desafiar amigo** (async, A's run streamed back through the gate), `/partidas` | 200 | `server/tests/test_challenge.py`: <br>• B gets no seed before `go` and never the whole log; <br>• single attempt; <br>• ready timeout counts as a loss; <br>• expiry; <br>• early decision; <br>• A is notified; <br>• A's run `rejected` makes the match `void` |

The total is about 3.4k LOC, including templates, tests and spikes. Start the items with lead time **now**: the domain (C1), the SMTP relay and its DNS records (C2), and publishing the Google consent screen. S2 and M1 need the domain. Answer C6 before M4.

## 9. Top risks and open questions

| Risk | Mitigation |
|---|---|
| The VPS's libm or masks differ from wasm | Spike S1 on day 0; CI gate; startup gate on the production CPU; Plan B ready (literal constants plus Newton root; precomputed mask bits); `desync` counter |
| Versus frame time in wasm | Measured in M1 on a real laptop; fallback is redrawing the rival half at 30 Hz |
| Our own auth code | Email-first removes the unverified state; argon2-cffi and Authlib do the crypto and protocol; one test per flow; an OWASP ASVS L1 pass before launch |
| pygbag has one maintainer and `--cdn` is unverified | Pin 0.9.3, mirror with a hash lock, WebSocket only, Spike S2; the desktop build stays as a fallback |
| One process: overload, or a restart drops races | `MAX_ATIVAS` measured with `load.py`; stall compensation; one hashing thread with a queue limit; drain before restarts; needrestart excluded. `ponytail:` about 100 racers per core; move `Run.advance` to a ProcessPool when `/saude` loop lag grows |
| Screen-reading bots below the top 10 | Accepted (§6.10); top 10 reviewed by a human; thresholds calibrated on beta logs |
| Reviewer workload | Hourly email only while the queue is non-empty; new top-10 entries are rare once the board settles |
| Road and bot tuning comes from heuristic drivers | `VERSUS_ROWS` and `BOT_LEVELS` are data-only knobs; refit from stored versus logs |
| Background tabs void honest online runs | Warnings in the game and on the site; the 2 s budget is calibrated from `max_lag` |
| Email deliverability from a new domain | Relay plus SPF, DKIM and DMARC; Google login does not depend on email |

**Open facts only you can provide:**
- Which datacenter the VPS is in (São Paulo is preferred; distance affects only how smooth the rival looks, never fairness).
- Whether it is IPv6-enabled.
- The VPS CPU model (S1 runs there anyway).

---

# (B) Changes from critique

**Security red-team**
1. Bot detector misses the screen-planner, and the top of the board was public before review. **Accepted.** Every would-be top-10 run is held as `review/top10`. The feature rule covers ranks 11–100. The planner log is a documented miss in `test_flags`. Admin email added.
2. Seed sent before `ready`, no deadline, open `replay`. **Accepted.** The seed moved into `go`, which is also simpler: the scene is built at `go` and the stock countdown is the sync. A 10 s `ready` deadline for every kind uses up the attempt. The `replay` rule is moot because public replays are cut (scope C1).
3. Golden gate ran on CI hardware, not on the production CPU. **Accepted.** The server checks the Chrome digest at every startup, and all masks are hashed.
4. Server overload blamed on players. **Accepted in full:**
   - `MAX_ATIVAS` from `load.py`;
   - argon2 `parallelism=1` on one thread, with 429 beyond 8 queued;
   - stall-compensated lag, and the sweeper skips while the loop lags;
   - IPv6 /64;
   - `wait_for(send, 1)`;
   - `loop.time()`;
   - an injected-stall test.
5. Repeatable bullet time inside the slack. **Accepted, merged with scope B4:** arrival times are stored in the log, and one `lag_up` feature is computed from them. The 2 s budget is tightened from p99.
6. Google auto-link trusted `email_verified` alone. **Accepted, slightly stricter:** when `ok` is false, Google may neither link nor create an account. Also: userinfo is required (fail closed); `https_only=True, max_age=600`; URLs are built from `DOMAIN`.
7. Pre-hijack through the verify link. **Accepted:** email-first signup with one link handler and one token kind; GET shows the form and POST uses up the token. This drops `email_ok`, "reenviar", the takeover special case and any hashing on signup.
8. Revoking sessions did not reach the open socket. **Accepted:** `end_sessions()` calls `hub.kick`. "Trocar senha" became an emailed link, which is stronger than asking for the current password and also covers Google-only accounts. Deletion requires the typed nickname. Dummy verify for Google-only accounts.
9. Client ids not bound to the socket's user. **Accepted:** every `m` must equal `sock.match`; invite reply and cancel are owner-only; Origin is checked in `/ws` before `accept()`; third-user tests added.
10. Requests that cost us more than the sender. **Accepted:** `/ranking` cached 10 s; global mail cap of 50/h. The `replay` rate limit is moot (replays cut). The "já tem conta" mail no longer exists.
11. W+S free boost. **Accepted:** `held == 1`. Listed in C11 because it changes scoring.
12. One-liners:
    - 53-bit seeds: **accepted**.
    - desync → `flagged`: **rejected**, because the server's numbers are authoritative; the result stays official with a counter (scope A7).
    - `--no-access-log`: **accepted**.
    - CSP on `/jogo/*`: **accepted**.
    - Templates must end in `.html`: **accepted**.
    - `Literal` types for mode and skin: **accepted**.
    - No data formatted into `eval`: **accepted**.
    - `rclone crypt`: **accepted**.
    - `restrict,command=` and Caddy `admin off`: **accepted**.

**Scope critique**
- **A1**, 6.4 MB per Run: **accepted.** `functools.cache` on the ground and vignette surfaces. Measured: 0.12 ms and about 20 KB per World.
- **A2**, Difícil win tick off by one: **accepted.** The outcome comes only from `elapsed >= win_s`, and the verdict compares ended runs. Test added.
- **A3**, the golden digest left out the hitboxes: **accepted.** All masks are hashed; the mask-bits fallback is in Plan B.
- **A4**, cubes go through libm: **accepted.** `u*u*u` unconditionally in M0.
- **A5**, golden check against production: **accepted** (same as security 3).
- **A6**, `ProtectHome` breaks uv's Python: **accepted.** `/opt/uv-python` and `UV_CACHE_DIR`.
- **A7**, desync rejection punishes honest players: **accepted.**
- **A8**, monotonic clock: **accepted.**
- **B1**, mail-scanner verify: **accepted.** Subsumed by email-first; POST-only use of the token.
- **B2**, seeing ahead by lagging: **accepted.** Relay gate at `k+24`. Its security value is small (the seed already reveals the shared road), but it costs about 6 lines and also serves B3.
- **B3**, the challenge handed over the whole recording: **accepted.** It is streamed through the same gate, which removes the client's separate "stored log" feed mode.
- **B4**, sawtooth slow motion: **accepted**, as `lag_up`.
- **B5**, pins less than 14 days old: **accepted.** `exclude-newer = "2026-10-06"`, uv 0.12.23, Caddy 2.11.7. Also **dropped FastAPI**: it shipped four releases in two days and we use only Starlette features.
- **B6**, top-10 hold: **accepted** (same as security 1).
- **C1**, cut public replays and reports: **accepted.** Review happens on the desktop with `admin export` and `--replay`, on the 3.12.12 runtime.
- **C2**, rematch is just an invite: **accepted.**
- **C3**, one copy of the scoring rules: **accepted.** RaceScene steps through `Run.step`.
- **C4**:
  - Drop basic_auth: **accepted**.
  - Frame time printed, not gated: **accepted**.
  - `admin stats` replaced by `/saude` plus documented queries: **accepted**.
  - Drop `set_mode((1,1))` and the dummy driver: **accepted**. Verified that the World runs with the display uninitialised; the mask digest settles equality.
- **D1**, both runs end at the verdict: **accepted.**
- **D2**, drain file: **accepted.** Wait at most 31 min, the ranked cap.
- **D3**, where BUILD comes from: **accepted.** `_build.py` is written by CI and by `jogo-deploy`.
- **D4**, `JOGO_RECORD`: **accepted.**
- **D5**, headless Chrome past the click gate: **accepted.** `--autoplay-policy=no-user-gesture-required` (verified in `pythons.js`); mirror `empty.ogg`.
- **D6**, mid-race drop: **accepted.**
- **E1**, move the go/no-go check earlier: **accepted** as S0 (Spikes 1 and 2). Spike 3 is **folded into the M1 and M3 checks**: a separate prototype would duplicate most of M1's code.
- **E2**, lead-time items: **accepted.**
- **E3**, review tooling with the board: **accepted.** Moved to M3.
- **F1**: **accepted.**
- **F2**, needrestart override: **accepted.**
- **F3**, runtime compression: **accepted.** `precompressed gzip`, and sizes are checked in S2.
- **F4**, back up the env file: **accepted.**
- **F5**: `caddy validate` and `systemd-analyze verify` are **accepted**, placed in `setup.sh`, because deploys never touch those files. `PYTHONDONTWRITEBYTECODE` is **accepted**.
- **G1**, `net.py` check: **accepted, simplified.** It needs no seeded cookie: the `error/login` reply proves the round trip, and the cookie path is covered by S2 and the server tests.
- **G2**, relay-gate test: **accepted.**
- **G3**, other checks: **accepted** (mask digest, Difícil win, GET `/senha` does not use the token, drain test).

---

# (C) Decisions the user must make (recommended default in bold)

1. **Domain:** **register one now** (e.g. a `.com.br` at registro.br) and point A/AAAA at the VPS. TLS, Google OAuth, email and Spike S2 all need it.
2. **Email relay and sender:** **Brevo free tier (300 emails/day), sender `nao-responda@DOMAIN`**, with SPF, DKIM and DMARC. Alternatives: Resend (100/day) or your domain host's mailbox.
3. **Who reviews held runs:** **you, with `ADMIN_EMAIL` set to your address; every new top-10 run is held.**
4. **Tie when both survive the timer:** **the higher score wins; an equal score is a draw.**
5. **Leaderboard scope:** **per mode, all-time, best run per player.** Weekly or per-car boards can come later.
6. **What "Desafiar amigo" means** (answer before M4): **both modes.** "Jogar com amigos" is the live race (M4); "Desafiar amigo" is "beat my recorded run" (M5).
7. **Mobile:** **out of scope** (keyboard or gamepad only).
8. **Off-site backups:** **Backblaze B2 (or Google Drive) through `rclone crypt`.** Keep the crypt password and `/etc/jogo/env` in your password manager.
9. **LGPD and the Google consent screen:** the data controller's name, a contact email, and the support email Google shows. Recommended: **your name, plus a `contato@DOMAIN` alias**.
10. **One hitbox for every car colour, desktop included:** **yes.**
11. **W+S boost fix** (boost only while UP is held alone), desktop included: **yes, before launch.**
12. **Keep the desktop build and its GitHub Releases:** **yes.** It is offline play, a fallback, and the review tool.
13. **Nickname rules:** **`^[A-Za-z0-9_]{3,16}$`, unique ignoring case, a reserved list, permanent once chosen.** No profanity filter; bans handle abuse.
---

# (D) S0 results (2026-10-20)

**Spike 1, bit-exactness: go, with Plan B (now applied in M0).**
- libm `pow` (`t**0.8` and the `**3` cubes) gives three families of results: Apple libm, glibc's FMA path (x86_64 with FMA+AVX2, and every arm64), and glibc's SSE2 path, which matches the musl compiled into the browser wasm. A typical VPS has FMA, so the old code would not have matched the browser.
- With a pure + − × ÷ Newton fifth root and `u*u*u` cubes, every configuration agrees: macOS 3.14/2.5.8, macOS 3.12.12/2.5.7, Docker amd64 (FMA and SSE2 paths), Docker arm64, and pygbag wasm in Chrome.
- `exp` factors, all 18 collision masks and bounds already matched everywhere (pygame-ce 2.5.7 vs 2.5.8, SDL 2.28 vs 2.32, with and without a display). No precomputed mask bits are needed.
- Final results (score, meters, outcome) matched even with the old code; only a per-tick state hash caught the drift. **`golden.py` must hash per-tick state**, not only results.
- Not run: a real x86 VPS. The startup golden check on the VPS's own CPU (§2) stays.

**Spike 2, self-hosted runtime + cookie WebSocket: pass**, with every external host blocked: title screen, a race, and `NET OK` over the Origin- and cookie-checked WebSocket. Changes to the plan:
- `--cdn /cdn/0.9.3/` needs `--template <local default.tmpl>`; without it pygbag writes no `index.html` and does not fail. `tools/web_build.py` must assert `index.html` exists.
- `--cdn` does not move the wheel index off GitHub (`pep0723.py` hard-codes `PKG_BASE_DEFAULT`). Add this inline script before the `pythons.js` tag:
  `<script>history.replaceState(null,"",location.pathname+(location.search?location.search+"&":"?")+"PYGPI=/cdn/"+location.hash)</script>`
- The page query string becomes `os.environ` in the browser's Python, so `?PYGPI=https://evil/` could load foreign wheels. pythons.js reads what follows the last `?` before the last `#`, so the script must also drop the fragment (corrected in M1: keeping `location.hash` let `#?PYGPI=…` win; it also turns off pygbag's `#debug`). Our `PYGPI` then comes last and wins, and the `connect-src 'self'` CSP on `/jogo/*` blocks it too: that CSP stays load-bearing. Any future `script-src` needs a hash for the inline script.
- The mirror spans all of `/cdn/` (14 files, 23 MB raw, about 11.3 MB gzip), not just `/cdn/0.9.3/`: §7's layout is `/srv/jogo/cdn/`.
- `frame-ancestors 'none'` on `/cdn/*` blocks pygbag's hidden `empty.html` iframe (harmless console error); use `'self'` there.
- In the browser, `print()` only reaches pygbag's in-page terminal: `GOLDEN` and `NET OK` must go through `platform.window.console.log` for CI.
- CI's `--host-resolver-rules="MAP * ~NOTFOUND, EXCLUDE localhost"` also maps IP literals: use `localhost`, not `127.0.0.1`.
- ffmpeg without libvorbis: `-c:a vorbis -strict -2 -ac 2 -q:a 3` (stereo only).

---

# (E) M1 shipping notes (2026-10-20)

These replace the static-file parts of §7: the VPS already serves another site, and nginx took Caddy's place (`ops/nginx/jogo.conf`, commit dc71af7).

**Layout on the VPS:** `/srv/jogo/www` is the web root, written only by `ops/jogo-deploy` (user `jogo`); `/srv/jogo/www-tmp` (0700) is where it unpacks a build first, on the same filesystem so publishing is a rename.

| Path | What | Headers the proxy must send |
|---|---|---|
| `/index.html` (and `/`) | `<meta refresh>` to `jogo/<TREE>/`; replaced last, atomically, on each deploy. **M2:** `/` is the app's page and nginx no longer serves this file; `/jogar` sends players to the build `www/current` names (see (F)) | `Cache-Control: no-cache` |
| `/jogo/<TREE>/` | `index.html`, `jogo.tar.gz` (the game, about 0.5 MB), `favicon.png`, `golden.txt`. `TREE = git rev-parse <sha>:src/jogo_de_carro <sha>:web <sha>:tools/web_build.py \| git hash-object --stdin` (everything the build is made of); never changes once published; old builds stay | `Cache-Control: public, max-age=31536000, immutable`; `Content-Security-Policy: frame-ancestors 'none'; connect-src 'self'` (load-bearing, see (D)) |
| `/cdn/` | pygbag 0.9.3's runtime (14 files, 23 MB; `.wasm` 13.4 MB → 4.5 MB gz), byte-identical to `web/cdn.lock`, plus `.gz` copies of every `.wasm`/`.data`/`.js` for `gzip_static`; files are only ever added | immutable as above; `Content-Security-Policy: frame-ancestors 'self'` (pygbag's hidden `empty.html` iframe) |

All three: `X-Content-Type-Options: nosniff`. No COOP/COEP. `ops/nginx/jogo.conf` implements this; Cloudflare terminates TLS in front of it.

**Pipeline:** `tools/web_build.py` → `build/www` (mirror fetched from `https://pygame-web.github.io/cdn/` and checked against `web/cdn.lock`; WAV → OGG; `_build.py`; `pygbag --build --no_opt --cdn /cdn/0.9.3/ --template <mirrored default.tmpl>`; PYGPI script inserted). CI job `web`: golden gate in the runner's Chrome on `http://localhost:4173/jogo/<TREE>/index.html?golden=1` with `MAP * ~NOTFOUND, EXCLUDE localhost`, writes `golden.txt`, uploads `www.tgz`. Job `deploy`: `ssh jogo@VPS "<sha> <golden>" < www.tgz`; no repo code runs in that job. `jogo-deploy`, after its own golden check: at most 100 MB on stdin, only regular files and folders with names matching `^[A-Za-z0-9_][A-Za-z0-9._-]*(/…)*/?$` (no `/`, `..`, dot files, links or devices), 300 MB and 1000 entries unpacked at most (a build has 32), modes reset to `u=rwX,go=rX`, `jogo/<TREE>/index.html` present, `golden.txt` equal to the expected digest, `index.html` pointing at that TREE. `index.html` is replaced only when the commit is still the tip of `origin/main` or `origin/web-platform`: deploys can finish out of order, and an older one only adds its `jogo/<TREE>/`.

**Found while building it:**
- On Linux, pygbag's packer "optimizes" assets unless `--no_opt`: it re-encodes every sound to mono and runs `pngquant` on every PNG when installed, which would change the collision masks. macOS skips that step, so local and CI builds would differ.
- pygbag's runtime treats any `//localhost:<port>/` page as its own test server and takes wheels from `http://localhost:<port>/cdn/` (`cpythonrc.py`, near `PYCONFIG_PKG_INDEXES_DEV`); port 8666 also turns on dev mode. So the CI gate on localhost does not exercise the PYGPI path; it was checked by hand on a non-localhost origin (`MAP jogo.test 127.0.0.1, MAP * ~NOTFOUND`): the URL becomes `?PYGPI=/cdn/`, the wheel comes from `/cdn/cp312/`, the title screen and a race run, and the save survives a reload.
- pygbag asks "navigate away?" on `beforeunload` by default; tools/web_build.py passes `--can_close 1`, so SITE leaves without a prompt.
- Two builds of one TREE are not byte-identical (tar and gzip timestamps, the runner's ffmpeg), only equivalent: `jogo-deploy` keeps the first. A local build with uncommitted inputs is named `dev` and can never be deployed.

**Changed from §3/§7/§8, and open decisions:**
- Menu: CONTRA O BOT is 4th, not 2nd (keeps the `focus=` indices, `tests/test_smoke.py` and the demo tour). **Open:** move it to 2nd?
- On the web SAIR is hidden, not replaced by SITE: in M1 the site's root only redirects to the game, so SITE comes with M2's site.
- Frame time, wasm in headless Chrome 155 on the dev Mac (Normal, both cars invulnerable, 1200 frames): versus p95 11.4 ms vs solo 11.3 ms at 1×; 50.8 vs 51.6 ms under the 4× throttle. Versus adds about 0.1 ms; the cost is the shared full-screen software draw (about 10 ms at 1×), so the 30 Hz rival-half redraw was dropped from §8. **Open:** re-scope the gate (for example p95 ≤ 20 ms at 1× on a real laptop, 4× recorded only) or make the 4× number a web-draw task that covers solo too (suspects, not measured: the full-screen alpha layers in `faded()` and the vignette).
- §7 step 4 (print the versus frame time in CI) was dropped: a runner's number says nothing about players' machines.
- **Open:** pushes to `main` and to `web-platform` both publish to the same site.

---

# (F) M2 server notes (2026-10-20)

`server/` (uv project `jogo-server`, package `jogo_server`): `app.py` (routes, `Config` from the environment, startup check), `auth.py` (sessions, links, hashing, rate limits, nicknames, Google's rules), `db.py`, `mail.py`, `schema.sql`, ten Jinja templates and `site.css`. 58 tests in `server/tests/`. uvicorn on `127.0.0.1:8090` behind nginx (§7's Caddy and port 8000 do not apply: (E), and 8000 is taken on the VPS).

**Locked set** (`exclude-newer = "2026-10-07T03:00:00Z"`, the end of 2026-10-06 in Brasília written as an instant: uv reads a plain date in the local timezone, so `uv lock --check` failed on a UTC runner; now the same `uv.lock` from uv 0.12.23 and 0.13.3 in any timezone): exactly §2's versions (starlette 1.7.0, uvicorn 0.54.0, jinja2 3.1.6, python-multipart 0.0.32, argon2-cffi 25.1.0, authlib 1.8.0, httpx 0.28.1, itsdangerous 2.2.0). No pydantic: M3's WebSocket envelopes are checked by `hub.fits` ((H)). authlib 1.8 and starlette 1.7 now warn that their httpx fallback is deprecated in favour of the `httpx2` fork; it works, the warnings are filtered in pytest. **Open:** move to httpx2 at the next bump.

**Changed from §4/§5, or decided where they were silent:**
- `Referrer-Policy: same-origin`, not `no-referrer`: with `no-referrer` Chrome sends `Origin: null` on the site's own form POSTs, so the Origin check refused every form. Found only in the headless-Chrome walk (TestClient always sends the header); `/senha?t=` still never leaks to another site.
- uv caches a directory's built wheel until its `pyproject.toml` changes, so a fresh venv for a new commit got the previous commit's server and game (seen: a fresh `uv sync --frozen --no-editable` installed a stale `app.py`). `server/pyproject.toml` sets `reinstall-package = ["jogo-server", "jogo-de-carro"]`, so every sync rebuilds both (about 1 s). `jogo-deploy` relies on that setting (checked with uv 0.12.23: without it a fresh venv gets the stale build, with it the new code).
- `/saude` and `/jogar` use the build read from `$JOGO_WWW/current` at startup, the one whose golden was checked, not the file's value at request time: a build published but not yet restarted into is never handed out. A `current` that is not 40 hex digits (or `dev`) refuses startup. In dev `/saude` says `golden: false` (nothing was checked).
- Hashing budget: at most 8 hashes running or waiting; the 9th request gets 429. `/senha` hashes before it uses the link up, so a 429 never spends a link.
- Rate limits, after review: the windows are swept once a minute (each key by its own window) and a refused attempt stores nothing, so a request costs the same with 150k keys as with none; the login key holds at most 254 characters of the unchecked address. Besides each IPv6 /64, each /48 has its own ceiling (300 logins and 20 links an hour), so one tunnel-broker allocation cannot keep the 8-hash queue full; `ponytail:` a carrier that puts many players in one /48 shares it. The per-address link limit counts the inbox (no `+tag`, Gmail without dots), and links also stop at 280 a day, under the relay's free 300 (past that the relay would drop mail silently). **Accepted trade-off:** the global caps (50 an hour, 280 a day) can still be spent by someone with enough /48s and IPv4 addresses, which pauses signup and "Esqueci a senha" for everyone until the window passes; logging in is unaffected.
- A login checks, with nothing awaited in between, that the hash it verified is still the account's before it creates the session, and its rehash only replaces that same hash: a password reset that lands while an old-password login is hashing wins.
- Pages send `Strict-Transport-Security: max-age=63072000` (no `includeSubDomains`: `pericles.dev.br` has other sites), and nginx redirects anything Cloudflare did not receive over https (§7's Caddy did both; (E) had dropped them).
- A rate-limited link request answers 429 "Muitas tentativas" instead of the usual reply: the limits count every request, known address or not, so the answer says nothing about accounts.
- Bans (no UI in M2): a banned account's sessions are ignored and its address gets no link.
- Google: `userinfo` must carry a string `sub` and `email`, and `email_verified` must be literally `true`; an address already linked to another Google account is refused, never relinked; any exception during the token exchange shows a refusal page. The state, nonce and PKCE verifier live in `__Host-g` (10 min).
- Friends: `recusar` and `remover` both delete the pair's row (both parties may end it); asking someone who already asked you accepts.
- "Excluir conta" for an account without a nickname asks for the email instead.
- Mail: STARTTLS always, except with `JOGO_DEV=1` (local sinks speak plain SMTP); a failed send is logged without the address or the link. Every link request is mailed (signup and reset are one flow), so known and unknown addresses get the same reply and the same mail.
- `/privacidade` names Péricles Feitoza as the controller and `ADMIN_EMAIL` as the contact. **Open:** confirm (C9).
- Game: on the web, SAIR became SITE (`platform.window.location.href = "/"`) on the title and results screens, and Esc on the title moves to it as it moves to SAIR on the desktop. No "sair do site?" prompt: the build passes `--can_close 1`. `tests/test_versus.py`'s web-menu test now checks SITE.
- M3 hooks: `same_origin(conn)` takes any Starlette connection, so `/ws` calls it before `accept()`; `end_sessions` has the `hub.kick(uid)` slot; `schema.sql` gets "-- migration 2" for matches and runs.

**Ops (`ops/`), changed from §7 or decided where it was silent:**
- One venv per deployed commit (`/srv/jogo/venvs/<sha>`, the 3 newest kept, always the running one); `venvs/current` switches by an atomic rename. A redeploy of the running commit reuses its venv.
- No drain in M2 (no races to drop); M3 adds it before the restart (see (G)).
- Before switching, `jogo-deploy` takes a verified database copy (`/var/backups/jogo/deploy-*`, 14 kept apart from the daily ones): the new server may migrate the schema at startup, and a rollback puts the previous server back on it.
- A failed `/saude` check puts back `www/current` and the previous venv: the previous server would otherwise check its golden against the new build and refuse to start. Commits without `server/` only add their `jogo/<TREE>/` and never write `current` (a running newer server would check a foreign golden at its next restart). A first failed deploy, with no previous venv, leaves the service retrying every 5 s until a good deploy.
- The deploy's output also goes to `/srv/jogo/cache/deploy.log` through `tee -p`, so a dropped CI connection can no longer kill the script (SIGPIPE) before its rollback.
- After a failed `nginx -t`, `setup.sh` puts the previous site file back and does not reload: the running nginx never loaded the broken file, and a reload would also apply other sites' unreloaded edits.
- Backups run at 04:00 America/Sao_Paulo as user `jogo` (a root `sqlite3` could leave root-owned `-wal`/`-shm` files), and each copy is restored and passes `PRAGMA integrity_check` before it joins the 14 kept. `ponytail:` local only; the off-site copy (C8) is the next step.
- nginx keeps no access log and logs only critical errors (an error line carries the request, so an emailed link's token, and the player's address); `CF-Connecting-IP` is stripped before the app. `jogo.service` is hardened (`systemd-analyze security` 1.7). `setup.sh` writes `SESSION_SECRET` without putting it on a command line.
- **Open:** uvicorn logs every WebSocket accept with the player's address even with `--no-access-log`: M3's server lowers uvicorn's loggers to WARNING at startup (done, see (G)). The deploy user cannot read `journalctl -u jogo`, so a failed deploy in CI only points there. `/` answers 502 from `setup.sh` until the first server deploy finishes. nginx listens on IPv4 only, as before.

**Checked by hand:** the dev site in headless Chrome 155 against an aiosmtpd sink: signup, the emailed link opened twice, password, a reserved nickname refused, nickname, a second player's friend request accepted, `/conta`, Sair, a wrong password, login, the used link refused, `/jogar` booting the game. Pages at 1280 and 390 px wide.

---

# (G) M3 operations notes (2026-10-20)

**Changed from §7/§8, or decided where they were silent:**
- **Drain file:** `/srv/jogo/cache/drain`, not `/srv/jogo/drain`.
  - `/srv/jogo` belongs to root, so that `jogo` cannot replace its own deploy key, and the deploy runs as `jogo`.
  - It is the server's `Config.drain` default; no setting names it (the review found `JOGO_DRAIN`, which had only that one allowed value, and the deploy's gate on it redundant: removed, (H)).
- **Deploy order:** publish the build → newest-commit check → drain and wait → database copy → switch → health check → rollback if needed. The copy comes after the wait, so it holds the drained runs' results.
- **Wait:**
  - It polls `/saude` every 5 s.
  - A server that reports no `ativas` (M2's) or does not answer means no wait.
  - At 31 min it restarts anyway and says so. Every run that started before the drain has ended by then, so a count above zero is a server bug, and it must not block deploys forever.
  - It prints a progress line each minute, which also keeps CI's ssh connection from idling out.
- **Drain file removal:** an `EXIT` trap removes it on success, rollback, failure, timeout and `SIGTERM` (bash runs `EXIT` traps on `SIGTERM`; checked). Only `SIGKILL` leaves it behind: `rm /srv/jogo/cache/drain`. `ponytail:` two deploys queued on the flock drain twice; the second wait is usually seconds.
- **`setup.sh` never restarts a running server**, because that dropped every live race. It only starts a stopped one. A changed unit or env takes effect at the next deploy, which drains first.
- **`setup.sh` and an existing `/etc/jogo/env`:** left untouched, as in M2. The M3 keys (`MAX_ATIVAS`, `FLAG_*`) are in `env.example` for new boxes, and their values equal the server's defaults, so an older env behaves the same; add `MAX_ATIVAS` by hand after `jogo-admin load` (the first version appended the missing keys with awk; removed, (H)).
- **uvicorn's address lines** (closes the (F) open item): with `--no-access-log` alone, uvicorn 0.54 still logs `<ip>:<port> - "WebSocket /ws" [accepted]` and "connection open" at INFO. The app sets `uvicorn.error` and `uvicorn.access` to WARNING in its lifespan, so neither line appears whatever the unit's flags (checked with real uvicorn at its default `info` level; (H)). The unit's `--log-level warning` was dropped as redundant; the app's own `jogo` logger has its own INFO handler and prints one line per finished run.
- **`jogo-admin`** (`/usr/local/bin`, installed by `setup.sh`):
  - It runs `python -I -B -m jogo_server.admin`, or `jogo_server.load` when the first argument is `load`, as `jogo`, in `venvs/current`, from `/`.
  - The environment is clean. It holds exactly `/etc/jogo/env`'s `KEY=value` lines, read as data and passed through the environment (never a command line, never `source`), plus `PATH`, `LANG` and `PYGAME_HIDE_SUPPORT_PROMPT=1`. pygame's banner would otherwise go to stdout and corrupt `export`'s JSON. `load` needs the whole file, because it builds its config with `Config.from_env()`.
  - A non-root caller is re-executed through sudo.
  - §8's `python -m server.load --n 100` is `jogo-admin load --n 100`.
- **New keys in `env.example`:** `MAX_ATIVAS=100`, and `FLAG_MIN_N=30`, `FLAG_P10=7`, `FLAG_MEDIAN=12`, `FLAG_ADHERENCE=0.99`. The `FLAG_*` values are §6.7's rule, with the reaction thresholds in ticks.

**What ops relies on from the server:**
- The drain file is checked on every new run, never cached at startup: the new server starts while the file still exists.
- `/saude`'s `ativas` is an int that counts every run from admission to `result`.
- `admin export` writes only the `--replay` log to stdout.

**Checked** (before the review removed the deploy's `JOGO_DRAIN` gate, `setup.sh`'s env append and the unit's `--log-level warning`, so those lines below describe the earlier version) in a linux/amd64 Ubuntu 24.04 container. `systemctl` was a stub that runs `jogo.service`'s `ExecStart` as `jogo` with its `EnvironmentFile`; uv, the game venv and the server were stubs, and the origin repository was local. Results:
- **An M2 box:** M2's `setup.sh`, the user's env edits (`MAIL_FROM` with spaces, a line holding `$(…)` and backticks), and the M2 server deployed by M2's `jogo-deploy`.
- **M3 `jogo-deploy` before M3 `setup.sh`:** refused with the message; `current` and the running server were unchanged.
- **M3 `setup.sh`:**
  - The old env is a byte-identical prefix; mode and owner are kept; the six keys were appended with their comments, each key once.
  - `jogo-admin` was installed, and the unit has `--log-level warning`.
  - No restart, only `systemctl start`.
  - A second run appends nothing.
  - An env missing two keys and its final newline gets exactly those two, after the added newline.
- **Deploy over the M2 server:** no wait, and the new server runs the M3 unit with `JOGO_DRAIN` and `MAX_ATIVAS`.
- **Deploy with 2, then 1, then 0 live runs:**
  - It waited about 18 s and restarted only after 0.
  - The running server saw the drain file through its own `JOGO_DRAIN`.
  - The backup came after the wait, and the drain file was gone afterwards.
- **A new server that never comes up:** drain, rollback, exit 1, drain file removed.
- **A run that never ends (cap lowered to 65 s for the test):** "(0 min)" and "(1 min)" lines, then "reiniciando assim mesmo", exit 0, file removed.
- **`SIGTERM` while draining:** exit 143, file removed, nothing switched.
- **`jogo-admin`:**
  - It runs as `jogo` with cwd `/`, `-I`, and no `.pyc` written.
  - `MAIL_FROM` arrives intact; the `$(…)` line arrives literally and nothing ran.
  - The caller's `FOO` and `PYTHONPATH` did not pass through.
  - `export` output is byte-identical to the stored log; `load --n 3` gets the env.
  - A user without sudo rights is refused.
- **Lint and unit check:** `shellcheck -x` is clean, and `systemd-analyze verify jogo.service` passes.

**Not checked:** the real server under systemd's sandbox, CI's real ssh connection through a long drain, and the real `admin`/`load` modules on the VPS (first M3 deploy).

---

# (H) M3 server and client notes (2026-10-21)

**Server, changed from §5/§6 or decided where they were silent:**
- **Envelopes:** `hub.fits` against `hub.SHAPES`, no pydantic: exact JSON types (`true` is no int), every field and no other, `mode`/`skin` from the known values, frames up to 16 KB, 30 messages/s with a burst of 60. `fin.score` must also be in `0 ≤ score < 2**53` (it is stored; a 2**63 overflowed SQLite and left the row `live`). A wrong frame voids the run (`invalido`), then `error bad` and close 1008.
- **Login:** a logged-out or nickname-less socket is accepted, gets `error login` (its own text without a nickname), then 1008, so the game plays offline and CI's `NET OK` gets a reply. A cross-origin socket is refused before accept (uvicorn answers 403). A kicked session (sair de todos, new password, deleted account) gets `login` too; a second tab gets `busy`. The game never reconnects by itself after `login`, `version` or `busy`.
- **Version:** a mismatch is `error version`, not `update`.
- **`welcome`** carries only `me`; friends, challenges and requests come with M4/M5.
- **Order inside `in`:** `feed` (validation), then pacing, then `advance`. `k` must be checked before `k/120`, or a huge int overflows the float. A non-`fin` `in` must have `k` on the 12-tick grid, so `arr` holds at most one entry per 12 ticks.
- **Give-ups:** `leave` after `go` gives up at the last `k`; before `go` it uses the attempt up (`prazo`). A `fin` must move `k` on, as every other `in` (the client plays one more tick for a give-up on a reported tick); the first version's special case for `k == last k, ev: []` was dead and was removed.
- **Pacing and stalls:** `adiantado` uses the raw lag (a stall only makes messages later). `ritmo` subtracts a **credit**: the server's stall of the last 3 s (after the run's `go`), from a deque of the ticker's marks. It covers the backlog a stall piles up, and lapses 3 s after it; the first version subtracted every stall since `go` for the rest of the run, so one 3 s stall turned the 2 s limit into 5 s. The rate limit's ceiling grows by 30 messages per second of the same credit, so a 7 s stall's 70-message backlog no longer voids honest runs. `max_lag` stores the compensated lag; the raw arrival of every message is in `arr`.
- **`arr`:** `[k, ms after t0]` per message (`lag_up` needs `k`). It is the time the server handled the message: a backlog lands at once. `lag_up` leaves out the last wall-clock second, so a run that ends inside a stall does not count the stall as a rise.
- **The board:** table `bests` (one row per player and mode: the best `ok` solo run), kept by the trigger `runs_bests` whenever a run enters or leaves `ok` (the hub's end, `admin aprovar`, `rejeitar`). `board()` and `place()` read it, so a run's end and the pages cost the same with a million stored runs as with a thousand (measured at 1M runs, 2000 players: `board` 1.9 ms, `place` 0.6 ms; it was 965 ms and 1413 ms). Every run is still stored.
- **Holds:** a new best that would enter the top 10 waits for review (`review/top10`), unless it scores 0 (nothing to verify: it is `ok`). One run per player and mode waits at a time: a run no better than the one in review is `rejected/substituida`; a better one replaces it (the old one becomes `rejected/substituida`). The bot rule applies to new bests that would place 11–100.
- **Starts:** 60 ranked starts an hour per player, then `error rate`.
- **Memory:** a worst-case run (keys toggled every tick until the 54k-event cap) holds about 6.3 MB traced: the events are most of it, and `arr` is a flat `array('i')` (18k arrivals in 144 KB; as lists they took 2.3 MB). `MAX_ATIVAS=100` is about 700 MB with the server's 61 MB, under the unit's `MemoryMax=1G`. Size `MAX_ATIVAS` by CPU with `jogo-admin load` and keep it at 100 or below unless `MemoryMax` grows.
- **No `matches` table** and no `match_id` yet: M4 adds them.
- **Known misses** (§6.7, §6.10): corridor readers with a human-scale delay are not flagged; seed shopping by instant give-ups is possible within the start limit. Both are left to the top-10 hold and review.

**Client, changed from §3:**
- **A version refusal goes to `/jogar`**, not a reload: the page `/jogo/<old tree>/` is immutable, so a reload brings the old build back. At most once per build (`sessionStorage`); refused again, the runtime itself differs and the game plays offline.
- **A give-up on a tick already reported** plays one more tick with no input and sends `fin` with `k = previous + 1, ev: []`.
- **The hello names the car**, so a skin changed before JOGAR opens a new socket with a new hello.
- **Refusals** show the server's own text (`hub.REFUSED`, short enough for the waiting screen's heading); the game keeps no table of its own.
- **Double `solo`:** Esc before the match and JOGAR again within one round trip can send a second `solo` while the first run is live, which the hub treats as a violation (1008). It needs a round trip over about 0.6 s (menu transitions block input for 0.3 s each).
- **`result` can arrive before the client's `fin`** (the server's simulation crashed first); the client takes it as the end of the run.

**Ops, after review:** no `JOGO_DRAIN` setting and no deploy gate on it; `setup.sh` no longer appends keys to an existing `/etc/jogo/env`; uvicorn's address lines are silenced by the app alone ((G)). Re-running `setup.sh` from the M3 commit's `ops/` before its deploy is still the rollout (it installs `jogo-admin` and the no-restart behaviour), but the deploy no longer enforces it.
