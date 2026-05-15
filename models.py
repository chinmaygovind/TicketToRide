from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()


class Game(db.Model):
    __tablename__ = "games"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default="waiting")  # waiting | playing | ended
    max_players = db.Column(db.Integer, default=5)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Full serialized game state as JSON text (avoids requiring JSONB dialect)
    state_json = db.Column(db.Text, default="{}")

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
            "player_count": len(self.players),
            "players": [p.to_dict() for p in self.players],
        }


class Player(db.Model):
    __tablename__ = "players"

    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    session_key = db.Column(db.String(64), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(20), nullable=False)
    turn_order = db.Column(db.Integer, default=0)
    is_host = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "turn_order": self.turn_order,
            "is_host": self.is_host,
        }
