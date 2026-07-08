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
from bot import bot_turn, bot_keep_initial_tickets


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


# ---------------------------------------------------------------------------
# shittér-bot (shitter_bot_2) — the sabotaging rival
# ---------------------------------------------------------------------------

_COLORS = ["red", "blue", "green", "yellow", "black", "white", "orange", "pink"]


def _state_with(names, map_variant="usa"):
    """Init a game with players named `names`, advanced to the main phase."""
    specs = [{"id": i + 1, "name": n, "color": _COLORS[i], "turn_order": i}
             for i, n in enumerate(names)]
    state = logic.init_game_state(specs, map_variant)
    for i in range(len(names)):
        pid = str(i + 1)
        ps = state["player_states"][pid]
        if ps.get("pending_tickets"):
            logic.keep_initial_tickets(state, pid, ps["pending_tickets"][:2])
    return state


def test_find_target_matches_fishy_by_name():
    state = _state_with(["shittér-bot", "fishy", "chinmay"])
    assert policy._find_target(state, "1") == "2"


def test_find_target_none_when_no_target_present():
    state = _state_with(["alice", "bob"])
    assert policy._find_target(state, "1") is None


def test_v2_is_identical_to_shitter_when_no_target():
    # With nobody to sabotage, shittér-bot must be a byte-for-byte shitter-bot.
    state = _state_with(["alice", "bob"])
    assert policy.shitter_policy_v2(state, "1") == policy.shitter_policy(state, "1")


def test_extract_personality_prefers_longer_slug():
    import bot
    assert bot._extract_personality("bot_shitter_bot_2_xyz") == "shitter_bot_2"
    assert bot._extract_personality("bot_shitter_bot_xyz") == "shitter_bot"


def test_snipe_grabs_targets_most_wanted_face_up_color():
    state = _state_with(["shittér-bot", "fishy"])
    state["claimed_routes"] = {}
    state["player_states"]["2"]["hand"] = {}          # no held-card discount
    # Find a ticket that makes fishy clearly hunt one colour (pathing is
    # deterministic given the map, so this is stable).
    chosen, wanted = None, None
    for tid in policy.TICKET_BY_ID:
        state["player_states"]["2"]["tickets"] = [tid]
        w = policy._target_wanted_colors(state, "2")
        if w and max(w.values()) >= 2.0:
            chosen, wanted = tid, w
            break
    assert chosen is not None
    top = max(wanted, key=wanted.get)
    others = [c for c in _COLORS if c != top][:4]
    face_up = [top] + others
    action, params = policy._snipe_target_color(state, "2", face_up)
    assert action == "draw_face_up"
    assert face_up[params["slot"]] == top


def test_snipe_returns_none_when_target_needs_nothing_face_up():
    state = _state_with(["shittér-bot", "fishy"])
    state["claimed_routes"] = {}
    state["player_states"]["2"]["tickets"] = []        # target owes nothing
    assert policy._snipe_target_color(state, "2", ["red", "blue", "green", "white", "black"]) is None


def test_best_target_block_hits_a_route_on_the_targets_path():
    state = _state_with(["shittér-bot", "fishy"])
    state["claimed_routes"] = {}
    state["player_states"]["1"]["tickets"] = []        # we owe nothing -> free to block
    state["player_states"]["1"]["hand"] = {c: 6 for c in _COLORS}
    state["player_states"]["1"]["hand"]["locomotive"] = 6
    state["player_states"]["1"]["trains"] = 45
    # Give fishy a high-value ticket so the block clears _BLOCK_MIN.
    chosen, needed = None, None
    for tid, t in policy.TICKET_BY_ID.items():
        if t.get("points", 0) < 10:
            continue
        state["player_states"]["2"]["tickets"] = [tid]
        paths = policy._target_incomplete_paths(state, "2")
        if paths and paths[0][1]:
            chosen = tid
            needed = {r for _pts, need in paths for r in need}
            break
    assert chosen is not None
    block = policy._best_target_block(
        state, "1", "2", state["player_states"]["1"]["hand"],
        45, len(state["turn_order"]), state["claimed_routes"])
    assert block is not None
    assert block["route_id"] in needed


def test_v2_snipes_fishy_color_where_base_would_draw_blind():
    # Set up a spot where plain shitter-bot has nothing to do but draw blind
    # (no cards, no network, no owed tickets), while fishy is clearly hunting a
    # colour that's sitting face-up. shitter-bot draws blind; shittér-bot instead
    # snipes fishy's colour — proving the sabotage actually changes the move.
    state = _state_with(["shittér-bot", "fishy"])
    state["claimed_routes"] = {}
    state["draw_step"] = 0
    state["player_states"]["1"]["tickets"] = []        # not owing
    state["player_states"]["1"]["hand"] = {}           # can't afford / block anything
    state["player_states"]["2"]["hand"] = {}
    chosen, wanted = None, None
    for tid in policy.TICKET_BY_ID:
        state["player_states"]["2"]["tickets"] = [tid]
        w = policy._target_wanted_colors(state, "2")
        if w and max(w.values()) >= 2.0:
            chosen, wanted = tid, w
            break
    assert chosen is not None
    top = max(wanted, key=wanted.get)
    state["face_up"] = [top] + [c for c in _COLORS if c != top][:4]

    assert policy.shitter_policy(state, "1") == ("draw_blind", {})
    action, params = policy.shitter_policy_v2(state, "1")
    assert action == "draw_face_up"
    assert state["face_up"][params["slot"]] == top


def test_shitter2_keep_and_turn_dispatch():
    state = logic.init_game_state(
        [{"id": 1, "name": "shittér-bot", "color": "red",  "turn_order": 0},
         {"id": 2, "name": "fishy",       "color": "blue", "turn_order": 1}], "usa")
    pending = state["player_states"]["1"]["pending_tickets"]
    keep = bot_keep_initial_tickets(state, "1", pending, "shitter_bot_2")
    assert len(keep) >= 2                              # uses the shitter ticket chooser
    for pid in ("1", "2"):
        ps = state["player_states"][pid]
        logic.keep_initial_tickets(state, pid, ps["pending_tickets"][:2])
    action, _ = bot_turn(state, "1", "shitter_bot_2")
    assert action in ("claim", "draw_face_up", "draw_blind", "draw_tickets")


def test_full_game_with_shitter2_targeting_fishy_completes():
    # Full end-to-end: shittér-bot seats sabotage the "fishy" seat all game; the
    # game must still complete cleanly (no illegal move / crash from the overlay).
    try:
        from tests.test_full_game import run_full_game
    except ImportError:
        from test_full_game import run_full_game
    specs = [
        {"id": 1, "name": "shittér-bot", "color": "red",   "turn_order": 0},
        {"id": 2, "name": "fishy",       "color": "blue",  "turn_order": 1},
        {"id": 3, "name": "chinmay",     "color": "green", "turn_order": 2},
    ]
    for _ in range(3):
        state = run_full_game(specs, "usa", "shitter_bot_2")
        assert state["phase"] == "ended"
        assert state["winner_id"] in ("1", "2", "3")
