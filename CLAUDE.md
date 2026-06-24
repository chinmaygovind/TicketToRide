# Ticket to Ride — Claude Code Instructions

## Project Overview

Full multiplayer online Ticket to Ride (North America map). Flask + Flask-SocketIO backend, vanilla JS + SVG frontend, SQLite/PostgreSQL database.

**Run locally:** `python app.py` → http://localhost:5001  
**Production:** http://52.54.184.133 (EC2, `aws-deploy` branch)

## Architecture

### Key Files
```
app.py              — Flask routes, all SocketIO event handlers, _run_bots()
game_logic.py       — Full rules engine: draw, claim, tickets, scoring, BFS longest-path
game_data_na.py     — 36 cities, 99 routes, 30 destination tickets (North America)
game_data_europe.py — Europe map data
models.py           — Game + Player SQLAlchemy models; state stored as JSON text column
bot.py              — All bot personalities + bot_turn() / bot_keep_initial_tickets()
route_segments.py   — Per-route segment (cx, cy, angle) for SVG rendering
static/js/game.js   — Client-side: SVG rendering, socket handlers, modals, UI
templates/          — Jinja2 HTML templates (game.html, lobby.html, index.html)
deploy/             — EC2 setup, nginx config, systemd unit
```

### Game State Shape
All state lives in `Game.state_json`. `game_logic.py` mutates it in place; `app.py` saves back to DB.
```python
{
  "deck": [...],
  "face_up": [...],           # 5 face-up cards (None = empty slot)
  "dest_deck": [...],
  "claimed_routes": {},       # {route_id_str: player_id_str}
  "player_states": {
    "pid": {
      "hand": {"red": 2, ...},
      "tickets": [1, 4, ...], # kept destination ticket IDs
      "pending_tickets": [],  # drawn but not yet kept
      "trains": 45,
      "route_score": 0,
    }
  },
  "current_player_id": "...",
  "phase": "initial_tickets | main | final_round | ended",
  "draw_step": 0,             # 0 = fresh turn, 1 = first card drawn
  "turn_order": [...],
  "action_log": [...],
}
```

### Bot System (`bot.py`)
`bot_turn(state, pid, personality)` is the public API called by `app.py`.  
`bot_keep_initial_tickets(state, pid, pending, personality)` handles initial ticket selection.  
Personalities: `fish_bot`, `chin_bot`, `rocket_bot`, `ticket_bot`, `chaos_bot`, `claude_bot`.  
`claude_bot` loads weights from `claude-bot/model/claude_bot_weights.json` if it exists.

### Socket Events
After every action `_broadcast_state(game, code)` sends:
1. `game_state` → player's personal room (includes hand, tickets)
2. `game_state_update` → game-code room (public data: claimed_routes, face_up, scores)

### Double-Route Rules
In ≤3 player games, only ONE side of a double route can be claimed by anyone.  
Enforced in `game_logic.claim_route`. Bot code must respect this.

---

## claude-bot ML Subproject

All machine-learning code for training the `claude_bot` lives in `claude-bot/`.  
See `claude-bot/README.md` for architecture and usage.

The bot integration point in `bot.py` is `_claude_turn()` — it calls the trained model  
(or falls back to weight-based scoring if no model is loaded).

To retrain: `cd claude-bot && python train.py`  
Output model/weights land in `claude-bot/model/` and are loaded at bot runtime.

---

## Development Notes

- **Python 3.14, Windows 11** dev machine; production is Ubuntu 22.04
- `main` branch: `async_mode="threading"`, run with `python app.py`
- `aws-deploy` branch: eventlet + gunicorn + nginx
- SQLite on EC2 — data lives on instance disk, lost if instance is terminated
- Single gunicorn worker required (socket rooms in-process); don't increase without Redis
- No HTTPS on EC2 currently
