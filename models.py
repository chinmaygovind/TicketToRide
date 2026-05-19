from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    google_id = db.Column(db.String(64), unique=True, nullable=True, index=True)
    phone = db.Column(db.String(20), unique=True, nullable=True)
    notify_new_game = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Stats
    elo = db.Column(db.Integer, default=1000)
    games_played = db.Column(db.Integer, default=0)
    games_won = db.Column(db.Integer, default=0)
    trains_placed = db.Column(db.Integer, default=0)
    tickets_drawn = db.Column(db.Integer, default=0)
    total_points = db.Column(db.Integer, default=0)

    @property
    def elo_tier(self):
        e = self.elo or 1000
        if e >= 1400: return "Rail Baron"
        if e >= 1250: return "Station Master"
        if e >= 1100: return "Engineer"
        if e >= 1000: return "Conductor"
        if e >= 800:  return "Brakeman"
        return "Passenger"

    @property
    def win_rate(self):
        if not self.games_played:
            return 0
        return round(100 * self.games_won / self.games_played)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, pw)


class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default="waiting")  # waiting | playing | ended
    max_players = db.Column(db.Integer, default=6)
    is_private = db.Column(db.Boolean, default=False)
    passcode = db.Column(db.String(20), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity_at = db.Column(db.DateTime, nullable=True)

    # Full serialized game state as JSON text
    state_json = db.Column(db.Text, default="{}")
    replay_json = db.Column(db.Text, default="[]")

    players = db.relationship("Player", backref="game", lazy=True,
                               order_by="Player.turn_order")

    @property
    def state(self):
        return json.loads(self.state_json or "{}")

    @state.setter
    def state(self, value):
        self.state_json = json.dumps(value)

    def to_lobby_dict(self):
        return {
            "code": self.code,
            "status": self.status,
            "max_players": self.max_players,
            "is_private": self.is_private,
            "player_count": len(self.players),
            "players": [p.to_dict() for p in self.players],
        }


class Friendship(db.Model):
    __tablename__ = "friendships"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    friend_id  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status     = db.Column(db.String(10), default="pending")  # pending | accepted
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint("user_id", "friend_id"),)


class GameResult(db.Model):
    __tablename__ = "game_results"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    game_code  = db.Column(db.String(10))
    played_at  = db.Column(db.DateTime, default=datetime.utcnow)
    placement  = db.Column(db.Integer)   # 1 = winner
    score      = db.Column(db.Integer)
    elo_before = db.Column(db.Integer)
    elo_after  = db.Column(db.Integer)
    opponents  = db.Column(db.Text)      # JSON list of {name, elo, placement}


class Player(db.Model):
    __tablename__ = "players"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    session_key = db.Column(db.String(64), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(20), nullable=False)
    turn_order = db.Column(db.Integer, default=0)
    is_host = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    linked_user = db.relationship("User", foreign_keys="Player.user_id", lazy="select")

    def to_dict(self):
        elo = self.linked_user.elo if self.linked_user else None
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "turn_order": self.turn_order,
            "is_host": self.is_host,
            "is_bot": self.session_key.startswith("bot_"),
            "elo": elo,
        }
