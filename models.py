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
    is_bot = db.Column(db.Boolean, default=False, index=True)  # synthetic account for a bot personality
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ------------------------------------------------------------------
    # Per-game stats live in their own tables now (ttr_stats here, ers_stats
    # in the Egyptian Rat Screw app) so one account is shared across games.
    # These numbers used to be plain columns on `users`; the physical columns
    # are left in place (dormant) as a backup, but are no longer mapped. The
    # properties below proxy TTR stats to the `ttr_stats` row so every existing
    # call site (user.elo, user.games_played = ..., templates) keeps working.
    # ------------------------------------------------------------------

    def _ensure_stats(self):
        if self.stats is None:
            self.stats = TtrStats()
        return self.stats

    @property
    def elo(self):
        return self.stats.elo if self.stats else None

    @elo.setter
    def elo(self, value):
        self._ensure_stats().elo = value

    @property
    def games_played(self):
        return self.stats.games_played if self.stats else None

    @games_played.setter
    def games_played(self, value):
        self._ensure_stats().games_played = value

    @property
    def games_won(self):
        return self.stats.games_won if self.stats else None

    @games_won.setter
    def games_won(self, value):
        self._ensure_stats().games_won = value

    @property
    def trains_placed(self):
        return self.stats.trains_placed if self.stats else None

    @trains_placed.setter
    def trains_placed(self, value):
        self._ensure_stats().trains_placed = value

    @property
    def tickets_drawn(self):
        return self.stats.tickets_drawn if self.stats else None

    @tickets_drawn.setter
    def tickets_drawn(self, value):
        self._ensure_stats().tickets_drawn = value

    @property
    def total_points(self):
        return self.stats.total_points if self.stats else None

    @total_points.setter
    def total_points(self, value):
        self._ensure_stats().total_points = value

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
        gp = self.games_played or 0
        if not gp:
            return 0
        return round(100 * (self.games_won or 0) / gp)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, pw)


class TtrStats(db.Model):
    """Ticket to Ride stats, one row per user. Split out of `users` so the
    account (users) can be shared with the Egyptian Rat Screw app while each
    game keeps its own stats."""
    __tablename__ = "ttr_stats"

    user_id       = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    elo           = db.Column(db.Integer, default=1000)
    games_played  = db.Column(db.Integer, default=0)
    games_won     = db.Column(db.Integer, default=0)
    trains_placed = db.Column(db.Integer, default=0)
    tickets_drawn = db.Column(db.Integer, default=0)
    total_points  = db.Column(db.Integer, default=0)

    user = db.relationship("User", backref=db.backref("stats", uselist=False,
                                                       cascade="all, delete-orphan"))


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

    # "usa" (default) or "europe"
    map_variant = db.Column(db.String(10), default="usa", nullable=False)

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
            "map_variant": self.map_variant or "usa",
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
