"""
Unit tests for the shitter-bot policy (shitter-bot/policy.py).

The module lives in a hyphenated folder that isn't importable as a normal
package, so we load it by file path exactly like bot.py:_load_shitter_agent does.
These pin the tempo/endgame-awareness logic (_claim_threshold) and the
card-draw targeting (_draw_toward) so future tuning can't silently regress them.
"""

import importlib.util
import os

import pytest

import game_logic as logic
from bot import bot_turn


def _load_policy():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(here, "shitter-bot", "policy.py")
    spec = importlib.util.spec_from_file_location("shitter_policy_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


policy = _load_policy()


# ---------------------------------------------------------------------------
# _claim_threshold — tempo + endgame awareness
# ---------------------------------------------------------------------------

def test_claim_threshold_always_advances_ticket_path():
    # While owing tickets, ANY affordable route on the plan should clear the bar.
    assert policy._claim_threshold(owing=True, trains=45, opp_min_trains=45) == 0.0
    assert policy._claim_threshold(owing=True, trains=3, opp_min_trains=45) == 0.0


def test_claim_threshold_early_game_is_picky():
    # Plenty of our trains, opponents comfortable -> hold out for a good route.
    assert (policy._claim_threshold(owing=False, trains=45, opp_min_trains=45)
            == policy._TEMPO_HI_THRESH)


def test_claim_threshold_drops_when_our_trains_dwindle():
    # Our own endgame: lower the bar so we actually spend our trains.
    assert (policy._claim_threshold(owing=False,
                                    trains=policy._TEMPO_MID_TRAINS,
                                    opp_min_trains=45)
            == policy._TEMPO_MID_THRESH)


def test_claim_threshold_reacts_to_opponent_endgame():
    # The key fix vs fast humans: even with a full stockpile of our own trains,
    # an opponent nearly out of trains means the game is about to end -> grab
    # affordable routes now instead of hoarding.
    hi = policy._claim_threshold(owing=False, trains=45, opp_min_trains=45)
    reacting = policy._claim_threshold(owing=False, trains=45,
                                       opp_min_trains=policy._ENDGAME_OPP_TRAINS)
    assert reacting == policy._TEMPO_MID_THRESH
    assert reacting < hi


# ---------------------------------------------------------------------------
# _draw_toward — target the colour the focus routes need MOST
# ---------------------------------------------------------------------------

def _first_route_of_color(color):
    for rid, r in policy.ROUTE_BY_ID.items():
        if r.get("color") == color:
            return rid, r
    return None, None


def test_draw_toward_grabs_face_up_locomotive_first():
    face_up = ["red", "locomotive", "blue", "green", "red"]
    action, params = policy._draw_toward(face_up, set(), draw_step=0)
    assert action == "draw_face_up"
    assert face_up[params["slot"]] == "locomotive"


def test_draw_toward_picks_most_needed_color():
    # Two focus routes: pick colours that are both present face-up, then assert we
    # take the one whose colour the (length-weighted) plan needs more of.
    long_rid, long_r = None, None
    short_rid, short_r = None, None
    for _val, rid, r in policy.ROUTES_BY_VALUE:
        c = r.get("color")
        if c in ("gray", "locomotive") or not c:
            continue
        if long_r is None and r["length"] >= 5:
            long_rid, long_r = rid, r
        elif short_r is None and r["length"] <= 2 and c != (long_r or {}).get("color"):
            short_rid, short_r = rid, r
        if long_r and short_r:
            break
    assert long_r and short_r, "expected both a long and a short coloured route"

    focus = {long_rid, short_rid}
    face_up = [short_r["color"], "white" if long_r["color"] != "white" else "black",
               long_r["color"], "black", "yellow"]
    action, params = policy._draw_toward(face_up, focus, draw_step=1)
    assert action == "draw_face_up"
    assert face_up[params["slot"]] == long_r["color"]


def test_draw_toward_falls_back_to_blind_when_nothing_matches():
    rid, r = _first_route_of_color("red")
    assert r is not None
    # Focus needs red, but no red is face up and no locomotive -> draw blind.
    face_up = ["blue", "green", "white", "black", "yellow"]
    action, _ = policy._draw_toward(face_up, {rid}, draw_step=1)
    assert action == "draw_blind"


# ---------------------------------------------------------------------------
# End-to-end: shitter_bot still produces legal actions through bot_turn
# ---------------------------------------------------------------------------

def test_shitter_bot_turn_is_legal_from_fresh_main_state():
    specs = [
        {"id": 1, "name": "A", "color": "red",  "turn_order": 0},
        {"id": 2, "name": "B", "color": "blue", "turn_order": 1},
    ]
    state = logic.init_game_state(specs, "usa")
    for pid in ("1", "2"):
        ps = state["player_states"][pid]
        if ps.get("pending_tickets"):
            logic.keep_initial_tickets(state, pid, ps["pending_tickets"][:2])
    action, params = bot_turn(state, "1", "shitter_bot")
    assert action in ("claim", "draw_face_up", "draw_blind", "draw_tickets")
