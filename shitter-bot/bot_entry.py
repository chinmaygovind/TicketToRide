"""
Integration point for the shitter-bot personality.

bot.py loads this module lazily (by file path) and calls shitter_turn() with the
same signature as the other personality turn-functions in bot.py:_DISPATCH.
The bot is a direct, instant policy — no tree search — so it never lags a turn.
"""
import os
import sys

_HERE   = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
sys.path.insert(0, _PARENT)
sys.path.insert(0, _HERE)

from policy import shitter_policy


def shitter_turn(state, pid, route_by_id, ticket_by_id,
                 hand, trains, draw_step, face_up, claimed):
    """Drop-in turn function for bot.py:_DISPATCH['shitter_bot']."""
    return shitter_policy(state, pid)
