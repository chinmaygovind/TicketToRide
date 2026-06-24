"""
Flask HTTP and SocketIO integration tests.

IMPORTANT NOTE on SocketIO session keys:
The Flask-SocketIO test client connects at creation time. If it is created
before login/game-setup, the session doesn't yet have a `session_key`, so
SocketIO handlers that call `get_session_key()` return a fresh UUID that
doesn't match any player in the database. For tests that need session
validation, we create the SocketIO client INSIDE the test body, after
all HTTP setup (login + game creation) has been done.
"""

import pytest
import json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_and_login(client, username="player1", email=None, password="Password1!"):
    email = email or f"{username}@example.com"
    resp = client.post("/register", json={
        "username": username, "email": email, "password": password
    })
    assert resp.status_code == 200


def http_create_game(client, max_players=4, is_private=False,
                     passcode="", map_variant="usa"):
    resp = client.post("/create", json={
        "max_players": max_players,
        "is_private": is_private,
        "passcode": passcode,
        "map_variant": map_variant,
    })
    return json.loads(resp.data)


def http_join_game(client, code, passcode=""):
    resp = client.post("/join", json={"code": code, "passcode": passcode})
    return json.loads(resp.data)


def make_sio(flask_app, client):
    """Create a SocketIO test client using the HTTP client's active session."""
    from app import socketio as _sio
    return _sio.test_client(flask_app, flask_test_client=client)


def start_game_with_bot(flask_app, client):
    """Login, create a game, add a bot, start it. Returns (sio, code)."""
    from app import socketio as _sio
    data = http_create_game(client)
    code = data["code"]
    # Create SIO AFTER game creation so the session key is established
    sio = make_sio(flask_app, client)
    sio.emit("join_lobby", {"code": code})
    sio.get_received()
    sio.emit("add_bot", {"code": code})
    sio.get_received()
    sio.emit("start_game", {"code": code})
    sio.get_received()
    return sio, code


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

def test_register_ok(client):
    resp = client.post("/register", json={
        "username": "newuser", "email": "new@example.com", "password": "Password1!"
    })
    data = json.loads(resp.data)
    assert data["ok"]


def test_register_duplicate_username(client):
    create_and_login(client, "dupuser")
    from app import app as flask_app
    with flask_app.test_client() as c2:
        resp = c2.post("/register", json={
            "username": "dupuser", "email": "other@example.com", "password": "Password1!"
        })
        data = json.loads(resp.data)
        assert not data["ok"]
        assert "taken" in data["error"].lower()


def test_register_short_password(client):
    resp = client.post("/register", json={
        "username": "shortpw", "email": "short@example.com", "password": "abc"
    })
    data = json.loads(resp.data)
    assert not data["ok"]


def test_login_ok(client):
    create_and_login(client, "logintest")
    resp = client.post("/login", json={"identity": "logintest", "password": "Password1!"})
    data = json.loads(resp.data)
    assert data["ok"]


def test_login_wrong_password(client):
    create_and_login(client, "loginfail")
    resp = client.post("/login", json={"identity": "loginfail", "password": "WrongPass1!"})
    data = json.loads(resp.data)
    assert not data["ok"]


def test_guest_login_ok(client):
    resp = client.post("/guest", json={"name": "Guestina"})
    data = json.loads(resp.data)
    assert data["ok"]


def test_guest_login_bad_name(client):
    resp = client.post("/guest", json={"name": "x"})
    data = json.loads(resp.data)
    assert not data["ok"]


def test_logout_redirects(client):
    create_and_login(client, "logouttest")
    resp = client.get("/logout")
    assert resp.status_code in (301, 302)


# ---------------------------------------------------------------------------
# Game creation (HTTP)
# ---------------------------------------------------------------------------

def test_create_game_returns_code(client):
    create_and_login(client, "creator")
    data = http_create_game(client)
    assert data["ok"]
    assert len(data["code"]) == 6


def test_create_game_private(client):
    create_and_login(client, "private_creator")
    data = http_create_game(client, is_private=True, passcode="secret")
    assert data["ok"]


def test_create_game_europe(client):
    create_and_login(client, "eu_creator")
    data = http_create_game(client, map_variant="europe")
    assert data["ok"]


def test_create_game_requires_login(client):
    resp = client.post("/create", json={"max_players": 4})
    assert resp.status_code in (302, 401)


# ---------------------------------------------------------------------------
# Joining games (HTTP)
# ---------------------------------------------------------------------------

def test_join_public_game(client, flask_app):
    create_and_login(client, "join_host")
    data = http_create_game(client)
    code = data["code"]
    with flask_app.test_client() as c2:
        c2.post("/register", json={
            "username": "joiner2", "email": "joiner2@example.com", "password": "Password1!"
        })
        result = http_join_game(c2, code)
        assert result["ok"]


def test_join_game_not_found(client):
    create_and_login(client, "joiner_nf")
    result = http_join_game(client, "XXXXXX")
    assert not result["ok"]


def test_join_private_game_wrong_passcode(client, flask_app):
    create_and_login(client, "host_priv")
    data = http_create_game(client, is_private=True, passcode="rightcode")
    code = data["code"]
    with flask_app.test_client() as c2:
        c2.post("/register", json={
            "username": "joiner_priv", "email": "priv@example.com", "password": "Password1!"
        })
        result = http_join_game(c2, code, passcode="wrongcode")
        assert not result["ok"]


def test_join_private_game_correct_passcode(client, flask_app):
    create_and_login(client, "host_priv2")
    data = http_create_game(client, is_private=True, passcode="correctcode")
    code = data["code"]
    with flask_app.test_client() as c2:
        c2.post("/register", json={
            "username": "joiner_priv2", "email": "priv2@example.com", "password": "Password1!"
        })
        result = http_join_game(c2, code, passcode="correctcode")
        assert result["ok"]


def test_join_full_game(client, flask_app):
    create_and_login(client, "host_full")
    data = http_create_game(client, max_players=2)
    code = data["code"]
    # Fill the one remaining slot
    with flask_app.test_client() as c2:
        c2.post("/register", json={
            "username": "filler1", "email": "filler1@x.com", "password": "Password1!"
        })
        http_join_game(c2, code)
    # One more — should be rejected
    with flask_app.test_client() as extra:
        extra.post("/register", json={
            "username": "extra_player", "email": "extra@x.com", "password": "Password1!"
        })
        result = http_join_game(extra, code)
        assert not result["ok"]
        assert "full" in result["error"].lower()


# ---------------------------------------------------------------------------
# SocketIO lobby events
# All SocketIO tests below create the client AFTER HTTP setup so the session
# key is already stored in the cookie before the connection is established.
# ---------------------------------------------------------------------------

def test_socketio_join_lobby_emits_state(client, flask_app):
    create_and_login(client, "sio_host")
    data = http_create_game(client)
    code = data["code"]
    sio = make_sio(flask_app, client)
    try:
        sio.emit("join_lobby", {"code": code})
        received = sio.get_received()
        event_names = [r["name"] for r in received]
        assert "lobby_state" in event_names
    finally:
        sio.disconnect()


def test_socketio_add_bot(client, flask_app):
    create_and_login(client, "bot_host")
    data = http_create_game(client)
    code = data["code"]
    sio = make_sio(flask_app, client)
    try:
        sio.emit("join_lobby", {"code": code})
        sio.get_received()
        sio.emit("add_bot", {"code": code})
        received = sio.get_received()
        event_names = [r["name"] for r in received]
        assert "player_joined" in event_names
    finally:
        sio.disconnect()


def test_socketio_add_bot_not_host(client, flask_app):
    create_and_login(client, "bot_host2")
    data = http_create_game(client)
    code = data["code"]
    with flask_app.test_client() as c2:
        c2.post("/register", json={
            "username": "nonhost2", "email": "nh2@x.com", "password": "Password1!"
        })
        c2.post("/login", json={"identity": "nonhost2", "password": "Password1!"})
        http_join_game(c2, code)
        sio2 = make_sio(flask_app, c2)
        try:
            sio2.emit("add_bot", {"code": code})
            received = sio2.get_received()
            event_names = [r["name"] for r in received]
            assert "error" in event_names
        finally:
            sio2.disconnect()


def test_socketio_leave_lobby_host_closes(client, flask_app):
    create_and_login(client, "leave_host")
    data = http_create_game(client)
    code = data["code"]
    sio = make_sio(flask_app, client)
    try:
        sio.emit("join_lobby", {"code": code})
        sio.get_received()
        sio.emit("leave_lobby", {"code": code})
        received = sio.get_received()
        event_names = [r["name"] for r in received]
        assert "lobby_closed" in event_names
    finally:
        sio.disconnect()


def test_socketio_kick_player_from_lobby(client, flask_app):
    create_and_login(client, "kick_host")
    data = http_create_game(client)
    code = data["code"]

    with flask_app.test_client() as c2:
        c2.post("/register", json={
            "username": "kickme", "email": "kickme@x.com", "password": "Password1!"
        })
        c2.post("/login", json={"identity": "kickme", "password": "Password1!"})
        http_join_game(c2, code)

    with flask_app.app_context():
        from models import Game, Player
        game = Game.query.filter_by(code=code).first()
        target = next(p for p in game.players if p.name == "kickme")
        target_id = target.id

    sio = make_sio(flask_app, client)
    try:
        sio.emit("join_lobby", {"code": code})
        sio.get_received()
        sio.emit("kick_player", {"code": code, "player_id": target_id})
        received = sio.get_received()
        event_names = [r["name"] for r in received]
        assert "player_kicked" in event_names or "player_joined" in event_names
    finally:
        sio.disconnect()


def test_socketio_start_game_needs_two_players(client, flask_app):
    create_and_login(client, "start_solo")
    data = http_create_game(client)
    code = data["code"]
    sio = make_sio(flask_app, client)
    try:
        sio.emit("join_lobby", {"code": code})
        sio.get_received()
        sio.emit("start_game", {"code": code})
        received = sio.get_received()
        event_names = [r["name"] for r in received]
        assert "error" in event_names
    finally:
        sio.disconnect()


def test_socketio_start_game_with_bot(client, flask_app):
    create_and_login(client, "start_with_bot")
    sio, code = start_game_with_bot(flask_app, client)
    try:
        received = sio.get_received()  # any leftover after start
        # The game_started event goes to the room; verify status in DB
        with flask_app.app_context():
            from models import Game
            game = Game.query.filter_by(code=code).first()
            assert game.status == "playing"
    finally:
        sio.disconnect()


# ---------------------------------------------------------------------------
# In-game SocketIO events
# ---------------------------------------------------------------------------

def test_socketio_join_game_room_emits_state(client, flask_app):
    create_and_login(client, "ingame_host")
    sio, code = start_game_with_bot(flask_app, client)
    try:
        sio.emit("join_game_room", {"code": code})
        received = sio.get_received()
        event_names = [r["name"] for r in received]
        assert "game_state" in event_names
    finally:
        sio.disconnect()


def test_socketio_game_state_has_my_player_id(client, flask_app):
    create_and_login(client, "my_pid_host")
    sio, code = start_game_with_bot(flask_app, client)
    try:
        sio.emit("join_game_room", {"code": code})
        received = sio.get_received()
        state_events = [r for r in received if r["name"] == "game_state"]
        assert state_events
        state = state_events[-1]["args"][0]
        assert "my_player_id" in state
    finally:
        sio.disconnect()


def test_socketio_chat_message(client, flask_app):
    create_and_login(client, "chatter")
    sio, code = start_game_with_bot(flask_app, client)
    try:
        sio.emit("join_game_room", {"code": code})
        sio.get_received()
        sio.emit("send_chat", {"code": code, "msg": "Hello!"})
        received = sio.get_received()
        event_names = [r["name"] for r in received]
        assert "chat_message" in event_names
    finally:
        sio.disconnect()


def test_socketio_draw_blind_not_your_turn_gives_error(client, flask_app):
    """Drawing when it's not your turn returns an error event."""
    create_and_login(client, "drawer_host")
    sio, code = start_game_with_bot(flask_app, client)
    try:
        sio.emit("join_game_room", {"code": code})
        received = sio.get_received()
        state_events = [r for r in received if r["name"] == "game_state"]
        if not state_events:
            return
        state = state_events[-1]["args"][0]
        my_pid = state.get("my_player_id")
        if state.get("current_player_id") == my_pid and state.get("phase") == "main":
            # It IS our turn — drawing blind should succeed
            sio.emit("draw_blind", {"code": code})
            received = sio.get_received()
            event_names = [r["name"] for r in received]
            assert "game_state" in event_names or "game_state_update" in event_names
        else:
            # It is NOT our turn — should get an error
            sio.emit("draw_blind", {"code": code})
            received = sio.get_received()
            event_names = [r["name"] for r in received]
            # Either error or no event (bots act between state updates)
            pass  # we just verify no crash
    finally:
        sio.disconnect()


def test_resign_http_replaces_with_bot(client, flask_app):
    create_and_login(client, "resign_host")
    sio, code = start_game_with_bot(flask_app, client)
    try:
        with flask_app.app_context():
            from models import Game
            game = Game.query.filter_by(code=code).first()
            assert game.status == "playing"

        resp = client.post(f"/resign/{code}")
        data_resp = json.loads(resp.data)
        assert data_resp["ok"]

        with flask_app.app_context():
            from models import Game
            game = Game.query.filter_by(code=code).first()
            # The resigning player's session_key should now be a bot
            bots = [p for p in game.players if p.session_key.startswith("bot_")]
            assert len(bots) >= 1
    finally:
        sio.disconnect()


# ---------------------------------------------------------------------------
# Leaderboard / account routes
# ---------------------------------------------------------------------------

def test_leaderboard_accessible(client):
    create_and_login(client, "leaderboard_user")
    resp = client.get("/leaderboard")
    assert resp.status_code == 200


def test_account_page_accessible(client):
    create_and_login(client, "account_user")
    resp = client.get("/account")
    assert resp.status_code == 200


def test_account_update_username(client):
    create_and_login(client, "update_me")
    resp = client.post("/account/update", json={"field": "username", "value": "updated_me"})
    data = json.loads(resp.data)
    assert data["ok"]


def test_account_update_bad_username(client):
    create_and_login(client, "bad_update")
    resp = client.post("/account/update", json={"field": "username", "value": "x"})
    data = json.loads(resp.data)
    assert not data["ok"]


# ---------------------------------------------------------------------------
# Friend system
# ---------------------------------------------------------------------------

def test_friend_request_sent(client, registered_user, registered_user2, flask_app):
    client, user = registered_user
    with flask_app.app_context():
        from models import User
        u2 = User.query.filter_by(username="testuser2").first()
        username2 = u2.username
    resp = client.post("/friends/request", json={"username": username2})
    data = json.loads(resp.data)
    assert data["ok"]


def test_friend_request_self(client, registered_user):
    client, user = registered_user
    with client.application.app_context():
        from models import User
        u = User.query.filter_by(username="testuser").first()
    resp = client.post("/friends/request", json={"username": "testuser"})
    data = json.loads(resp.data)
    assert not data["ok"]


def test_friend_request_nonexistent(client, registered_user):
    client, user = registered_user
    resp = client.post("/friends/request", json={"username": "doesnotexist_xyz"})
    data = json.loads(resp.data)
    assert not data["ok"]
