import eventlet
eventlet.monkey_patch()

import os
import re
import base64
import random
import string
import smtplib
import uuid
import secrets
import json as json_mod
import urllib.request as urlreq
import urllib.parse as urlparse
from email.mime.text import MIMEText
from functools import wraps
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

import subprocess as _subprocess

def _get_git_version():
    """Return (commit_subject, github_commit_url) or (None, None) if unavailable."""
    try:
        root = os.path.dirname(__file__)
        hash_ = _subprocess.check_output(
            ["git", "log", "-1", "--format=%h"], cwd=root, text=True,
            stderr=_subprocess.DEVNULL).strip()
        subject = _subprocess.check_output(
            ["git", "log", "-1", "--format=%s"], cwd=root, text=True,
            stderr=_subprocess.DEVNULL).strip()
        remote = _subprocess.check_output(
            ["git", "remote", "get-url", "origin"], cwd=root, text=True,
            stderr=_subprocess.DEVNULL).strip()
        if remote.startswith("git@github.com:"):
            remote = "https://github.com/" + remote[len("git@github.com:"):].removesuffix(".git")
        else:
            remote = remote.removesuffix(".git")
        return subject, f"{remote}/commit/{hash_}"
    except Exception:
        return None, None

GIT_VERSION_NAME, GIT_COMMIT_URL = _get_git_version()

from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, session)
from flask_socketio import SocketIO, join_room, leave_room, emit

from models import db, Game, Player, User, GameResult, Friendship
from game_data_na import ROUTES, CITIES, DESTINATION_TICKETS, PLAYER_COLORS, CARD_COLOR_HEX, BOARD_WIDTH, BOARD_HEIGHT
from game_data_europe import (
    EUROPE_ROUTES, EUROPE_CITIES, EUROPE_DESTINATION_TICKETS,
    EUROPE_BOARD_WIDTH, EUROPE_BOARD_HEIGHT,
)
from route_segments import ROUTE_SEGMENTS
from route_segments_europe import EUROPE_ROUTE_SEGMENTS
import game_logic as logic

# ---------------------------------------------------------------------------
# App configuration
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# Inject asset version into all templates for cache-busting
_ASSET_VERSION = GIT_VERSION_NAME or 'dev'

@app.context_processor
def inject_asset_version():
    return {'asset_version': _ASSET_VERSION}

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///tickettoride.db"

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# SMS via Twilio REST (optional — requires TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER)
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")

# Email via SMTP (optional — requires SMTP_HOST, SMTP_USER, SMTP_PASS)
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)

# Public URL used in notification links
SITE_URL = os.environ.get("SITE_URL", "").rstrip("/")

# Google OAuth (optional — requires GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET env vars)
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI")  # set explicitly for production
GOOGLE_ENABLED = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

with app.app_context():
    db.create_all()
    # Add new columns to existing databases without dropping data
    _migration_stmts = [
        "ALTER TABLE games ADD COLUMN is_private BOOLEAN DEFAULT 0",
        "ALTER TABLE games ADD COLUMN passcode VARCHAR(20)",
        "ALTER TABLE games ADD COLUMN last_activity_at DATETIME",
        "ALTER TABLE games ADD COLUMN map_variant VARCHAR(10) DEFAULT 'usa'",
        "ALTER TABLE users ADD COLUMN phone VARCHAR(20)",
        "ALTER TABLE users ADD COLUMN notify_new_game BOOLEAN DEFAULT 0",
        "ALTER TABLE users ADD COLUMN elo INTEGER DEFAULT 1000",
        "ALTER TABLE users ADD COLUMN games_played INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN games_won INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN trains_placed INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN tickets_drawn INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN total_points INTEGER DEFAULT 0",
        "ALTER TABLE players ADD COLUMN user_id INTEGER REFERENCES users(id)",
        "ALTER TABLE games ADD COLUMN replay_json TEXT DEFAULT '[]'",
    ]
    with db.engine.connect() as _conn:
        for _stmt in _migration_stmts:
            try:
                _conn.execute(db.text(_stmt))
                _conn.commit()
            except Exception:
                _conn.rollback()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def get_session_key() -> str:
    if "session_key" not in session:
        session["session_key"] = str(uuid.uuid4())
    return session["session_key"]


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


def get_effective_name() -> str:
    user = get_current_user()
    if user:
        return user.username
    return session.get("guest_name", "Guest")


def require_login(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not get_current_user() and not session.get("guest_name"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


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


def _valid_username(u: str) -> bool:
    return bool(re.match(r'^[A-Za-z][A-Za-z0-9_\-]{1,29}$', u))


# ---------------------------------------------------------------------------
# Notification helpers (SMS + email)
# ---------------------------------------------------------------------------

def _send_sms(to_phone: str, message: str):
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER):
        return
    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json"
    data = urlparse.urlencode({"To": to_phone, "From": TWILIO_FROM_NUMBER, "Body": message}).encode()
    creds = base64.b64encode(f"{TWILIO_ACCOUNT_SID}:{TWILIO_AUTH_TOKEN}".encode()).decode()
    req = urlreq.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Basic {creds}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlreq.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


def _send_email(to_email: str, subject: str, body: str):
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS):
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM or SMTP_USER
    msg["To"] = to_email
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
    except Exception:
        pass


def _send_game_notifications(game_code: str, host_name: str, site_url: str):
    join_url = f"{site_url}/lobby/{game_code}"
    message = f"New TTR Game! Hosted by {host_name}. Join here: {join_url}"
    with app.app_context():
        users = User.query.filter_by(notify_new_game=True).all()
        for user in users:
            if user.phone:
                _send_sms(user.phone, message)
            elif user.email:
                _send_email(user.email, "New Ticket to Ride Game!", message)


# ---------------------------------------------------------------------------
# Google OAuth helpers
# ---------------------------------------------------------------------------

def _google_post(url: str, data: dict) -> dict:
    encoded = urlparse.urlencode(data).encode()
    req = urlreq.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlreq.urlopen(req, timeout=10) as resp:
        return json_mod.loads(resp.read())


def _google_get(url: str, token: str) -> dict:
    req = urlreq.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urlreq.urlopen(req, timeout=10) as resp:
        return json_mod.loads(resp.read())


# ---------------------------------------------------------------------------
# HTTP Routes — Auth
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if get_current_user() or session.get("guest_name"):
        return redirect(url_for("lobbies"))
    return redirect(url_for("login_page"))


@app.route("/login", methods=["GET"])
def login_page():
    if get_current_user() or session.get("guest_name"):
        return redirect(url_for("lobbies"))
    google_setup = bool(request.args.get("google_setup"))
    return render_template("login.html", google_enabled=GOOGLE_ENABLED,
                           google_setup=google_setup)


@app.route("/login", methods=["POST"])
def login():
    data = request.json or {}
    identity = data.get("identity", "").strip()
    password = data.get("password", "")
    if not identity or not password:
        return jsonify({"ok": False, "error": "Please fill in all fields."}), 400

    # Allow login by username, email, or phone
    user = User.query.filter_by(username=identity).first()
    if not user:
        user = User.query.filter_by(email=identity.lower()).first()
    if not user:
        user = User.query.filter_by(phone=identity).first()
    if not user or not user.check_password(password):
        return jsonify({"ok": False, "error": "Invalid username or password."}), 401

    session["user_id"] = user.id
    return jsonify({"ok": True})


@app.route("/register", methods=["POST"])
def register():
    data = request.json or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    phone = data.get("phone", "").strip() or None

    if not username or not email or not password:
        return jsonify({"ok": False, "error": "Please fill in all fields."}), 400
    if not _valid_username(username):
        return jsonify({"ok": False, "error": "Username must be 2-30 characters, start with a letter, and contain only letters, numbers, hyphens, or underscores."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "Password must be at least 8 characters."}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400
    if phone and not re.match(r'^\+?[0-9][0-9\s\-\(\)]{6,18}[0-9]$', phone):
        return jsonify({"ok": False, "error": "Please enter a valid phone number."}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"ok": False, "error": "Username already taken."}), 409
    if User.query.filter_by(email=email).first():
        return jsonify({"ok": False, "error": "An account with that email already exists."}), 409
    if phone and User.query.filter_by(phone=phone).first():
        return jsonify({"ok": False, "error": "An account with that phone number already exists."}), 409

    user = User(username=username, email=email, phone=phone)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session["user_id"] = user.id
    return jsonify({"ok": True})


@app.route("/guest", methods=["POST"])
def guest_login():
    data = request.json or {}
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Please enter a name."}), 400
    if not re.match(r'^[A-Za-z][A-Za-z0-9 _\-]{1,19}$', name):
        return jsonify({"ok": False, "error": "Name must be 2–20 characters, start with a letter, and contain only letters, numbers, spaces, hyphens, or underscores."}), 400
    session.pop("user_id", None)
    session["guest_name"] = name
    return jsonify({"ok": True})


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("guest_name", None)
    return redirect(url_for("login_page"))


@app.route("/settings/notify", methods=["POST"])
def toggle_notify():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    user.notify_new_game = not user.notify_new_game
    db.session.commit()
    return jsonify({"ok": True, "notify": user.notify_new_game})


@app.route("/account")
@require_login
def account_page():
    user = get_current_user()
    if not user:
        return redirect(url_for("login_page"))
    return render_template("account.html", user=user)


@app.route("/account/history")
@require_login
def account_history():
    user = get_current_user()
    if not user:
        return redirect(url_for("login_page"))
    history = GameResult.query.filter_by(user_id=user.id)\
                              .order_by(GameResult.played_at.desc())\
                              .limit(50).all()
    for h in history:
        h.opponents_parsed = json_mod.loads(h.opponents or "[]")
    return render_template("account_history.html", user=user, history=history)


@app.route("/account/update", methods=["POST"])
@require_login
def account_update():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    data = request.json or {}
    field = data.get("field", "")

    if field == "username":
        new_val = data.get("value", "").strip()
        if not _valid_username(new_val):
            return jsonify({"ok": False, "error": "Username must be 2-30 characters, start with a letter, letters/numbers/hyphens/underscores only."}), 400
        existing = User.query.filter_by(username=new_val).first()
        if existing and existing.id != user.id:
            return jsonify({"ok": False, "error": "Username already taken."}), 409
        user.username = new_val

    elif field == "email":
        new_val = data.get("value", "").strip().lower()
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', new_val):
            return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400
        existing = User.query.filter_by(email=new_val).first()
        if existing and existing.id != user.id:
            return jsonify({"ok": False, "error": "Email already in use."}), 409
        user.email = new_val

    elif field == "phone":
        new_val = data.get("value", "").strip() or None
        if new_val and not re.match(r'^\+?[0-9][0-9\s\-\(\)]{6,18}[0-9]$', new_val):
            return jsonify({"ok": False, "error": "Please enter a valid phone number."}), 400
        if new_val:
            existing = User.query.filter_by(phone=new_val).first()
            if existing and existing.id != user.id:
                return jsonify({"ok": False, "error": "Phone number already in use."}), 409
        user.phone = new_val

    elif field == "password":
        current_pw = data.get("current_password", "")
        new_pw = data.get("value", "")
        if user.password_hash and not user.check_password(current_pw):
            return jsonify({"ok": False, "error": "Current password is incorrect."}), 401
        if len(new_pw) < 8:
            return jsonify({"ok": False, "error": "New password must be at least 8 characters."}), 400
        user.set_password(new_pw)

    else:
        return jsonify({"ok": False, "error": "Unknown field."}), 400

    db.session.commit()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# HTTP Routes — Google OAuth
# ---------------------------------------------------------------------------

@app.route("/auth/google")
def google_auth():
    if not GOOGLE_ENABLED:
        return redirect(url_for("login_page"))
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    redirect_uri = GOOGLE_REDIRECT_URI or url_for("google_callback", _external=True)
    params = urlparse.urlencode({
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    })
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@app.route("/auth/google/callback")
def google_callback():
    if not GOOGLE_ENABLED:
        return redirect(url_for("login_page"))

    state = request.args.get("state")
    if state != session.pop("oauth_state", None):
        return redirect(url_for("login_page"))
    if request.args.get("error"):
        return redirect(url_for("login_page"))

    code = request.args.get("code")
    redirect_uri = GOOGLE_REDIRECT_URI or url_for("google_callback", _external=True)

    try:
        token_data = _google_post("https://oauth2.googleapis.com/token", {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        access_token = token_data.get("access_token")
        if not access_token:
            return redirect(url_for("login_page"))

        user_info = _google_get(
            "https://www.googleapis.com/oauth2/v3/userinfo", access_token)
    except Exception:
        return redirect(url_for("login_page"))

    google_id = user_info.get("sub")
    email = user_info.get("email", "").lower()
    given_name = user_info.get("given_name", "")
    if not google_id:
        return redirect(url_for("login_page"))

    user = User.query.filter_by(google_id=google_id).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_id = google_id
            db.session.commit()
        else:
            # New Google user — pick a username
            session["pending_google"] = {
                "google_id": google_id,
                "email": email,
                "name": given_name,
            }
            return redirect(url_for("login_page", google_setup=1))

    session["user_id"] = user.id
    return redirect(url_for("lobbies"))


@app.route("/auth/google/setup", methods=["POST"])
def google_setup():
    pending = session.get("pending_google")
    if not pending:
        return jsonify({"ok": False, "error": "No pending Google login."}), 400

    data = request.json or {}
    username = data.get("username", "").strip()
    if not _valid_username(username):
        return jsonify({"ok": False, "error": "Username must be 2-30 characters, start with a letter, and contain only letters, numbers, hyphens, or underscores."}), 400
    if User.query.filter_by(username=username).first():
        return jsonify({"ok": False, "error": "Username already taken."}), 409

    user = User(username=username, email=pending["email"],
                google_id=pending["google_id"])
    db.session.add(user)
    db.session.commit()

    session.pop("pending_google", None)
    session["user_id"] = user.id
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# HTTP Routes — Lobbies & Game
# ---------------------------------------------------------------------------

@app.route("/api/friends")
@require_login
def api_friends():
    user = get_current_user()
    if not user:
        return jsonify([])
    accepted = Friendship.query.filter_by(user_id=user.id, status="accepted").all()
    result = []
    for f in accepted:
        friend = db.session.get(User, f.friend_id)
        if friend:
            result.append({
                "id": friend.id,
                "username": friend.username,
                "online": friend.id in _online_users,
                "elo": friend.elo or 1000,
            })
    return jsonify(result)


@app.route("/api/friend-requests")
@require_login
def api_friend_requests():
    user = get_current_user()
    if not user:
        return jsonify([])
    pending = Friendship.query.filter_by(friend_id=user.id, status="pending").all()
    result = []
    for f in pending:
        sender = db.session.get(User, f.user_id)
        if sender:
            result.append({"id": f.id, "username": sender.username, "elo": sender.elo or 1000})
    return jsonify(result)


@app.route("/friends/request", methods=["POST"])
@require_login
def friend_request():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    data = request.json or {}
    username = data.get("username", "").strip()
    target = User.query.filter_by(username=username).first()
    if not target:
        return jsonify({"ok": False, "error": "User not found."}), 404
    if target.id == user.id:
        return jsonify({"ok": False, "error": "Cannot friend yourself."}), 400
    existing = Friendship.query.filter_by(user_id=user.id, friend_id=target.id).first()
    if existing:
        return jsonify({"ok": False, "error": "Request already sent or already friends."}), 409
    # Check reverse (they sent us a request already — auto-accept)
    reverse = Friendship.query.filter_by(user_id=target.id, friend_id=user.id).first()
    if reverse and reverse.status == "pending":
        reverse.status = "accepted"
        db.session.add(Friendship(user_id=user.id, friend_id=target.id, status="accepted"))
        db.session.commit()
        return jsonify({"ok": True, "accepted": True})
    db.session.add(Friendship(user_id=user.id, friend_id=target.id))
    db.session.commit()
    return jsonify({"ok": True, "accepted": False})


@app.route("/friends/accept", methods=["POST"])
@require_login
def friend_accept():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    data = request.json or {}
    req_id = data.get("request_id")
    f = Friendship.query.filter_by(id=req_id, friend_id=user.id, status="pending").first()
    if not f:
        return jsonify({"ok": False, "error": "Request not found."}), 404
    f.status = "accepted"
    # Add reverse row so both sides see each other
    reverse = Friendship.query.filter_by(user_id=user.id, friend_id=f.user_id).first()
    if not reverse:
        db.session.add(Friendship(user_id=user.id, friend_id=f.user_id, status="accepted"))
    else:
        reverse.status = "accepted"
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/friends/decline", methods=["POST"])
@require_login
def friend_decline():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    data = request.json or {}
    req_id = data.get("request_id")
    f = Friendship.query.filter_by(id=req_id, friend_id=user.id, status="pending").first()
    if f:
        db.session.delete(f)
        db.session.commit()
    return jsonify({"ok": True})


@app.route("/friends/remove", methods=["POST"])
@require_login
def friend_remove():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not logged in."}), 401
    data = request.json or {}
    friend_id = data.get("friend_id")
    for f in Friendship.query.filter(
        ((Friendship.user_id == user.id) & (Friendship.friend_id == friend_id)) |
        ((Friendship.user_id == friend_id) & (Friendship.friend_id == user.id))
    ).all():
        db.session.delete(f)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/replay/<code>")
@require_login
def replay_page(code):
    from flask import abort
    game = Game.query.filter_by(code=code.upper()).first_or_404()
    if game.status != "ended":
        abort(404)
    try:
        replay_data = json_mod.loads(game.replay_json or "[]")
    except Exception:
        replay_data = []
    _map = game.map_variant or "usa"
    if _map == "europe":
        _bd = {"map": "europe", "cities": {k: list(v) for k, v in EUROPE_CITIES.items()},
               "routes": EUROPE_ROUTES, "route_segments": EUROPE_ROUTE_SEGMENTS,
               "card_colors": CARD_COLOR_HEX,
               "board_w": EUROPE_BOARD_WIDTH, "board_h": EUROPE_BOARD_HEIGHT}
    else:
        _bd = {"map": "usa", "cities": {k: list(v) for k, v in CITIES.items()},
               "routes": ROUTES, "route_segments": ROUTE_SEGMENTS,
               "card_colors": CARD_COLOR_HEX,
               "board_w": BOARD_WIDTH, "board_h": BOARD_HEIGHT}
    players_info = {str(p.id): {"name": p.name, "color": p.color} for p in game.players}
    return render_template("replay.html", game=game, replay_data=replay_data,
                           board_data=_bd, players_info=players_info,
                           user=get_current_user())


@app.route("/leaderboard")
@require_login
def leaderboard():
    top = User.query.filter(User.games_played > 0)\
                    .order_by(User.elo.desc())\
                    .limit(100).all()
    current_user = get_current_user()
    return render_template("leaderboard.html", players=top, user=current_user)


@app.route("/admin")
def admin_page():
    user = get_current_user()
    if not user or user.username != "chinmay":
        return redirect(url_for("login_page"))
    return render_template("admin.html", user=user)


@app.route("/admin/table/<table_name>")
def admin_table(table_name):
    user = get_current_user()
    if not user or user.username != "chinmay":
        return ("Forbidden", 403)
    table_map = {
        "users": User,
        "games": Game,
        "players": Player,
        "game_results": GameResult,
        "friendships": Friendship,
    }
    model = table_map.get(table_name)
    if not model:
        return ("Not found", 404)
    page = request.args.get("page", 1, type=int)
    per_page = 50
    q = model.query.order_by(model.id.desc())
    total = q.count()
    rows = q.offset((page - 1) * per_page).limit(per_page).all()
    cols = [c.name for c in model.__table__.columns]
    data = [[getattr(r, c) for c in cols] for r in rows]
    return jsonify({
        "table": table_name,
        "columns": cols,
        "rows": data,
        "total": total,
        "page": page,
        "per_page": per_page,
    })


@app.route("/admin/edit/<table_name>/<int:row_id>", methods=["POST"])
def admin_edit(table_name, row_id):
    user = get_current_user()
    if not user or user.username != "chinmay":
        return ("Forbidden", 403)
    table_map = {
        "users": User,
        "games": Game,
        "players": Player,
        "game_results": GameResult,
        "friendships": Friendship,
    }
    model = table_map.get(table_name)
    if not model:
        return jsonify({"error": "Not found"}), 404
    row = model.query.get(row_id)
    if not row:
        return jsonify({"error": "Row not found"}), 404
    payload = request.get_json(force=True)
    cols = {c.name for c in model.__table__.columns}
    for key, val in payload.items():
        if key in cols and key != "id":
            setattr(row, key, val)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/admin/delete/<table_name>/<int:row_id>", methods=["POST"])
def admin_delete(table_name, row_id):
    user = get_current_user()
    if not user or user.username != "chinmay":
        return ("Forbidden", 403)
    table_map = {
        "users": User,
        "games": Game,
        "players": Player,
        "game_results": GameResult,
        "friendships": Friendship,
    }
    model = table_map.get(table_name)
    if not model:
        return jsonify({"error": "Not found"}), 404
    row = model.query.get(row_id)
    if not row:
        return jsonify({"error": "Row not found"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/lobbies")
@require_login
def lobbies():
    user = get_current_user()
    guest_name = session.get("guest_name") if not user else None
    public_games = (Game.query
                    .filter_by(status="waiting", is_private=False)
                    .order_by(Game.created_at.desc())
                    .all())
    ongoing_games = (Game.query
                     .filter_by(status="playing", is_private=False)
                     .order_by(Game.created_at.desc())
                     .all())
    notify = user.notify_new_game if user else False
    return render_template("lobbies.html", user=user, guest_name=guest_name,
                           games=public_games, ongoing_games=ongoing_games,
                           notify_new_game=notify)


@app.route("/create", methods=["POST"])
@require_login
def create_game():
    player_name = get_effective_name()
    data = request.json or {}
    max_players = int(data.get("max_players", 6))
    is_private = bool(data.get("is_private", False))
    passcode = data.get("passcode", "").strip() if is_private else None
    map_variant = data.get("map_variant", "usa")
    if map_variant not in ("usa", "europe"):
        map_variant = "usa"

    sk = get_session_key()
    code = _make_game_code()

    game = Game(code=code, max_players=max(2, min(6, max_players)),
                is_private=is_private, passcode=passcode or None,
                map_variant=map_variant)
    db.session.add(game)
    db.session.flush()

    user = get_current_user()
    color = PLAYER_COLORS[0]
    player = Player(
        game_id=game.id,
        user_id=user.id if user else None,
        session_key=sk,
        name=player_name,
        color=color,
        turn_order=0,
        is_host=True,
    )
    db.session.add(player)
    db.session.commit()

    site_url = SITE_URL or request.host_url.rstrip("/")
    eventlet.spawn(_send_game_notifications, code, player_name, site_url)

    return jsonify({"ok": True, "code": code})


@app.route("/join", methods=["POST"])
@require_login
def join_game_http():
    player_name = get_effective_name()
    data = request.json or {}
    code = data.get("code", "").strip().upper()
    passcode = data.get("passcode", "").strip()

    if not code:
        return jsonify({"ok": False, "error": "Game code required."}), 400

    game = Game.query.filter_by(code=code).first()
    if not game:
        return jsonify({"ok": False, "error": "Game not found."}), 404
    if game.status != "waiting":
        return jsonify({"ok": False, "error": "Game already started."}), 400
    if game.is_private and game.passcode and game.passcode != passcode:
        return jsonify({"ok": False, "error": "Incorrect passcode."}), 403

    sk = get_session_key()

    existing = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if existing:
        return jsonify({"ok": True, "code": code})

    if len(game.players) >= game.max_players:
        return jsonify({"ok": False, "error": "Game is full."}), 400

    used_colors = {p.color for p in game.players}
    available = [c for c in PLAYER_COLORS if c not in used_colors]
    if not available:
        return jsonify({"ok": False, "error": "No colors available."}), 400

    join_user = get_current_user()
    player = Player(
        game_id=game.id,
        user_id=join_user.id if join_user else None,
        session_key=sk,
        name=player_name,
        color=available[0],
        turn_order=len(game.players),
        is_host=False,
    )
    db.session.add(player)
    db.session.commit()

    socketio.emit("player_joined", game.to_lobby_dict(), to=code)
    return jsonify({"ok": True, "code": code})


@app.route("/lobby/<code>")
@require_login
def lobby(code):
    game = Game.query.filter_by(code=code.upper()).first_or_404()
    player = get_player_for_game(code)
    if not player:
        return redirect(url_for("lobbies"))
    if game.status == "playing":
        return redirect(url_for("game_page", code=code.upper()))
    return render_template("lobby.html", game=game, player=player)


@app.route("/game/<code>")
@require_login
def game_page(code):
    user = get_current_user()
    game = Game.query.filter_by(code=code.upper()).first_or_404()
    player = get_player_for_game(code)
    is_spectator = player is None
    if game.status == "waiting":
        if player:
            return redirect(url_for("lobby", code=code.upper()))
        else:
            return redirect(url_for("lobbies"))

    map_variant = game.map_variant or "usa"
    if map_variant == "europe":
        board_data = {
            "map": "europe",
            "cities": {k: list(v) for k, v in EUROPE_CITIES.items()},
            "routes": EUROPE_ROUTES,
            "route_segments": EUROPE_ROUTE_SEGMENTS,
            "card_colors": CARD_COLOR_HEX,
            "board_w": EUROPE_BOARD_WIDTH,
            "board_h": EUROPE_BOARD_HEIGHT,
            "tickets": EUROPE_DESTINATION_TICKETS,
        }
    else:
        board_data = {
            "map": "usa",
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
    guest_name = session.get("guest_name") if not user else None
    return render_template("game.html", game=game, player=player,
                           board_data=board_data, music_files=music_files,
                           is_spectator=is_spectator, user=user, guest_name=guest_name,
                           git_version_name=GIT_VERSION_NAME, git_commit_url=GIT_COMMIT_URL,
                           map_variant=map_variant)


# ---------------------------------------------------------------------------
# Socket.IO Events
# ---------------------------------------------------------------------------

_chat_history: dict[str, list] = {}  # game_code -> [{name, msg, ts}, …] max 100
_online_users: dict[int, str] = {}   # user_id -> socket_sid


@socketio.on("connect")
def on_connect():
    user = get_current_user()
    if user:
        _online_users[user.id] = request.sid


@socketio.on("disconnect")
def on_disconnect():
    user = get_current_user()
    if user:
        _online_users.pop(user.id, None)


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

    players_list = list(game.players)
    random.shuffle(players_list)
    for i, p in enumerate(players_list):
        p.turn_order = i
    game.status = "playing"
    game.last_activity_at = datetime.utcnow()

    players_data = [{"id": p.id, "name": p.name, "color": p.color, "turn_order": p.turn_order}
                    for p in players_list]
    state = logic.init_game_state(players_data, map_variant=game.map_variant or "usa")
    game.state = state
    db.session.commit()

    socketio.emit("game_started", {"code": code}, to=code)
    _run_bots(game, code)


@socketio.on("join_game_room")
def on_join_game_room(data):
    code = data.get("code", "").upper()
    sk = get_session_key()
    game = Game.query.filter_by(code=code).first()
    if not game:
        return
    player = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    join_room(code)
    state = game.state
    bot_ids = [str(p.id) for p in game.players if p.session_key.startswith("bot_")]
    host_id = next((str(p.id) for p in game.players if p.is_host), None)
    if player:
        pub = logic.get_public_state(state, str(player.id))
        pub["my_player_id"] = str(player.id)
        pub["my_color"] = player.color
        pub["is_host"] = player.is_host
        pub["host_player_id"] = host_id
        pub["bot_player_ids"] = bot_ids
        emit("game_state", pub)
    else:
        pub = logic.get_public_state(state, "")
        pub["is_spectator"] = True
        pub["host_player_id"] = host_id
        pub["bot_player_ids"] = bot_ids
        emit("game_state", pub)
        spectator_name = data.get("spectator_name", "").strip()
        if spectator_name:
            socketio.emit("spectator_joined", {"name": spectator_name}, to=code)

    emit("chat_history", _chat_history.get(code, []))


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


@socketio.on("kick_player")
def on_kick_player(data):
    code = data.get("code", "").upper()
    target_id = data.get("player_id")
    sk = get_session_key()

    game = Game.query.filter_by(code=code).first()
    if not game:
        return

    host = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if not host or not host.is_host:
        emit("error", {"message": "Only the host can kick players."})
        return

    target = Player.query.filter_by(game_id=game.id, id=target_id).first()
    if not target or target.is_host:
        return

    # Notify all clients before state changes so kicked player can redirect
    socketio.emit("player_kicked", {"player_id": target_id}, to=code)

    if game.status == "waiting":
        db.session.delete(target)
        db.session.commit()
        socketio.emit("player_joined", game.to_lobby_dict(), to=code)
    else:
        # Convert to bot so turns auto-play; real player will be redirected by event
        target.session_key = f"bot_kicked_{uuid.uuid4()}"
        db.session.commit()
        _run_bots(game, code)


@socketio.on("rematch")
def on_rematch(data):
    code = data.get("code", "").upper()
    game = Game.query.filter_by(code=code).first()
    if not game or game.status != "ended":
        return emit("error", {"message": "Game not ended."})
    sid_key = get_session_key()
    player = Player.query.filter_by(game_id=game.id, session_key=sid_key).first()
    if not player or not player.is_host:
        return emit("error", {"message": "Only the host can rematch."})

    new_code = _make_game_code()
    new_game = Game(code=new_code, status="waiting", max_players=game.max_players,
                    is_private=game.is_private, passcode=game.passcode,
                    map_variant=game.map_variant or "usa")
    db.session.add(new_game)
    db.session.flush()

    old_players = list(game.players)
    colors = [p.color for p in old_players]
    random.shuffle(colors)
    for i, old_p in enumerate(old_players):
        new_p = Player(
            game_id=new_game.id,
            name=old_p.name,
            color=colors[i],
            session_key=old_p.session_key,
            is_host=(old_p.id == player.id),
            user_id=old_p.user_id,
            turn_order=i,
        )
        db.session.add(new_p)
    db.session.commit()
    socketio.emit("rematch_created", {"new_code": new_code}, to=code)


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


@socketio.on("resolve_tunnel")
def on_resolve_tunnel(data):
    code = data.get("code", "").upper()
    proceed = bool(data.get("proceed", False))
    extra_cards = data.get("extra_cards", {})
    _player_action(code, lambda state, pid: logic.resolve_tunnel(state, pid, proceed, extra_cards))


@socketio.on("place_station")
def on_place_station(data):
    code = data.get("code", "").upper()
    city = data.get("city", "")
    cards = data.get("cards", {})
    _player_action(code, lambda state, pid: logic.place_station(state, pid, city, cards))


@socketio.on("send_chat")
def on_send_chat(data):
    code = data.get("code", "").upper()
    msg = data.get("msg", "").strip()
    if not msg or len(msg) > 200:
        return
    game = Game.query.filter_by(code=code).first()
    if not game:
        return
    sk = get_session_key()
    player = Player.query.filter_by(game_id=game.id, session_key=sk).first()
    if player:
        sender_name = player.name
    else:
        sender_name = (data.get("spectator_name") or "").strip() or "Spectator"
    chat_msg = {"name": sender_name, "msg": msg}
    history = _chat_history.setdefault(code, [])
    history.append(chat_msg)
    if len(history) > 100:
        del history[0]
    socketio.emit("chat_message", chat_msg, to=code)


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

    # Record slim replay snapshot
    import time as _time
    snap = {
        "t": int(_time.time()),
        "routes": dict(state.get("claimed_routes", {})),
        "scores": {pid: pdata.get("route_score", 0)
                   for pid, pdata in state["player_states"].items()},
        "face_up": state.get("face_up", []),
        "action": state.get("action_log", [""])[-1] if state.get("action_log") else "",
    }
    try:
        replay = json_mod.loads(game.replay_json or "[]")
        replay.append(snap)
        game.replay_json = json_mod.dumps(replay[-500:])
    except Exception:
        pass

    db.session.commit()
    _broadcast_state(game, code)
    _run_bots(game, code)


def _finalize_game_stats(game: Game, state: dict):
    """Called once when game phase transitions to ended. Updates per-user stats and ELO."""
    game.status = "ended"

    scores = state.get("scores", {})
    winner_id = state.get("winner_id")
    if not scores:
        db.session.commit()
        return

    # Map player-state pid -> Player record
    pid_to_player = {str(p.id): p for p in game.players}

    # Gather real (non-bot) players who have a linked user account
    pid_to_user: dict[str, User] = {}
    for pid, p in pid_to_player.items():
        if p.user_id and not p.session_key.startswith("bot_"):
            u = db.session.get(User, p.user_id)
            if u:
                pid_to_user[pid] = u

    if not pid_to_user:
        db.session.commit()
        return

    # Build ranking (0 = best) from scores for ELO
    ranked_pids = sorted(scores.keys(), key=lambda pid: scores[pid]["total"], reverse=True)
    rank_of = {pid: i for i, pid in enumerate(ranked_pids)}

    # Compute ELO deltas (pairwise, then averaged)
    elo_deltas: dict[str, int] = {}
    real_pids = [pid for pid in ranked_pids if pid in pid_to_user]
    for pid in real_pids:
        user = pid_to_user[pid]
        K = 32 if (user.games_played or 0) < 10 else 16
        my_elo = user.elo or 1000
        my_rank = rank_of[pid]
        delta = 0.0
        opponents = [opid for opid in real_pids if opid != pid]
        for opid in opponents:
            opp_elo = pid_to_user[opid].elo or 1000
            expected = 1 / (1 + 10 ** ((opp_elo - my_elo) / 400))
            opp_rank = rank_of[opid]
            actual = 1.0 if my_rank < opp_rank else (0.5 if my_rank == opp_rank else 0.0)
            delta += K * (actual - expected)
        if opponents:
            delta /= len(opponents)
        elo_deltas[pid] = round(delta)

    # Apply stats updates and record match history
    for pid, user in pid_to_user.items():
        if pid not in scores:
            continue
        ps = state["player_states"].get(pid, {})
        sc = scores[pid]
        elo_before = user.elo or 1000
        user.games_played = (user.games_played or 0) + 1
        if pid == winner_id:
            user.games_won = (user.games_won or 0) + 1
        user.trains_placed = (user.trains_placed or 0) + max(0, 45 - ps.get("trains", 45))
        user.tickets_drawn = (user.tickets_drawn or 0) + len(ps.get("tickets", []))
        user.total_points  = (user.total_points or 0) + max(0, sc.get("total", 0))
        user.elo = max(100, elo_before + elo_deltas.get(pid, 0))

        # Record per-game result
        placement = ranked_pids.index(pid) + 1
        opponent_list = [
            {"name": pid_to_user[opid].username if opid in pid_to_user else pid_to_player[opid].name,
             "elo": scores[opid].get("total", 0),
             "placement": ranked_pids.index(opid) + 1}
            for opid in ranked_pids if opid != pid
        ]
        db.session.add(GameResult(
            user_id    = user.id,
            game_code  = game.code,
            placement  = placement,
            score      = sc.get("total", 0),
            elo_before = elo_before,
            elo_after  = user.elo,
            opponents  = json_mod.dumps(opponent_list),
        ))

    db.session.commit()


def _broadcast_state(game: Game, code: str):
    game.last_activity_at = datetime.utcnow()
    db.session.commit()
    state = game.state

    # Finalize stats exactly once when the game first ends
    if state.get("phase") == "ended" and game.status == "playing":
        _finalize_game_stats(game, state)
    bot_ids = [str(p.id) for p in game.players if p.session_key.startswith("bot_")]
    host_id = next((str(p.id) for p in game.players if p.is_host), None)
    for p in game.players:
        if p.session_key.startswith("bot_"):
            continue
        pub = logic.get_public_state(state, str(p.id))
        pub["my_player_id"] = str(p.id)
        pub["my_color"] = p.color
        pub["is_host"] = p.is_host
        pub["host_player_id"] = host_id
        pub["bot_player_ids"] = bot_ids
        socketio.emit("game_state", pub, to=p.session_key)

    generic = logic.get_public_state(state, "")
    generic["host_player_id"] = host_id
    generic["bot_player_ids"] = bot_ids
    socketio.emit("game_state_update", generic, to=code)


def _run_bots(game: Game, code: str):
    for _ in range(100):
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
                # If a tunnel is pending for this bot, abort it (bots don't pay extra)
                if state.get("pending_tunnel") and state["pending_tunnel"].get("player_id") == cur_pid:
                    logic.resolve_tunnel(state, cur_pid, proceed=False)
                else:
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
    sk = get_session_key()
    join_room(sk)


@socketio.on("get_all_tickets")
def on_get_all_tickets(data=None):
    code = (data or {}).get("code", "").upper()
    game = Game.query.filter_by(code=code).first() if code else None
    if game and (game.map_variant or "usa") == "europe":
        emit("all_tickets", EUROPE_DESTINATION_TICKETS)
    else:
        emit("all_tickets", DESTINATION_TICKETS)


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Background: end games inactive for >20 minutes
# ---------------------------------------------------------------------------

def _stale_game_cleanup():
    PLAYING_LIMIT = timedelta(minutes=20)
    WAITING_LIMIT = timedelta(hours=2)

    def _run_cleanup():
        with app.app_context():
            now = datetime.utcnow()

            # End playing games inactive for >20 minutes
            playing_cutoff = now - PLAYING_LIMIT
            stale_playing = Game.query.filter(
                Game.status == "playing",
                db.or_(
                    Game.last_activity_at == None,   # noqa: E711
                    Game.last_activity_at < playing_cutoff,
                ),
            ).all()
            for game in stale_playing:
                game.status = "ended"
                db.session.commit()
                socketio.emit("game_over", {
                    "reason": "Game ended due to inactivity.",
                    "scores": {},
                }, to=game.code)

            # Delete waiting lobbies older than 2 hours
            waiting_cutoff = now - WAITING_LIMIT
            stale_waiting = Game.query.filter(
                Game.status == "waiting",
                Game.created_at < waiting_cutoff,
            ).all()
            for game in stale_waiting:
                socketio.emit("lobby_closed", {
                    "reason": "Lobby expired.",
                }, to=game.code)
                for player in game.players:
                    db.session.delete(player)
                db.session.delete(game)
            if stale_waiting:
                db.session.commit()

    _run_cleanup()  # immediate pass on startup
    while True:
        eventlet.sleep(5 * 60)  # then every 5 minutes
        _run_cleanup()

eventlet.spawn(_stale_game_cleanup)


# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_ENV") == "development"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug, use_reloader=False, log_output=True)
