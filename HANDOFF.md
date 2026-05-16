# Ticket to Ride — Handoff Doc

## What This Is
Full multiplayer online Ticket to Ride (North America).

- **Backend:** Flask + Flask-SocketIO (`async_mode="eventlet"`), SQLAlchemy
- **DB:** SQLite (default, `instance/tickettoride.db`) or PostgreSQL via `DATABASE_URL`
- **Frontend:** Vanilla JS + custom SVG board overlay (`static/images/board.svg`) — fully hand-traced, NOT a raster image
- **Identity:** Flask session cookie → `session_key` → `Player` row in DB
- **Run locally:** `python app.py` → http://localhost:5001
- **Python:** 3.14, Windows 11 dev machine

## Branches
| Branch | Purpose |
|--------|---------|
| `main` | Development — uses `async_mode="threading"`, no gunicorn |
| `aws-deploy` | Production on EC2 — eventlet + gunicorn + nginx, SQLite |
| `render-deploy` | Render.com config — eventlet + gunicorn + PostgreSQL |

**Deployed at:** http://52.54.184.133 (EC2 t2.micro, Ubuntu 22.04, us-east-1)

On the EC2 instance:
```bash
sudo systemctl restart tickettoride   # restart app
sudo journalctl -u tickettoride -f    # live logs
# to update: cd ~/TicketToRide && git pull && sudo systemctl restart tickettoride
```

## Key Files
```
app.py                    — Flask routes + all SocketIO event handlers + _run_bots
game_logic.py             — Full rules engine: draw, claim, tickets, scoring, BFS for longest path
game_data.py              — CITIES (36, pixel coords), ROUTES (95), DESTINATION_TICKETS (30)
models.py                 — Game + Player SQLAlchemy models; game state stored as JSON text column
route_segments.py         — Explicit per-route segment centers: {route_id: [[cx, cy, angle], ...]}
static/js/game.js         — All client-side: SVG rendering, socket handlers, modals, UI
static/css/style.css      — Dark antique theme (Cinzel font, gold accents)
static/images/board.svg   — Hand-traced SVG map (ocean, US landmass, Great Lakes)
templates/game.html       — Injects BOARD_DATA, GAME_CODE, MY_PLAYER_ID, MY_COLOR as JS globals
templates/lobby.html      — Pre-game lobby (share code, player list, Add Bot button)
templates/index.html      — Home (create / join)
scripts/label_debug.html  — Standalone drag tool for placing city label offsets (open in browser, no server)
deploy/setup.sh           — One-shot EC2 bootstrap (run from repo root on Ubuntu 22.04)
deploy/nginx.conf         — nginx reverse proxy config with WebSocket upgrade headers
deploy/tickettoride.service — systemd unit file
```

## Architecture Notes

### Game State
All game state lives in `Game.state_json` (a JSON text column). `game_logic.py` mutates the state dict in place, then `app.py` saves it back. State is a single dict:
```python
{
  "deck": [...],
  "face_up": [...],           # 5 face-up cards (None = empty slot)
  "dest_deck": [...],
  "claimed_routes": {},       # {route_id_str: player_id_str}
  "player_states": {
    "player_id": {
      "hand": {"red": 2, ...},
      "tickets": [1, 4, ...], # kept destination ticket IDs
      "pending_tickets": [],  # drawn but not yet kept
      "trains": 45,
      "route_score": 0,
    }
  },
  "current_player_id": "...",
  "phase": "initial_tickets | main | final_round | ended",
  "draw_step": 0,             # 0 = no draw yet, 1 = drew first card
  "action_log": [...],
}
```

### Socket Events
`_broadcast_state(game, code)` sends two events after every action:
1. `game_state` → personal room (player's session_key) — includes hand, pending_tickets
2. `game_state_update` → game code room — public data only (claimed_routes, face_up, etc.)

The client merges `game_state_update` carefully to avoid clobbering private hand/ticket data.

### Bot Players
Bots are `Player` rows with `session_key` starting with `"bot_"`. After every game action, `_run_bots(game, code)` iterates until the current player is human:
- `initial_tickets` phase: auto-keeps all pending tickets
- `main/final_round`: draws 2 blind cards

Host adds bots via "Add Bot" button in the lobby. Bots show a purple BOT badge.

### Board SVG Overlay
`game.js` renders a `<svg id="board-svg">` on top of `<img id="board-img">`. ViewBox is `0 0 1024 683`. Route segments use explicit `(cx, cy, angle)` data from `route_segments.py` (passed as `BOARD_DATA.route_segments`). Fallback: linear interpolation between city coords.

City label offsets are in `const LABEL_OFFSETS` at the top of `game.js` — all 36 cities manually placed using `scripts/label_debug.html`.

## What Was Recently Fixed / Added
- **Double-submit ticket bug:** `renderAll` now closes the ticket modal if pending_tickets clears while modal is open (race between `game_state_update` and `game_state`)
- **Ticket modal:** defaults to all unchecked; confirm button disabled until ≥2 selected (initial) or ≥1 (mid-game draw); free deselection allowed
- **Train card visuals:** 🚂 emoji on face-up cards; locomotive is rainbow gradient (`LOCO` label); hand cards are a single column
- **Route hover:** mouseenter/mouseleave on any segment highlights all segments in that route (brightness + glow)
- **Bot players:** full lobby UI + backend auto-play
- **game_logic.py:** `draw_blind`, `draw_face_up`, `claim_route` now all allow `final_round` phase (were incorrectly rejecting it)

## Feature Requests (Not Yet Built)
These came up during playtesting — implement in a new chat:

1. **Route completion indicator** — when you successfully claim a route, flash the segments or show a toast/banner (e.g. "+7 pts!" overlay on the board near the route)

2. **Ticket hover → highlight cities** — when hovering a ticket card in "YOUR TICKETS" panel, highlight the two endpoint city dots on the board (pulse or glow)

3. **Card draw animation** — when a face-up card is clicked or blind draw happens, animate the card flying into the current player's hand area (or off-screen to another player's side if it's not your turn and you're watching)

4. **Your turn sound notification** — play a sound when it becomes your turn. User will provide the sound file. Hook: in `renderStatusBar()` or `renderAll()`, detect transition from `current_player_id !== MY_PLAYER_ID` → `=== MY_PLAYER_ID` and play the sound. Need to store previous `current_player_id` to detect the transition.

## Known Issues / Things to Watch
- **SQLite on EC2:** data lives on the instance disk. If the instance is stopped/terminated, game data is lost. Fine for now.
- **Single gunicorn worker (`-w 1`):** required because socket rooms live in-process memory. Do not increase workers without adding a message queue (Redis + `socketio = SocketIO(app, message_queue=...)`).
- **Eventlet deprecation warning:** harmless, eventlet still works with Flask-SocketIO 5.x.
- **Free tier EC2 (t2.micro):** 1GB RAM. Has been fine in testing. Watch memory if you add more features.
- **No HTTPS:** the EC2 deployment is plain HTTP. Fine for playing with friends on a known IP, but browsers will warn about "not secure" on some features. Add a domain + Let's Encrypt (certbot) to fix.
