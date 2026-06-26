"""Tests for ticket-decision telemetry (app._log_ticket_decision).

Captures what tickets were OFFERED, KEPT, and (crucially) REJECTED plus the
decision context — the signal needed to learn human ticket selection, which the
replay log never stored.
"""
import game_logic as logic


def _state():
    players = [
        {"id": 1, "name": "human",       "color": "red",  "turn_order": 0},
        {"id": 2, "name": "shitter-bot", "color": "blue", "turn_order": 1},
    ]
    return logic.init_game_state(players, "usa")


def test_logs_offered_kept_rejected():
    from app import _log_ticket_decision
    st = _state()
    pid = "1"
    offered = list(st["player_states"][pid]["pending_tickets"])
    assert len(offered) >= 3
    keep = offered[:2]
    assert logic.keep_initial_tickets(st, pid, keep)["ok"]

    _log_ticket_decision(st, pid, offered, keep, is_bot=False)

    decs = st.get("ticket_decisions")
    assert decs and len(decs) == 1
    ev = decs[0]
    assert [t["id"] for t in ev["offered"]] == [int(t) for t in offered]
    assert {t["id"] for t in ev["kept"]} == {int(t) for t in keep}
    assert {t["id"] for t in ev["rejected"]} == set(int(t) for t in offered) - {int(t) for t in keep}
    # context + ticket detail resolved from the map
    assert ev["is_bot"] is False and ev["build"] is None
    assert ev["trains"] == 45 and ev["phase"] == "initial_tickets"
    assert all(t["points"] and t["start"] and t["end"] for t in ev["offered"])


def test_bot_decision_is_stamped_with_build():
    from app import _log_ticket_decision, BOT_BUILD
    st = _state()
    pid = "2"
    offered = list(st["player_states"][pid]["pending_tickets"])
    keep = offered[:2]
    _log_ticket_decision(st, pid, offered, keep, is_bot=True, bot_type="shitter_bot")
    ev = st["ticket_decisions"][0]
    assert ev["is_bot"] is True
    assert ev["bot_type"] == "shitter_bot"
    assert ev["build"] == BOT_BUILD


def test_empty_offer_logs_nothing_and_never_raises():
    from app import _log_ticket_decision
    st = _state()
    _log_ticket_decision(st, "1", [], [], is_bot=False)
    assert "ticket_decisions" not in st or st["ticket_decisions"] == []
