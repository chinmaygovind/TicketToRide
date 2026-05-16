import eventlet
eventlet.monkey_patch()

import os
import random
import string
import uuid
from dotenv import load_dotenv

load_dotenv()

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session)
from flask_socketio import SocketIO, join_room, leave_room, emit

from models import db, Game, Player
from game_data import ROUTES, CITIES, DESTINATION_TICKETS, TICKET_BY_ID, PLAYER_COLORS, CARD_COLOR_HEX, BOARD_WIDTH, BOARD_HEIGHT
from route_segments import ROUTE_SEGMENTS
import game_logic as logic

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    # Fallback to SQLite for development without a PostgreSQL instance
    DATABASE_URL = "sqlite:///tickettoride.db"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

with app.app_context():
    db.create_all()


# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

def get_session_key() -> str:
    if "session_key" not in session:
        session["session_key"] = str(uuid.uuid4())
    return session["session_key"]


def _make_game_code() -> str:
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if not Game.query.filter_by(code=code).first():
            return code


def get_player_for_game(game_code: str) -> Player | None:
    sk = get_session_key()
    game = Game.query.filter_by(code=game_code).first()
    if not game:
        return None
    return Player.query.filter_by(game_id=game.id, session_key=sk).first()


# ---------------------------------------------------------------------------
# HTTP Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/create", methods=["POST"])
def create_game():
    name = request.json.get("name", "").strip()
    max_players = int(request.json.get("max_players", 6))
    if not name:
        return jsonify({"ok": False, "error": "Name required."}), 400

    sk = get_session_key()
    code = _make_game_code()

    game = Game(code=code, max_players=max(2, min(6, max_players)))
    db.session.add(game)
    db.session.flush()

    color = PLAYER_COLORS[0]
    player = Player(
        game_id=game.id,
        session_key=sk,
        name=name,
        color=color,
        turn_order=0,
        is_host=True,
    )
    db.session.add(player)
    db.session.commit()

    return jsonify({"ok": True, "code": code})


@app.route("/join", methods=["POST"])
def join_game_http():
    name = request.json.get("name", "").strip()
    code = request.json.get("code", "").strip().upper()
    if not name or not code:
        return jsonify({"ok": False, "error": "Name and code required."}), 400

    game = Game.query.filter_by(code=code).first()
    if not game:
        return jsonify({"ok": False, "error": "Game not found."}), 404
    if game.status != "waiting":
        return jsonify({"ok": False, "error": "Game already started."}), 400

    sk = get_session_key()

    # Already in game?
    existing = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if existing:
        return jsonify({"ok": True, "code": code})

    if len(game.players) >= game.max_players:
        return jsonify({"ok": False, "error": "Game is full."}), 400

    used_colors = {p.color for p in game.players}
    available = [c for c in PLAYER_COLORS if c not in used_colors]
    if not available:
        return jsonify({"ok": False, "error": "No colors available."}), 400

    player = Player(
        game_id=game.id,
        session_key=sk,
        name=name,
        color=available[0],
        turn_order=len(game.players),
        is_host=False,
    )
    db.session.add(player)
    db.session.commit()

    socketio.emit("player_joined", game.to_lobby_dict(), to=code)
    return jsonify({"ok": True, "code": code})


@app.route("/lobby/<code>")
def lobby(code):
    game = Game.query.filter_by(code=code.upper()).first_or_404()
    player = get_player_for_game(code)
    if not player:
        return redirect(url_for("index", join=code.upper()))
    if game.status == "playing":
        return redirect(url_for("game_page", code=code.upper()))
    return render_template("lobby.html", game=game, player=player)


@app.route("/game/<code>")
def game_page(code):
    game = Game.query.filter_by(code=code.upper()).first_or_404()
    player = get_player_for_game(code)
    is_spectator = player is None
    if game.status == "waiting":
        if player:
            return redirect(url_for("lobby", code=code.upper()))
        else:
            return redirect(url_for("index", join=code.upper()))

    board_data = {
        "cities": {k: list(v) for k, v in CITIES.items()},
        "routes": ROUTES,
        "route_segments": ROUTE_SEGMENTS,
        "card_colors": CARD_COLOR_HEX,
        "board_w": BOARD_WIDTH,
        "board_h": BOARD_HEIGHT,
        "tickets": DESTINATION_TICKETS,
    }
    music_dir = os.path.join(app.static_folder, "music")
    music_files = sorted(
        f for f in os.listdir(music_dir) if f.lower().endswith(".mp3")
    ) if os.path.isdir(music_dir) else []
    return render_template("game.html", game=game, player=player,
                           board_data=board_data, music_files=music_files,
                           is_spectator=is_spectator)


# ---------------------------------------------------------------------------
# Socket.IO Events
# ---------------------------------------------------------------------------

@socketio.on("connect")
def on_connect():
    pass


@socketio.on("join_lobby")
def on_join_lobby(data):
    code = data.get("code", "").upper()
    game = Game.query.filter_by(code=code).first()
    if not game:
        return
    join_room(code)
    emit("lobby_state", game.to_lobby_dict())


@socketio.on("start_game")
def on_start_game(data):
    code = data.get("code", "").upper()
    sk = get_session_key()
    game = Game.query.filter_by(code=code).first()
    if not game:
        return
    player = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if not player or not player.is_host:
        emit("error", {"message": "Only the host can start the game."})
        return
    if len(game.players) < 2:
        emit("error", {"message": "Need at least 2 players."})
        return
    if game.status != "waiting":
        return

    # Assign random turn order
    players_list = list(game.players)
    random.shuffle(players_list)
    for i, p in enumerate(players_list):
        p.turn_order = i
    game.status = "playing"

    players_data = [{"id": p.id, "name": p.name, "color": p.color, "turn_order": p.turn_order}
                    for p in players_list]
    state = logic.init_game_state(players_data)
    game.state = state
    db.session.commit()

    socketio.emit("game_started", {"code": code}, to=code)
    _run_bots(game, code)


@socketio.on("join_game_room")
def on_join_game_room(data):
    code = data.get("code", "").upper()
    spectator_name = data.get("spectator_name", "").strip()
    sk = get_session_key()
    game = Game.query.filter_by(code=code).first()
    if not game:
        return
    player = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    join_room(code)
    state = game.state
    if player:
        pub = logic.get_public_state(state, str(player.id))
        pub["my_player_id"] = str(player.id)
        pub["my_color"] = player.color
        emit("game_state", pub)
    else:
        pub = logic.get_public_state(state, "")
        pub["is_spectator"] = True
        emit("game_state", pub)
        if spectator_name:
            socketio.emit("spectator_joined", {"name": spectator_name}, to=code)


@socketio.on("add_bot")
def on_add_bot(data):
    code = data.get("code", "").upper()
    sk = get_session_key()
    game = Game.query.filter_by(code=code).first()
    if not game or game.status != "waiting":
        emit("error", {"message": "Cannot add bot now."})
        return
    player = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if not player or not player.is_host:
        emit("error", {"message": "Only the host can add bots."})
        return
    if len(game.players) >= game.max_players:
        emit("error", {"message": "Game is full."})
        return

    bot_count = sum(1 for p in game.players if p.session_key.startswith("bot_"))
    used_colors = {p.color for p in game.players}
    available = [c for c in PLAYER_COLORS if c not in used_colors]
    if not available:
        emit("error", {"message": "No colors available."})
        return

    bot = Player(
        game_id=game.id,
        session_key=f"bot_{uuid.uuid4()}",
        name=f"Bot {bot_count + 1}",
        color=available[0],
        turn_order=len(game.players),
        is_host=False,
    )
    db.session.add(bot)
    db.session.commit()
    socketio.emit("player_joined", game.to_lobby_dict(), to=code)


@socketio.on("keep_initial_tickets")
def on_keep_initial_tickets(data):
    code = data.get("code", "").upper()
    keep_ids = data.get("keep_ids", [])
    sk = get_session_key()
    game = Game.query.filter_by(code=code).first()
    if not game:
        return
    player = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if not player:
        return

    state = game.state
    result = logic.keep_initial_tickets(state, str(player.id), keep_ids)
    if not result["ok"]:
        emit("error", {"message": result["error"]})
        return

    game.state = state
    db.session.commit()
    _broadcast_state(game, code)
    _run_bots(game, code)


@socketio.on("draw_face_up")
def on_draw_face_up(data):
    code = data.get("code", "").upper()
    slot = int(data.get("slot", 0))
    _player_action(code, lambda state, pid: logic.draw_face_up(state, pid, slot))


@socketio.on("draw_blind")
def on_draw_blind(data):
    code = data.get("code", "").upper()
    _player_action(code, lambda state, pid: logic.draw_blind(state, pid))


@socketio.on("claim_route")
def on_claim_route(data):
    code = data.get("code", "").upper()
    route_id = int(data.get("route_id", 0))
    cards = data.get("cards", {})
    _player_action(code, lambda state, pid: logic.claim_route(state, pid, route_id, cards))


@socketio.on("draw_destination_tickets")
def on_draw_destination_tickets(data):
    code = data.get("code", "").upper()
    _player_action(code, lambda state, pid: logic.draw_destination_tickets(state, pid))


@socketio.on("keep_drawn_tickets")
def on_keep_drawn_tickets(data):
    code = data.get("code", "").upper()
    keep_ids = data.get("keep_ids", [])
    _player_action(code, lambda state, pid: logic.keep_drawn_tickets(state, pid, keep_ids))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _player_action(code: str, action_fn):
    sk = get_session_key()
    game = Game.query.filter_by(code=code).first()
    if not game:
        emit("error", {"message": "Game not found."})
        return
    player = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if not player:
        emit("error", {"message": "You are not in this game."})
        return

    state = game.state
    result = action_fn(state, str(player.id))
    if not result["ok"]:
        emit("error", {"message": result.get("error", "Action failed.")})
        return

    game.state = state
    db.session.commit()
    _broadcast_state(game, code)
    _run_bots(game, code)


def _broadcast_state(game: Game, code: str):
    """Send each player their personalized view of the game state."""
    state = game.state
    for p in game.players:
        if p.session_key.startswith("bot_"):
            continue  # bots have no socket connection
        pub = logic.get_public_state(state, str(p.id))
        pub["my_player_id"] = str(p.id)
        pub["my_color"] = p.color
        socketio.emit("game_state", pub, to=p.session_key)

    # Also send a generic update to the room (for non-personal data like claimed routes)
    generic = logic.get_public_state(state, "")
    socketio.emit("game_state_update", generic, to=code)


def _run_bots(game: Game, code: str):
    """Auto-play any bot turns until the current player is human."""
    for _ in range(100):  # safety cap
        state = game.state
        phase = state.get("phase")

        if phase == "initial_tickets":
            acted = False
            for p in game.players:
                if not p.session_key.startswith("bot_"):
                    continue
                pid = str(p.id)
                ps = state["player_states"].get(pid, {})
                pending = ps.get("pending_tickets", [])
                if pending:
                    logic.keep_initial_tickets(state, pid, pending)
                    game.state = state
                    db.session.commit()
                    acted = True
                    break
            if not acted:
                break

        elif phase in ("main", "final_round"):
            cur_pid = state["current_player_id"]
            cur_player = next((p for p in game.players if str(p.id) == cur_pid), None)
            if cur_player and cur_player.session_key.startswith("bot_"):
                for _ in range(2):
                    result = logic.draw_blind(state, cur_pid)
                    if not result["ok"]:
                        break
                game.state = state
                db.session.commit()
            else:
                break
        else:
            break

    _broadcast_state(game, code)


@socketio.on("register_session")
def on_register_session(data=None):
    """Allow client to register its session key as a Socket.IO room for personal messages."""
    sk = get_session_key()
    join_room(sk)


@socketio.on("get_all_tickets")
def on_get_all_tickets():
    emit("all_tickets", DESTINATION_TICKETS)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_ENV") == "development"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, use_reloader=False, log_output=True)
