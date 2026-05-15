# Ticket to Ride — Agent Handoff

## What This Is
A full multiplayer online Ticket to Ride (North America) web app.
- Flask + Flask-SocketIO (`async_mode="threading"`) backend
- SQLAlchemy with SQLite (default) or PostgreSQL (`DATABASE_URL` env var)
- Vanilla JS + SVG overlay on `static/images/board.png` (1024×683px)
- Session-key based player identity; game state stored as JSON in DB
- Run with `python app.py` → http://localhost:5001

## Current Bugs (What Needs Fixing)

### Bug 1: Route segments on SVG don't align with the printed board
The city coordinates in `game_data.py` `CITIES` dict are wrong/estimated.
The SVG rendering in `static/js/game.js` interpolates route segments between
city coordinates — so wrong cities = wrong routes.

**Fix in progress:** A full board calibration pipeline was built. The user has
already clicked all 36 city dots and all ~280 train car slots (one click per slot,
per color). The detection script needs to be completed and its output wired in.

### Bug 2: Drawing cards doesn't show them in your hand; tickets don't appear
Root cause: `socket.on('game_state_update', ...)` in `static/js/game.js` line 56
overwrites `gameState.players` with generic state that has empty `hand` and
`tickets` for all players (since `get_public_state(state, "")` omits private data).

**Fix:** In the `game_state_update` handler, do NOT overwrite `gameState.players`.
Only update shared fields: `claimed_routes`, `face_up`, `deck_count`,
`dest_deck_count`, `action_log`, `phase`, `current_player_id`, `draw_step`,
`scores`, `winner_id`. Per-player public info (trains, route_score) can be
merged per-player without touching hand/tickets.

```js
// game_state_update handler — CORRECT version:
socket.on('game_state_update', (state) => {
  if (!gameState) return;
  gameState.claimed_routes   = state.claimed_routes;
  gameState.face_up          = state.face_up;
  gameState.deck_count       = state.deck_count;
  gameState.dest_deck_count  = state.dest_deck_count;
  gameState.action_log       = state.action_log;
  gameState.phase            = state.phase;
  gameState.current_player_id = state.current_player_id;
  gameState.draw_step        = state.draw_step;
  gameState.scores           = state.scores;
  gameState.winner_id        = state.winner_id;
  // Merge public-only player fields (trains, score) without touching hand/tickets
  for (const pid of Object.keys(state.players)) {
    if (gameState.players[pid]) {
      gameState.players[pid].trains      = state.players[pid].trains;
      gameState.players[pid].route_score = state.players[pid].route_score;
      gameState.players[pid].card_count  = state.players[pid].card_count;
      gameState.players[pid].ticket_count = state.players[pid].ticket_count;
    }
  }
  renderAll();
});
```

## Board Calibration Pipeline (In Progress)

The user clicked every city dot and every train car slot on the board image.
The data is stored and partially processed. The goal is to produce:
- `city_coords.py` — `CITIES = { "Vancouver": (x, y), ... }` for all 36 cities
- `route_segments.py` — `ROUTE_SEGMENTS = { route_id: [(cx, cy, angle), ...] }`

### Files involved
| File | Purpose | Status |
|------|---------|--------|
| `pick_colors.py` | Tkinter tool — user clicks every car slot per color + all city dots | Done, run by user |
| `color_points.json` | Output of pick_colors.py — raw click coords per color | EXISTS, ready |
| `detect_board.py` | OpenCV script — finds precise bounding rects from clicks | Partially working |
| `templates.json` | Bounding box samples (from earlier draw_templates.py) | EXISTS |
| `color_samples.json` | Single-pixel HSV samples per color (from earlier pick_colors.py version) | EXISTS |
| `city_coords.py` | Target output — city pixel positions | NOT YET CORRECT |
| `route_segments.py` | Target output — per-route segment centers + angles | NOT YET CORRECT |

### Click data counts in color_points.json
```
gray:   93 clicks  (80 gray slots across ~30 gray routes)
yellow: 27 clicks  (22 yellow slots)
blue:   27 clicks
red:    27 clicks
green:  22 clicks  (21 green slots)
orange: 27 clicks
white:  27 clicks
pink:   27 clicks  (routes called "purple" in code = pink visually)
black:  27 clicks
city:   36 clicks  (all 36 city dots, unordered)
```

### detect_board.py current state
- **City matching**: Works — uses raw click positions + Hungarian algorithm against
  `APPROX_CITIES` (approximate positions from game_data.py, Winnipeg corrected to x≈467).
  Produces all 36 cities correctly.
- **Car slot detection**: Uses `find_rect()` per click — samples HSV at click pixel,
  creates local color mask, finds connected component, returns `minAreaRect`.
  Currently produces ~91 gray, 27 each for most colors, 22 green rects.
- **Route assignment**: Groups car rects by proximity to city-city lines (PERP_BAND=26px).
  **Currently has 68 route warnings** — many routes get wrong number of segments.
  Root cause: APPROX_CITIES positions used for route band math are too far off from
  actual city positions. The city_pos from Hungarian matching IS correct, but the
  route assignment code runs AFTER and uses city_pos correctly — so the issue is
  likely the PERP_BAND being too narrow/wide, or clicks being on neighboring route lines.

### What needs to happen next in detect_board.py
1. Run the script and look at the debug image `static/images/board_detected.png`
   to visually diagnose route assignment failures.
2. The main issues are likely:
   a. PERP_BAND too tight — some car slots (especially diagonal routes) fall outside 26px
   b. Gray routes — many gray route bands overlap each other, causing cross-assignment
   c. A few car slot clicks may have been on the wrong color band
3. Suggested fixes:
   - Widen PERP_BAND to 35px
   - For gray routes specifically, use city_pos (from detection) not APPROX_CITIES
     to define bands (the code already does this — make sure city_pos is populated first)
   - After assignment, if a route has more segments than expected, keep only the
     `route.length` closest to the midpoints (discard outliers)
   - If a route has 0 segments, fall back to linear interpolation between the two cities

### After calibration is done
Once `city_coords.py` and `route_segments.py` are correct:
1. Update `game_data.py` `CITIES` dict from `city_coords.py`
2. Change the JS rendering in `static/js/game.js` `buildRouteSegments()` to use
   explicit segment positions from `ROUTE_SEGMENTS` (passed via `BOARD_DATA`) instead
   of interpolating between city positions
3. `BOARD_DATA` is injected in `templates/game.html` from `app.py`'s `game_page()` view
4. Also pass `route_segments` in `board_data` dict in `app.py`

## Key File Map
```
app.py                  — Flask routes + SocketIO events
game_data.py            — CITIES, ROUTES, DESTINATION_TICKETS, scoring constants
game_logic.py           — Full rules engine (draw, claim, tickets, scoring, BFS/DFS)
models.py               — Game + Player DB models (state as JSON text column)
static/js/game.js       — Board SVG rendering, socket handlers, UI
static/css/style.css    — Dark antique theme
templates/game.html     — Injects BOARD_DATA, GAME_CODE, MY_PLAYER_ID, MY_COLOR
templates/lobby.html    — Pre-game lobby
templates/index.html    — Home page (create/join)
static/images/board.png — 1024x683 board image
```

## Todos (Priority Order)
1. **Fix `game_state_update` JS bug** (Bug 2 above) — simple edit to `game.js` lines 45-60
2. **Fix detect_board.py** — widen PERP_BAND, check debug image, get route warnings to 0
3. **Wire calibration output into game** — update CITIES in game_data.py, update JS rendering
   to use ROUTE_SEGMENTS for precise segment positions instead of interpolation

## How the SVG Rendering Works (for context)
`buildRouteSegments(p1, p2, length, side, color)` in game.js takes two city screen
positions, interpolates `length` segment centers along the line, applies a
perpendicular offset of ±4px for double routes (side=0 or 1), and draws rotated
rectangles. Once `route_segments.py` exists, replace this with a lookup:
each segment already has `(cx, cy, angle)` in original board pixel coords, which
get transformed to screen coords via `boardPx(cx, cy)`.

## Environment
- Python 3.14, Windows 11
- pip packages: Flask, Flask-SocketIO, Flask-SQLAlchemy, python-dotenv, opencv-python, scipy, Pillow
- Run: `python app.py` (port 5001)
- `.env` has DATABASE_URL=sqlite:///tickettoride.db, SECRET_KEY, PORT=5001
