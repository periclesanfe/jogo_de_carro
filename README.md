# Jogo de Carro

[![CI](https://github.com/periclesanfe/jogo_de_carro/actions/workflows/ci.yml/badge.svg)](https://github.com/periclesanfe/jogo_de_carro/actions/workflows/ci.yml)

A pixel-art endless runner on a five-lane road: dodge traffic, stones, potholes and rolling logs, grab coins and survive until the clock runs out.

<p align="center">
  <img src="docs/media/gameplay.gif" alt="Gameplay: the yellow car weaves between traffic, cones and stones on a five-lane road, collecting coins while near-miss popups build a x5 combo." width="640">
</p>

Originally a 2022 team project at IFAL (Instituto Federal de Alagoas), rebuilt in 2026 on Python 3.14 and pygame-ce with new art, synthesized music, tests and cross-platform releases. The UI is in Brazilian Portuguese.

## Play

**Download:** grab the zip for Windows, macOS (Apple Silicon) or Linux from [Releases](https://github.com/periclesanfe/jogo_de_carro/releases/latest), unzip it and run `jogo-de-carro` (`jogo-de-carro.app` on macOS). The builds are not code-signed, so the first launch needs *More info → Run anyway* on Windows. On macOS, open the app once, then allow it in *System Settings → Privacy & Security → Open Anyway* (or run `xattr -dr com.apple.quarantine jogo-de-carro.app`).

**From source** (Python 3.12+, developed on 3.14; on Windows use `py` instead of `python3`):

```bash
git clone https://github.com/periclesanfe/jogo_de_carro.git
cd jogo_de_carro
python3 -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
jogo-de-carro                                       # or: python -m jogo_de_carro
```

## Controls

| Action | Keyboard | Gamepad |
| --- | --- | --- |
| Change lane | `A` `D` / `←` `→` | Left stick / D-pad |
| Move up and down | `W` `S` / `↑` `↓` (hold up for +15% score) | Left stick / D-pad |
| Confirm | `Enter` / `Space` | A |
| Back / pause | `Esc` / `P` | B / Start |
| Give up the run | `R` | |
| Mute / fullscreen | `M` / `F11` | |

Menus also work with the mouse, and there is a clickable pause button in the race HUD.

## Modes

The four difficulties keep the win times of the 2022 version. Normal is the default.

| Mode | Survive for | Road |
| --- | --- | --- |
| Fácil | 1:30 | Cars, stones, potholes and cones; vans and rolling logs later on; up to 2 lanes blocked per row |
| Normal | 3:00 | Adds vans, rolling logs and trucks as the run goes on; up to 3 lanes blocked |
| Difícil | 4:30 | Everything from the start, higher top speed; up to 4 lanes blocked |
| Infinito | 30:00 (the run cap) | Speed keeps climbing; 4 lanes can be blocked after 2:00 |

## Features

- 26 cars, each with a record of its own, picked on a turntable in the garage: six free, and 20 bought in the garage with the coins online runs pay (the server keeps the wallet and the cars).
- Contra o bot: the same road side by side against a FÁCIL, MÉDIO or DIFÍCIL bot; whoever lasts longer wins, then points decide. It sets no records.
- A spawner that always leaves a reachable free lane, sized for the lane-change time at the current speed and kept close to the lane you are in; a test checks 10,000 rows per mode with an independent solver.
- Traffic that signals with a blinker before changing lanes, logs that roll across lanes, potholes that only hurt in the middle.
- Coins, a shield that absorbs one hit, and near misses (dodging at the last moment) that build a combo up to x5.
- Countdown, slow-motion crash with screen shake and sparks, a victory lap with confetti, pause with a blurred backdrop.
- Best score per mode and per car saved as JSON in the user data folder; a corrupt save falls back to defaults.
- Fixed-step simulation (120 Hz) inside an async main loop, so the same code runs in the browser (pygbag).

## Screenshots

<p align="center">
  <img src="docs/media/title.png" alt="Title screen: the JOGO DE CARRO logo with a flaming tire over the road, menu with Jogar, Skin, Dificuldade, Contra o bot and Sair." width="49%">
  <img src="docs/media/race.png" alt="Race: a QUASE! near-miss popup next to the yellow car, the combo pill under the score, timer and speedometer." width="49%">
  <img src="docs/media/garage.png" alt="Garage: the blue police car on a turntable between the other cars." width="49%">
  <img src="docs/media/difficulty.png" alt="Difficulty cards for Fácil, Normal, Difícil and Infinito with goal time, speed and obstacle bars and the best score." width="49%">
  <img src="docs/media/pause.png" alt="Pause menu with Continuar, Reiniciar and Menu over a blurred race." width="49%">
  <img src="docs/media/results.png" alt="Victory screen: VOCÊ VENCEU!, time, distance, coins, near misses, score and NOVO RECORDE! with confetti around the card." width="49%">
</p>

## What changed in v2

| | 2022 | 2026 |
| --- | --- | --- |
| Runtime | Python 3.10, Pygame 2.1.2 | Python 3.14, pygame-ce 2.5.8 |
| Code | 806 lines, global state in `config.py`, screens that call each other recursively | A package with a scene stack, a fixed-step loop, no mutable globals, type hints |
| Art and audio | Sprites drawn in Piskel, MP3 music | Pixel art, sound effects and music generated by `tools/make_assets.py`, keeping the six car colors and the flaming-tire icon |
| Gameplay | Dodge obstacles, survival timer | Adds lane tweening, a fair spawner, coins, shield, near-miss combos, signalling traffic, countdown, pause, records, gamepad |
| Quality | No tests | pytest suite, Ruff, GitHub Actions |
| Distribution | A ~110 MB Windows build committed to the repository | Zipped builds for Windows, macOS and Linux attached to each release |

The 2022 code is still in the git history (up to commit `7f1a41b`).

## Project structure

```
src/jogo_de_carro/
  app.py              Game: window, fixed-step async loop, global keys
  settings.py         constants, asset manifest, difficulty presets
  assets.py audio.py save.py input.py ui.py tween.py particles.py
  run.py              one race as a pure function of seed and inputs; input logs, replay, validation
  golden.py           determinism digest that the web build and the server must reproduce
  scenes/             title, garage, difficulty, race, versus (contra o bot), pause, results
  world/              road, player, traffic, obstacles, pickups, spawner, scoring, autopilot
  assets/             generated sprites, sounds and music (committed)
  replays/            input logs replayed by golden.py and the tests
  demo.py             scripted tour used for screenshots and the GIF
tests/                spawner fairness, rules, assets, input, drivers, runs and replays, versus, web save, headless smoke test
tools/
  make_assets.py      deterministic generator for every sprite, sound and track
  screenshots.py      renders the demo tour to PNGs
  web_build.py        the browser build (pygbag) into build/www
  pyinstaller_entry.py
web/                  main.py (the browser entry point) and cdn.lock (the pinned pygbag runtime)
server/               the site: accounts, friends, /jogar (Starlette, SQLite; see "Servidor")
ops/                  VPS setup, the deploy script CI runs there, the nginx site
.github/workflows/    ci.yml (lint, tests, web build and its golden gate, deploy), release.yml (PyInstaller builds on v* tags)
```

## Development

```bash
pip install -e ".[dev]"
pytest                              # runs headless; JOGO_STRICT_ASSETS=1 fails on any missing asset
ruff check . && ruff format --check .
python tools/make_assets.py         # regenerate every asset (same seed, same bytes)
python tools/screenshots.py shots   # scripted demo: one PNG per scene plus GIF frames
JOGO_AUTOPILOT=1 python -m jogo_de_carro   # watch the demo play itself
JOGO_RECORD=runs python -m jogo_de_carro   # save every race's input log to runs/<mode>-<seed>.json
python -m jogo_de_carro --replay runs/normal-123.json   # play a saved log back
python -m jogo_de_carro.golden      # print the determinism digest (GOLDEN <sha256>)
```

Set `JOGO_SAVE_DIR` to keep the save file somewhere other than the user data folder. Pushing a `v*` tag builds the three platforms and publishes the release.

## Web build and deploy

The browser version is this package run by [pygbag](https://pygame-web.github.io) 0.9.3 (CPython 3.12.12 and pygame-ce 2.5.7 compiled to WebAssembly), with pygbag's runtime self-hosted:

```bash
pip install pygbag==0.9.3                          # plus ffmpeg on the PATH (the sounds ship as OGG)
python tools/web_build.py                          # writes build/www
python -m http.server 4173 --directory build/www   # open http://localhost:4173/
```

`build/www` is the whole static site: `index.html` redirects to `jogo/<tree>/` (and `current` names it, for the server's `/jogar`), the game, named after everything it is built from (`git rev-parse HEAD:src/jogo_de_carro HEAD:web HEAD:tools/web_build.py | git hash-object --stdin`, or `dev` while those have uncommitted changes), and `cdn/` holds pygbag's runtime, checked against `web/cdn.lock`. Everything but the top `index.html` and `current` can be cached forever. In the browser the save lives in localStorage, and `?golden=1` on the game's URL logs `GOLDEN <sha256>` to the browser console instead of starting the game.

On pushes to `main` and `web-platform` and on pull requests, CI builds the site and opens `?golden=1` in headless Chrome with every host but localhost blocked: the digest must equal `python -m jogo_de_carro.golden` on CPython 3.12.12. On a push to `main` or `web-platform` it then sends the build to the VPS, where `ops/jogo-deploy` (the deploy key's only command) installs that commit, refuses it unless the VPS's own digest matches too, and publishes it into `/srv/jogo/www`. Each deploy of a commit with `server/` installs the server into `/srv/jogo/venvs/<sha>`, drains the running server (it creates `/srv/jogo/cache/drain`, so no new ranked run starts, and waits until `/saude` reports `"ativas": 0`, at most 31 minutes), copies the database, writes `/srv/jogo/www/current` and restarts `jogo.service` (only while that commit is still its branch's newest). The drain file goes away on every way out; only a killed (`SIGKILL`) deploy can leave it behind: `rm /srv/jogo/cache/drain`. `/saude` must report the new build with `golden: true` within 60 s; otherwise the deploy switches back to the previous server and build and fails. Its output is also kept in `/srv/jogo/cache/deploy.log`. One-time VPS setup, as root, from a copy of `ops/` taken outside `/srv/jogo`:

1. `bash setup.sh 'ssh-ed25519 AAAA... jogo-ci'` (the certificate from `certbot --nginx --no-redirect -d jogo.pericles.dev.br` must already exist) creates the `jogo` user, the pinned Python, the checkout, `/srv/jogo/www`, `/var/lib/jogo`, `/etc/jogo/env` (once, with a random `SESSION_SECRET`; fill Google/SMTP later, then `systemctl restart jogo`; never overwritten: a key `ops/env.example` gained later is the server's default until you add it), `jogo.service` and its only sudo rule, `jogo-admin`, the needrestart exclusion, the daily backup (`/var/backups/jogo`, 14 copies, each verified by a restore; restore steps in `ops/jogo-backup`) and the nginx site (`nginx -t`, previous file restored if it fails). Re-run it whenever `ops/` changes, with the same key. It never restarts a running server (that would drop live races): a changed unit or env takes effect at the next deploy.
2. In the repository's `deploy` environment, set the secrets `DEPLOY_HOST`, `DEPLOY_SSH_KEY` (the private half of that key) and `DEPLOY_KNOWN_HOSTS` (the line `setup.sh` prints). The deploy job is skipped until `DEPLOY_HOST` exists.

## Servidor

`server/` is the site around the game (`jogo-server`, Starlette + SQLite, plan in `docs/web-platform-plan.md`): the landing page, accounts (email link + password, or Google), nickname, friends, `/conta` and `/privacidade`, and `/jogar`, which sends a logged-in player with a nickname to the current build. Pages are server-rendered with no JavaScript. It runs on CPython 3.12.12 + pygame-ce 2.5.7 like the browser, and refuses to start unless `python -m jogo_de_carro.golden` on its own CPU equals the build's `golden.txt`. Dependencies are locked in `server/uv.lock`.

```bash
cd server
uv sync && uv run pytest                           # the server's tests (needs uv and Python 3.12.12)
python ../tools/web_build.py                       # optional: a local game build for /jogar (build/www)
JOGO_DEV=1 JOGO_DB=jogo-dev.db JOGO_WWW=../build/www SMTP_HOST=localhost SMTP_PORT=1025 MAIL_FROM=jogo@localhost \
  uv run uvicorn jogo_server.app:app --port 8090   # open http://localhost:8090 (not 127.0.0.1: POSTs must come from DOMAIN)
```

`JOGO_DEV=1` serves the site over http on `localhost:8090` (or `DOMAIN`), skips the runtime check, sends mail without STARTTLS to any local SMTP sink (for example `python -m aiosmtpd -n -l localhost:1025`) and serves `build/www`'s `/jogo/` and `/cdn/` itself. In production the settings come from `/etc/jogo/env` (`ops/env.example`): without `GOOGLE_CLIENT_ID` the Google button is hidden, and without `SMTP_HOST` signup says email is unavailable. `GET /saude` answers `{"build": ..., "golden": true, "ativas": ...}` (`ativas`: ranked runs in progress, from M3).

## Ranked runs and review (M3)

Logged in on the web, JOGAR is a ranked run: the server reveals the seed only when the race starts, receives the inputs as they are played, re-simulates the run with the same code and checks it keeps real-time pace, and the score it computes is the official one (`/ranking`: the best run per player and mode). Without a login the game plays offline as before. A run that the bot detector flags (top 100) shows "Em análise" and waits for review; the server emails `ADMIN_EMAIL` at most once an hour while the queue is not empty.

On the VPS, M3 adds:

- **The drain** in `ops/jogo-deploy` (see "Web build and deploy"); `/saude` reports `ativas`.
- **`jogo-admin`**, the server's admin CLI run as user `jogo` in the running server's venv with `/etc/jogo/env`'s settings.
- **New settings** in `ops/env.example`: `MAX_ATIVAS` (runs at once; more get "Servidor cheio") and the bot detector's `FLAG_*` thresholds. Their values there are the server's defaults, so an existing `/etc/jogo/env` needs them only to change one: add the line by hand.
- **No player addresses in the journal:** the server lowers uvicorn's loggers to WARNING at startup (uvicorn otherwise logs every WebSocket connection with the player's address, even with `--no-access-log`).

Rolling it out, once: re-run `setup.sh` from a copy of the M3 commit's `ops/` before its deploy (it installs `jogo-admin` and stops restarting a running server).

Reviewing the queue, from the Mac (`meuhubprod` logs in as root):

```bash
ssh meuhubprod jogo-admin revisar                  # what waits for review
ssh meuhubprod 'jogo-admin export 123' > run.json  # run 123's input log
python -m jogo_de_carro --replay run.json          # watch it here; Esc pauses
ssh meuhubprod jogo-admin aprovar 123              # into the ranking; or: rejeitar 123, banir <apelido>
```

The replay is the server's own simulation, so replay it with game code equal to the run's build: `/srv/jogo/cache/deploy.log` pairs each deployed commit with its `jogo/<tree>/`.

Setting `MAX_ATIVAS`: while the site is quiet (the test competes with the live server for the VPS's two vCPUs), run `ssh meuhubprod jogo-admin load --n 100` (then other values of `--n`). It plays that many real-time ranked runs against a scratch copy of the server and reports the event loop's lag, the CPU used and every result: take the largest `n` whose p99 lag stays well under 500 ms with no run rejected for `ritmo` or `adiantado`, leave room for the other sites, and put `MAX_ATIVAS=<n>` in `/etc/jogo/env`. Memory bounds it too: a worst-case run holds about 6.5 MB, so keep `n` at 100 or below unless `MemoryMax=1G` in `jogo.service` grows. The next deploy applies it, draining first; `systemctl restart jogo` applies it at once but drops the races in progress.

## Live races and challenges with friends (M4, M5)

Logged in on the web, AMIGOS on the title lists the challenges you received, then every friend (added on the site), those in the game first and offline ones greyed; the list scrolls. Everything happens in the current mode:

- **CORRER AGORA** (friends in the menu) invites one to a live race, side by side on the same road; the invite shows over their game for 30 s. The server simulates both runs from the inputs, relays each player's inputs to the other no further ahead than the receiver's own position, and decides the race (the first to crash or give up loses; if both reach the end, the points). REVANCHE is a new invite.
- **DESAFIAR** (any friend, online or not) records your run on the versus road. Once it ends well, the friend has 7 days and one attempt to beat it: JOGAR races your run, streamed by the server at their own pace as a live rival's inputs are, and the server decides against the stored run. You get a toast if you are in the game. Your run cannot be thrown away once it has started: a lost connection or a rejected run counts as your loss (giving up just sends the shorter run). The friend's attempt is used as soon as they press JOGAR: missing the start, leaving or a lost connection loses it. At most 10 open challenges each.
- **`/partidas`** on the site lists your last 50 races and challenges, wins/losses/draws against each friend, and your runs "em análise".

Neither kind enters `/ranking`. `MAX_ATIVAS` counts both runs of a race, and a friend's challenge turn as two places (the recording is in memory too); `/saude`'s `ativas` counts runs. The drain refuses new invites and challenges. Protocol and decisions: `docs/web-platform-plan.md`, (I) and (J).

## Credits

The original 2022 game was made by:

- [Adenilson Silva dos Santos](https://github.com/adenilson666)
- [Eduardo Pedro da Silva](https://github.com/eduardopedro2)
- [Erimaiken Batista dos Santos](https://github.com/M4iKen)
- [Ingrid Mônica da Silva Bezerra](https://github.com/ingridmonica)
- [Péricles Andrade Feitoza](https://github.com/periclesanfe)

v2 modernization by Péricles Feitoza.
