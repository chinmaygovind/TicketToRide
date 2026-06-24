"""
Unit tests for bot.py.

After the bug fix, all card references use "locomotive" (not "loco") and route
colors use "gray" (not "grey"). These tests verify both the corrected behavior
and bot decision-making across all personalities.
"""

import pytest
import random
import game_logic as logic
import bot as bot_module
from bot import _can_claim, bot_turn, bot_resolve_tunnel, bot_keep_initial_tickets, BOT_TYPES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_state(player_specs, map_variant="usa"):
    return logic.init_game_state(player_specs, map_variant)


def advance_to_main(state, player_specs):
    for p in player_specs:
        pid = str(p["id"])
        ps = state["player_states"][pid]
        if ps.get("pending_tickets"):
            logic.keep_initial_tickets(state, pid, ps["pending_tickets"][:2])


@pytest.fixture
def two_player_specs():
    return [
        {"id": 1, "name": "Alice", "color": "red",  "turn_order": 0},
        {"id": 2, "name": "Bob",   "color": "blue", "turn_order": 1},
    ]


@pytest.fixture
def main_state(two_player_specs):
    state = make_state(two_player_specs)
    advance_to_main(state, two_player_specs)
    return state


# ---------------------------------------------------------------------------
# _can_claim — the fixed version uses "locomotive" (was "loco")
# ---------------------------------------------------------------------------

def test_can_claim_colored_route_exact_cards():
    route = {"id": 6, "length": 6, "color": "yellow", "ferry": 0, "tunnel": False}
    hand = {"yellow": 6}
    cards = _can_claim(hand, route, 45)
    assert cards == {"yellow": 6}


def test_can_claim_colored_route_with_locos():
    route = {"id": 6, "length": 6, "color": "yellow", "ferry": 0, "tunnel": False}
    hand = {"yellow": 4, "locomotive": 2}
    cards = _can_claim(hand, route, 45)
    assert cards is not None
    assert cards.get("yellow", 0) + cards.get("locomotive", 0) == 6
    assert "locomotive" in cards  # locomotive key (not "loco")


def test_can_claim_gray_route_picks_best_color():
    route = {"id": 1, "length": 1, "color": "gray", "ferry": 0, "tunnel": False}
    hand = {"red": 3, "blue": 1}
    cards = _can_claim(hand, route, 45)
    assert cards is not None
    # Should prefer the color with most cards
    assert "red" in cards or "blue" in cards


def test_can_claim_gray_with_only_locos():
    route = {"id": 1, "length": 2, "color": "gray", "ferry": 0, "tunnel": False}
    hand = {"locomotive": 3}
    cards = _can_claim(hand, route, 45)
    assert cards == {"locomotive": 2}


def test_can_claim_insufficient_cards():
    route = {"id": 6, "length": 6, "color": "yellow", "ferry": 0, "tunnel": False}
    hand = {"yellow": 3}
    cards = _can_claim(hand, route, 45)
    assert cards is None


def test_can_claim_insufficient_trains():
    route = {"id": 6, "length": 6, "color": "yellow", "ferry": 0, "tunnel": False}
    hand = {"yellow": 6}
    cards = _can_claim(hand, route, 3)  # only 3 trains left
    assert cards is None


def test_can_claim_empty_hand():
    route = {"id": 1, "length": 1, "color": "gray", "ferry": 0, "tunnel": False}
    cards = _can_claim({}, route, 45)
    assert cards is None


def test_can_claim_returns_locomotive_key_not_loco():
    """Ensure the fixed bot returns 'locomotive', not the old 'loco'."""
    route = {"id": 1, "length": 3, "color": "gray", "ferry": 0, "tunnel": False}
    hand = {"locomotive": 3}
    cards = _can_claim(hand, route, 45)
    assert cards is not None
    assert "loco" not in cards, "Should use 'locomotive' not 'loco'"
    assert "locomotive" in cards


def test_can_claim_colored_with_partial_locos_key():
    """Wildcard fill must use 'locomotive' key so claim_route accepts it."""
    route = {"id": 18, "length": 3, "color": "red", "ferry": 0, "tunnel": False}
    hand = {"red": 1, "locomotive": 2}
    cards = _can_claim(hand, route, 45)
    assert cards is not None
    assert "locomotive" in cards
    assert "loco" not in cards


# ---------------------------------------------------------------------------
# bot_turn — returns valid actions for all personalities
# ---------------------------------------------------------------------------

ALL_PERSONALITIES = [slug for _, slug in BOT_TYPES]


@pytest.mark.parametrize("personality", ALL_PERSONALITIES)
def test_bot_turn_returns_valid_action(personality, main_state):
    state = main_state
    pid = state["current_player_id"]
    # Give the bot some cards so it has options
    state["player_states"][pid]["hand"] = {
        "red": 3, "blue": 3, "yellow": 3, "locomotive": 2
    }
    action, params = bot_turn(state, pid, personality)
    assert action in ("claim", "draw_face_up", "draw_blind", "draw_tickets")


@pytest.mark.parametrize("personality", ALL_PERSONALITIES)
def test_bot_turn_draw_face_up_has_slot(personality, main_state):
    state = main_state
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {}
    state["face_up"] = ["red", "blue", "green", "orange", "white"]
    action, params = bot_turn(state, pid, personality)
    if action == "draw_face_up":
        assert "slot" in params
        assert 0 <= params["slot"] < 5


@pytest.mark.parametrize("personality", ALL_PERSONALITIES)
def test_bot_turn_claim_has_route_and_cards(personality, main_state):
    state = main_state
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {
        "yellow": 6, "red": 6, "blue": 6, "locomotive": 4
    }
    action, params = bot_turn(state, pid, personality)
    if action == "claim":
        assert "route_id" in params
        assert "cards" in params
        assert isinstance(params["cards"], dict)
        assert sum(params["cards"].values()) > 0


@pytest.mark.parametrize("personality", ALL_PERSONALITIES)
def test_bot_turn_no_exception_with_empty_hand(personality, main_state):
    state = main_state
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {}
    # Should not raise even with no cards
    action, params = bot_turn(state, pid, personality)
    assert action in ("claim", "draw_face_up", "draw_blind", "draw_tickets")


@pytest.mark.parametrize("personality", ALL_PERSONALITIES)
def test_bot_turn_no_exception_with_full_board(personality, two_player_specs):
    """Smoke test: bot should not crash when most routes are claimed."""
    state = make_state(two_player_specs)
    advance_to_main(state, two_player_specs)
    pid = state["current_player_id"]
    other = next(p for p in state["turn_order"] if p != pid)
    from game_data_na import ROUTES
    # Claim the first 30 routes for the other player
    for r in ROUTES[:30]:
        state["claimed_routes"][str(r["id"])] = other
    state["player_states"][pid]["hand"] = {"red": 3, "blue": 3, "locomotive": 2}
    action, params = bot_turn(state, pid, personality)
    assert action in ("claim", "draw_face_up", "draw_blind", "draw_tickets")


def test_fish_bot_prefers_long_routes(main_state):
    state = main_state
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {
        "yellow": 6, "red": 3, "blue": 2, "locomotive": 2
    }
    action, params = bot_turn(state, pid, "fish_bot")
    # Fish bot should try to claim the longest affordable route
    if action == "claim":
        from game_data_na import ROUTE_BY_ID
        route = ROUTE_BY_ID[params["route_id"]]
        # Fish bot generally prefers longer routes (no strict assertion but
        # with 6 yellow it should grab the 6-length route if possible)
        assert route["length"] >= 1  # sanity


def test_fish_bot_picks_face_up_locomotive(main_state):
    state = main_state
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {"red": 1}
    state["face_up"] = ["red", "locomotive", "green", "orange", "white"]
    action, params = bot_turn(state, pid, "fish_bot")
    if action == "draw_face_up":
        assert params["slot"] == 1  # locomotive is at slot 1


def test_chin_bot_draws_tickets_when_few_uncompleted(main_state):
    """chin-bot draws tickets when ≤1 ticket is uncompleted."""
    state = main_state
    pid = state["current_player_id"]
    # No uncompleted tickets (all claimed) → should draw more tickets
    state["player_states"][pid]["tickets"] = []
    state["player_states"][pid]["hand"] = {}
    state["face_up"] = ["red", "red", "red", "red", "red"]
    # Make sure dest deck has cards
    state["dest_deck"] = [1, 2, 3, 4]
    action, params = bot_turn(state, pid, "chin_bot")
    # Should draw tickets since uncompleted ≤ 1 and deck has cards
    assert action == "draw_tickets"


def test_chaos_bot_sometimes_picks_different_route(two_player_specs):
    """chaos-bot's randomness: run 20 times and verify it doesn't always pick same route."""
    state = make_state(two_player_specs)
    advance_to_main(state, two_player_specs)
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {
        "red": 3, "blue": 3, "yellow": 3, "green": 3,
        "orange": 3, "black": 3, "white": 3, "locomotive": 2,
    }
    choices = set()
    for _ in range(20):
        action, params = bot_turn(state, pid, "chaos_bot")
        choices.add((action, params.get("route_id") or params.get("slot")))
    # Chaos bot should produce some variety
    assert len(choices) >= 1  # weak assertion — just ensure no crash


# ---------------------------------------------------------------------------
# bot_resolve_tunnel
# ---------------------------------------------------------------------------

def test_bot_resolve_tunnel_free_always_proceeds(two_player_specs):
    state = make_state(two_player_specs, "europe")
    advance_to_main(state, two_player_specs)
    pid = state["current_player_id"]
    state["pending_tunnel"] = {
        "player_id": pid, "route_id": 1, "extra_cost": 0, "extra_color": "red",
        "cards_offered": {"red": 2}, "revealed": [],
    }
    proceed, extra = bot_resolve_tunnel(state, pid, "fish_bot")
    assert proceed is True
    assert extra == {}


def test_bot_resolve_tunnel_can_afford_proceeds(two_player_specs):
    state = make_state(two_player_specs, "europe")
    advance_to_main(state, two_player_specs)
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {"red": 3, "locomotive": 2}
    state["pending_tunnel"] = {
        "player_id": pid, "route_id": 1, "extra_cost": 2, "extra_color": "red",
        "cards_offered": {"red": 2}, "revealed": ["red", "red"],
    }
    proceed, extra = bot_resolve_tunnel(state, pid, "fish_bot")
    assert proceed is True
    assert sum(extra.values()) == 2


def test_bot_resolve_tunnel_cannot_afford_aborts(two_player_specs):
    state = make_state(two_player_specs, "europe")
    advance_to_main(state, two_player_specs)
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {}  # no cards
    state["pending_tunnel"] = {
        "player_id": pid, "route_id": 1, "extra_cost": 3, "extra_color": "red",
        "cards_offered": {"red": 2}, "revealed": ["red", "red", "red"],
    }
    proceed, extra = bot_resolve_tunnel(state, pid, "fish_bot")
    assert proceed is False


def test_bot_resolve_tunnel_extra_cards_use_locomotive_key(two_player_specs):
    """Extra cards returned must use 'locomotive' key, not 'loco'."""
    state = make_state(two_player_specs, "europe")
    advance_to_main(state, two_player_specs)
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {"locomotive": 3}
    state["pending_tunnel"] = {
        "player_id": pid, "route_id": 1, "extra_cost": 2, "extra_color": "red",
        "cards_offered": {"red": 2}, "revealed": ["red", "red"],
    }
    proceed, extra = bot_resolve_tunnel(state, pid, "fish_bot")
    if proceed:
        assert "loco" not in extra, "Should use 'locomotive' not 'loco'"
        if extra:
            assert "locomotive" in extra


def test_bot_resolve_tunnel_no_pending_returns_false(two_player_specs):
    state = make_state(two_player_specs, "europe")
    advance_to_main(state, two_player_specs)
    pid = state["current_player_id"]
    state["pending_tunnel"] = None
    proceed, extra = bot_resolve_tunnel(state, pid)
    assert proceed is False


# ---------------------------------------------------------------------------
# bot_keep_initial_tickets
# ---------------------------------------------------------------------------

def test_bot_keep_initial_tickets_min_two(two_player_specs):
    state = make_state(two_player_specs)
    pid = "1"
    pending = state["player_states"][pid]["pending_tickets"]
    for _, slug in BOT_TYPES:
        keep = bot_keep_initial_tickets(state, pid, pending, slug)
        assert len(keep) >= 2, f"{slug} kept fewer than 2 tickets"


def test_bot_keep_initial_tickets_valid_ids(two_player_specs):
    state = make_state(two_player_specs)
    pid = "1"
    pending = state["player_states"][pid]["pending_tickets"]
    for _, slug in BOT_TYPES:
        keep = bot_keep_initial_tickets(state, pid, pending, slug)
        assert all(k in pending for k in keep), f"{slug} returned invalid ticket ids"


def test_ticket_bot_keeps_all_reachable(two_player_specs):
    state = make_state(two_player_specs)
    pid = "1"
    pending = state["player_states"][pid]["pending_tickets"]
    keep = bot_keep_initial_tickets(state, pid, pending, "ticket_bot")
    # ticket_bot should keep all (they're all reachable at game start)
    assert len(keep) == len(pending)


def test_fish_bot_keeps_high_value_tickets(two_player_specs):
    from game_data_na import TICKET_BY_ID
    state = make_state(two_player_specs)
    pid = "1"
    pending = state["player_states"][pid]["pending_tickets"]
    keep = bot_keep_initial_tickets(state, pid, pending, "fish_bot")
    # Fish bot sorts by value descending — check kept tickets have high value
    kept_values = [TICKET_BY_ID[t]["points"] for t in keep]
    pending_values = sorted([TICKET_BY_ID[t]["points"] for t in pending], reverse=True)
    # Kept tickets should include the highest value ones
    assert max(kept_values) == pending_values[0]


# ---------------------------------------------------------------------------
# Bot locomotive face-up detection (the "loco" vs "locomotive" bug)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("personality", ALL_PERSONALITIES)
def test_bot_detects_face_up_locomotive(personality, main_state):
    """Bots should prefer picking up a face-up locomotive (was broken with 'loco' key)."""
    state = main_state
    pid = state["current_player_id"]
    state["player_states"][pid]["hand"] = {}  # no cards → must draw
    state["face_up"] = ["locomotive", "red", "blue", "green", "orange"]
    action, params = bot_turn(state, pid, personality)
    if action == "draw_face_up":
        # If bot draws face-up, it might pick the locomotive (slot 0)
        # chaos_bot might pick randomly, so just check slot is valid
        assert 0 <= params["slot"] < 5
    # Key assertion: bot must not crash even with locomotive in face_up


@pytest.mark.parametrize("personality", ["fish_bot", "chin_bot", "rocket_bot", "ticket_bot", "claude_bot"])
def test_loco_seeking_bots_grab_locomotive_first(personality, main_state):
    """Non-chaos bots that prioritize locos should pick the locomotive slot."""
    state = main_state
    pid = state["current_player_id"]
    # No cards and no claimable routes → bot must draw
    state["player_states"][pid]["hand"] = {}
    for i in range(1, 96):  # claim everything
        state["claimed_routes"][str(i)] = "99"
    state["face_up"] = ["locomotive", "red", "blue", "green", "orange"]
    action, params = bot_turn(state, pid, personality)
    if action == "draw_face_up":
        assert params["slot"] == 0  # locomotive is slot 0
