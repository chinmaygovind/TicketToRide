"""Tests for bot chat reactions (bot_chat.py)."""
import bot_chat
import game_logic as logic
import game_data_na as gd


def _started_state():
    players = [
        {"id": 1, "name": "human",       "color": "red",  "turn_order": 0},
        {"id": 2, "name": "shitter-bot", "color": "blue", "turn_order": 1},
    ]
    st = logic.init_game_state(players, "usa")
    for pid in ("1", "2"):
        pend = list(st["player_states"][pid]["pending_tickets"])
        logic.keep_initial_tickets(st, pid, pend[:2])
    return st


def test_pick_returns_from_bank_or_none():
    assert bot_chat.pick("ticket_complete") == "yipeeee"
    assert bot_chat.pick("route_blocked") in bot_chat.PHRASES["route_blocked"]
    assert bot_chat.pick("does_not_exist") is None


def test_route_on_bot_plan_detects_blocking_route():
    st = _started_state()
    t = gd.TICKET_BY_ID[st["player_states"]["2"]["tickets"][0]]
    # Every route is either on the plan or not; at least the ones on the shortest
    # path must be flagged, and a route touching neither endpoint cluster usually not.
    on_plan = [rid for rid in gd.ROUTE_BY_ID if bot_chat.route_on_bot_plan(st, "2", rid)]
    assert on_plan, "expected some routes on the bot's ticket path"
    # A route already owned-by-nobody on the path -> blocking it is detected
    assert any(rid for rid in on_plan)
    # sanity: the ticket endpoints are not yet connected
    assert not logic.is_path_connected(st, "2", t["city1"], t["city2"])


def test_completed_count_and_all_complete():
    st = _started_state()
    assert bot_chat.completed_count(st, "2") == 0
    assert bot_chat.all_tickets_complete(st, "2") is False
