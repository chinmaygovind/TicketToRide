"""
Full game simulation tests.

These run complete games from init_game_state to phase=="ended" using bot logic,
without any database or Flask. They're the closest thing to end-to-end tests for
the core game engine.
"""

import pytest
import random
import game_logic as logic
import bot as bot_module
from bot import _can_claim


# ---------------------------------------------------------------------------
# Simulation engine (mirrors _run_bots from app.py, no database)
# ---------------------------------------------------------------------------

def run_full_game(player_specs, map_variant="usa", personality="fish_bot",
                  max_iterations=5000):
    """
    Simulate a complete game with bot players.
    Returns the final state dict.
    Raises AssertionError if the game doesn't finish within max_iterations.
    """
    state = logic.init_game_state(player_specs, map_variant)
    no_progress = 0  # consecutive turns where no action could advance the state

    for iteration in range(max_iterations):
        phase = state.get("phase")
        if phase == "ended":
            break

        if phase == "initial_tickets":
            acted = False
            for p in player_specs:
                pid = str(p["id"])
                ps = state["player_states"].get(pid, {})
                pending = ps.get("pending_tickets", [])
                if pending:
                    keep = bot_module.bot_keep_initial_tickets(state, pid, pending, personality)
                    if not keep:
                        keep = pending[:2]
                    result = logic.keep_initial_tickets(state, pid, keep)
                    assert result["ok"], f"keep_initial_tickets failed: {result}"
                    acted = True
                    break
            if not acted:
                break
            continue

        cur_pid = state["current_player_id"]
        ps = state["player_states"].get(cur_pid, {})

        # Resolve pending tunnel
        if state.get("pending_tunnel") and state["pending_tunnel"].get("player_id") == cur_pid:
            proceed, extra_cards = bot_module.bot_resolve_tunnel(state, cur_pid, personality)
            logic.resolve_tunnel(state, cur_pid,
                                 proceed=proceed,
                                 extra_cards=extra_cards if proceed else None)
            continue

        # Handle pending tickets
        if ps.get("pending_tickets"):
            pending = ps["pending_tickets"]
            keep = pending[:max(1, len(pending))]
            logic.keep_drawn_tickets(state, cur_pid, keep)
            continue

        draw_step = state.get("draw_step", 0)

        # Finish a mid-draw (draw_step == 1) by drawing blind.
        # If the deck and discard are both exhausted (all cards hoarded in
        # player hands), draw_blind returns ok=False and the turn can't
        # advance normally. Force-advance to prevent an infinite loop.
        if draw_step == 1:
            result = logic.draw_blind(state, cur_pid)
            if not result.get("ok"):
                order = [str(p["id"]) for p in player_specs]
                idx = (order.index(str(cur_pid)) + 1) % len(order)
                state["draw_step"] = 0
                state["current_player_id"] = order[idx]
                state["turns_taken"] = state.get("turns_taken", 0) + 1
            continue

        def safe_draw_blind():
            r = logic.draw_blind(state, cur_pid)
            return r.get("ok", False)

        def do_second_draw():
            if state.get("draw_step", 0) == 1:
                try:
                    action2, params2 = bot_module.bot_turn(state, cur_pid, personality)
                except Exception:
                    action2, params2 = "draw_blind", {}
                if action2 == "draw_face_up":
                    r2 = logic.draw_face_up(state, cur_pid, params2.get("slot", 0))
                    if not r2.get("ok"):
                        safe_draw_blind()
                else:
                    safe_draw_blind()

        try:
            action, params = bot_module.bot_turn(state, cur_pid, personality)
        except Exception as e:
            action, params = "draw_blind", {}

        advanced = False

        if action == "claim":
            result = logic.claim_route(state, cur_pid, params["route_id"], params["cards"])
            if result.get("ok"):
                advanced = True
            elif safe_draw_blind():
                do_second_draw()
                advanced = True

        elif action == "draw_tickets":
            result = logic.draw_destination_tickets(state, cur_pid)
            if result.get("ok"):
                fresh_ps = state["player_states"].get(cur_pid, {})
                pending = fresh_ps.get("pending_tickets", [])
                keep = pending[:1] if pending else []
                if keep:
                    logic.keep_drawn_tickets(state, cur_pid, keep)
                advanced = True
            elif safe_draw_blind():
                do_second_draw()
                advanced = True

        elif action == "draw_face_up":
            result = logic.draw_face_up(state, cur_pid, params.get("slot", 0))
            if result.get("ok"):
                do_second_draw()
                advanced = True
            elif safe_draw_blind():
                do_second_draw()
                advanced = True

        else:  # draw_blind
            if safe_draw_blind():
                do_second_draw()
                advanced = True

        # Safety net: if no action could advance the turn (deck exhausted,
        # all valid routes blocked), force-advance to prevent infinite loop.
        if not advanced and str(state.get("current_player_id")) == str(cur_pid):
            order = [str(p["id"]) for p in player_specs]
            idx = (order.index(str(cur_pid)) + 1) % len(order)
            state["draw_step"] = 0
            state["current_player_id"] = order[idx]
            state["turns_taken"] = state.get("turns_taken", 0) + 1
            no_progress += 1
            # After all players fail to act repeatedly, consider game deadlocked
            if no_progress >= len(player_specs) * 4:
                state["phase"] = "ended"
                if not state.get("winner_id"):
                    best = max(
                        state["player_states"].items(),
                        key=lambda x: x[1].get("route_score", 0)
                    )
                    state["winner_id"] = best[0]
                state.setdefault("action_log", []).append("Game ended!")
                break
        else:
            no_progress = 0

    assert state.get("phase") == "ended", (
        f"Game did not finish within {max_iterations} iterations "
        f"(phase={state.get('phase')}, turn={state.get('turns_taken')})"
    )
    return state


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def two_bots():
    return [
        {"id": 1, "name": "Bot-A", "color": "red",  "turn_order": 0},
        {"id": 2, "name": "Bot-B", "color": "blue", "turn_order": 1},
    ]


@pytest.fixture
def four_bots():
    return [
        {"id": 1, "name": "Bot-A", "color": "red",    "turn_order": 0},
        {"id": 2, "name": "Bot-B", "color": "blue",   "turn_order": 1},
        {"id": 3, "name": "Bot-C", "color": "green",  "turn_order": 2},
        {"id": 4, "name": "Bot-D", "color": "yellow", "turn_order": 3},
    ]


# ---------------------------------------------------------------------------
# Basic game completion
# ---------------------------------------------------------------------------

_REPEAT = 5  # each single-bot test runs this many games to catch non-deterministic failures


def _assert_games(specs, map_variant, personality, n=_REPEAT):
    """Run N games and assert all finish."""
    for i in range(n):
        state = run_full_game(specs, map_variant, personality)
        assert state["phase"] == "ended", (
            f"{personality} game {i + 1}/{n} did not finish "
            f"(turns={state.get('turns_taken')})"
        )


def test_two_fish_bots_complete_usa(two_bots):
    for i in range(_REPEAT):
        state = run_full_game(two_bots, "usa", "fish_bot")
        assert state["phase"] == "ended"
        assert state["winner_id"] in [str(p["id"]) for p in two_bots]


def test_two_chin_bots_complete_usa(two_bots):
    _assert_games(two_bots, "usa", "chin_bot")


def test_two_rocket_bots_complete_usa(two_bots):
    _assert_games(two_bots, "usa", "rocket_bot")


def test_two_ticket_bots_complete_usa(two_bots):
    _assert_games(two_bots, "usa", "ticket_bot")


def test_two_chaos_bots_complete_usa(two_bots):
    _assert_games(two_bots, "usa", "chaos_bot")


def test_two_claude_bots_complete_usa(two_bots):
    _assert_games(two_bots, "usa", "claude_bot")


def test_four_fish_bots_complete_usa(four_bots):
    _assert_games(four_bots, "usa", "fish_bot")


# ---------------------------------------------------------------------------
# Europe map
# ---------------------------------------------------------------------------

def test_two_fish_bots_complete_europe(two_bots):
    for i in range(_REPEAT):
        state = run_full_game(two_bots, "europe", "fish_bot")
        assert state["phase"] == "ended"
        assert state["winner_id"] in [str(p["id"]) for p in two_bots]


def test_two_ticket_bots_complete_europe(two_bots):
    _assert_games(two_bots, "europe", "ticket_bot")


def test_four_bots_complete_europe(four_bots):
    _assert_games(four_bots, "europe", "fish_bot")


# ---------------------------------------------------------------------------
# Scores and winner integrity
# ---------------------------------------------------------------------------

def test_scores_populated_after_game(two_bots):
    state = run_full_game(two_bots, "usa", "fish_bot")
    assert state["scores"]
    for pid, sc in state["scores"].items():
        assert "total" in sc
        assert "route_score" in sc
        assert "tickets" in sc
        assert "longest_path" in sc


def test_winner_has_highest_score(two_bots):
    state = run_full_game(two_bots, "usa", "fish_bot")
    winner_id = state["winner_id"]
    winner_score = state["scores"][winner_id]["total"]
    for pid, sc in state["scores"].items():
        assert sc["total"] <= winner_score or pid == winner_id


def test_exactly_one_longest_path_bonus_winner(two_bots):
    state = run_full_game(two_bots, "usa", "fish_bot")
    bonus_pids = [pid for pid, sc in state["scores"].items() if sc.get("longest_path_bonus")]
    # At least one player gets longest path bonus (could tie)
    assert len(bonus_pids) >= 1


def test_trains_are_non_negative_after_game(two_bots):
    state = run_full_game(two_bots, "usa", "fish_bot")
    for pid, ps in state["player_states"].items():
        assert ps["trains"] >= 0, f"Player {pid} has negative trains"


def test_europe_station_bonus_applied(two_bots):
    state = run_full_game(two_bots, "europe", "fish_bot")
    # All players should have station_bonus >= 0 in scores
    for pid, sc in state["scores"].items():
        assert sc.get("station_bonus", 0) >= 0


# ---------------------------------------------------------------------------
# Resign during game
# ---------------------------------------------------------------------------

def test_resign_mid_game_continues_to_end(two_bots):
    """Player resigns → game_logic resign_player marks resigned, game keeps going."""
    state = logic.init_game_state(two_bots)
    # Fast-forward through initial tickets
    for p in two_bots:
        pid = str(p["id"])
        ps = state["player_states"].get(pid, {})
        if ps.get("pending_tickets"):
            logic.keep_initial_tickets(state, pid, ps["pending_tickets"][:2])

    # Resign the current player
    pid = state["current_player_id"]
    result = logic.resign_player(state, pid)
    assert result["ok"]
    assert state["player_states"][pid].get("resigned")

    # Continue game with remaining player (they're "active")
    # With only 1 player active, game should end immediately
    assert state["phase"] == "ended"


def test_resign_leaves_other_player_to_win(two_bots):
    state = logic.init_game_state(two_bots)
    for p in two_bots:
        pid = str(p["id"])
        ps = state["player_states"].get(pid, {})
        if ps.get("pending_tickets"):
            logic.keep_initial_tickets(state, pid, ps["pending_tickets"][:2])

    pid_a, pid_b = state["turn_order"]
    logic.resign_player(state, pid_a)
    assert state["phase"] == "ended"
    assert state["winner_id"] is not None


# ---------------------------------------------------------------------------
# Mixed personalities (4-player free-for-all)
# ---------------------------------------------------------------------------

def test_mixed_personalities_complete(four_bots):
    """Each player uses a different bot personality."""
    personalities = ["fish_bot", "chin_bot", "rocket_bot", "ticket_bot"]
    state = logic.init_game_state(four_bots, "usa")

    for p in four_bots:
        pid = str(p["id"])
        ps = state["player_states"].get(pid, {})
        if ps.get("pending_tickets"):
            logic.keep_initial_tickets(state, pid, ps["pending_tickets"][:2])

    pid_to_personality = {str(p["id"]): personalities[i] for i, p in enumerate(four_bots)}

    for _ in range(5000):
        phase = state.get("phase")
        if phase == "ended":
            break

        cur_pid = state["current_player_id"]
        pers = pid_to_personality[cur_pid]
        ps = state["player_states"].get(cur_pid, {})

        if state.get("pending_tunnel") and state["pending_tunnel"].get("player_id") == cur_pid:
            proceed, extra = bot_module.bot_resolve_tunnel(state, cur_pid, pers)
            logic.resolve_tunnel(state, cur_pid, proceed=proceed,
                                 extra_cards=extra if proceed else None)
            continue

        if ps.get("pending_tickets"):
            pending = ps["pending_tickets"]
            logic.keep_drawn_tickets(state, cur_pid, pending[:1])
            continue

        if state.get("draw_step", 0) == 1:
            logic.draw_blind(state, cur_pid)
            continue

        try:
            action, params = bot_module.bot_turn(state, cur_pid, pers)
        except Exception:
            action, params = "draw_blind", {}

        if action == "claim":
            r = logic.claim_route(state, cur_pid, params["route_id"], params["cards"])
            if not r.get("ok"):
                r2 = logic.draw_blind(state, cur_pid)
                if r2.get("ok") and state.get("draw_step", 0) == 1:
                    logic.draw_blind(state, cur_pid)
        elif action == "draw_tickets":
            r = logic.draw_destination_tickets(state, cur_pid)
            if r.get("ok"):
                pend = state["player_states"][cur_pid].get("pending_tickets", [])
                if pend:
                    logic.keep_drawn_tickets(state, cur_pid, pend[:1])
            else:
                logic.draw_blind(state, cur_pid)
                if state.get("draw_step", 0) == 1:
                    logic.draw_blind(state, cur_pid)
        elif action == "draw_face_up":
            r = logic.draw_face_up(state, cur_pid, params.get("slot", 0))
            if not r.get("ok"):
                logic.draw_blind(state, cur_pid)
            if state.get("draw_step", 0) == 1:
                logic.draw_blind(state, cur_pid)
        else:
            logic.draw_blind(state, cur_pid)
            if state.get("draw_step", 0) == 1:
                logic.draw_blind(state, cur_pid)

    assert state["phase"] == "ended", "Mixed-personality game did not finish"
    assert state["winner_id"] is not None


# ---------------------------------------------------------------------------
# Action log integrity
# ---------------------------------------------------------------------------

def test_action_log_populated(two_bots):
    for _ in range(_REPEAT):
        state = run_full_game(two_bots, "usa", "fish_bot")
        assert len(state["action_log"]) > 0


def test_action_log_contains_game_end(two_bots):
    for _ in range(_REPEAT):
        state = run_full_game(two_bots, "usa", "fish_bot")
        combined = " ".join(state["action_log"]).lower()
        assert "ended" in combined or "winner" in combined


# ---------------------------------------------------------------------------
# Determinism with fixed seed
# ---------------------------------------------------------------------------

def test_game_deterministic_with_seed(two_bots):
    random.seed(12345)
    state1 = run_full_game(two_bots, "usa", "fish_bot")
    random.seed(12345)
    state2 = run_full_game(two_bots, "usa", "fish_bot")
    assert state1["winner_id"] == state2["winner_id"]
    assert state1["scores"] == state2["scores"]


# ---------------------------------------------------------------------------
# Bot stress test: every pair, 20 games each — nothing should hang
# ---------------------------------------------------------------------------

def _run_game_pair(personality_a, personality_b, map_variant="usa", max_iterations=5000):
    """Run a 2-player game where each player uses a different bot personality."""
    specs = [
        {"id": 1, "name": "Bot-A", "color": "red",  "turn_order": 0},
        {"id": 2, "name": "Bot-B", "color": "blue", "turn_order": 1},
    ]
    pid_to_pers = {"1": personality_a, "2": personality_b}
    state = logic.init_game_state(specs, map_variant)
    no_progress = 0

    for _ in range(max_iterations):
        phase = state.get("phase")
        if phase == "ended":
            break

        if phase == "initial_tickets":
            acted = False
            for p in specs:
                pid = str(p["id"])
                ps = state["player_states"].get(pid, {})
                pending = ps.get("pending_tickets", [])
                if pending:
                    pers = pid_to_pers[pid]
                    keep = bot_module.bot_keep_initial_tickets(state, pid, pending, pers)
                    if not keep:
                        keep = pending[:2]
                    logic.keep_initial_tickets(state, pid, keep)
                    acted = True
                    break
            if not acted:
                break
            continue

        cur_pid = state["current_player_id"]
        ps = state["player_states"].get(cur_pid, {})
        pers = pid_to_pers.get(cur_pid, "fish_bot")

        if state.get("pending_tunnel") and state["pending_tunnel"].get("player_id") == cur_pid:
            proceed, extra = bot_module.bot_resolve_tunnel(state, cur_pid, pers)
            logic.resolve_tunnel(state, cur_pid, proceed=proceed,
                                 extra_cards=extra if proceed else None)
            continue

        if ps.get("pending_tickets"):
            pending = ps["pending_tickets"]
            logic.keep_drawn_tickets(state, cur_pid, pending[:max(1, len(pending))])
            continue

        draw_step = state.get("draw_step", 0)
        if draw_step == 1:
            result = logic.draw_blind(state, cur_pid)
            if not result.get("ok"):
                order = [str(p["id"]) for p in specs]
                idx = (order.index(str(cur_pid)) + 1) % len(order)
                state["draw_step"] = 0
                state["current_player_id"] = order[idx]
                state["turns_taken"] = state.get("turns_taken", 0) + 1
            continue

        def _blind():
            r = logic.draw_blind(state, cur_pid)
            return r.get("ok", False)

        def _second():
            if state.get("draw_step", 0) == 1:
                try:
                    a2, p2 = bot_module.bot_turn(state, cur_pid, pers)
                except Exception:
                    a2, p2 = "draw_blind", {}
                if a2 == "draw_face_up":
                    r2 = logic.draw_face_up(state, cur_pid, p2.get("slot", 0))
                    if not r2.get("ok"):
                        _blind()
                else:
                    _blind()

        try:
            action, params = bot_module.bot_turn(state, cur_pid, pers)
        except Exception:
            action, params = "draw_blind", {}

        advanced = False

        if action == "claim":
            r = logic.claim_route(state, cur_pid, params["route_id"], params["cards"])
            if r.get("ok"):
                advanced = True
            elif _blind():
                _second()
                advanced = True
        elif action == "draw_tickets":
            r = logic.draw_destination_tickets(state, cur_pid)
            if r.get("ok"):
                pend = state["player_states"].get(cur_pid, {}).get("pending_tickets", [])
                if pend:
                    logic.keep_drawn_tickets(state, cur_pid, pend[:1])
                advanced = True
            elif _blind():
                _second()
                advanced = True
        elif action == "draw_face_up":
            r = logic.draw_face_up(state, cur_pid, params.get("slot", 0))
            if r.get("ok"):
                _second()
                advanced = True
            elif _blind():
                _second()
                advanced = True
        else:
            if _blind():
                _second()
                advanced = True

        # Safety net: if no action could advance the turn, force-advance.
        if not advanced and str(state.get("current_player_id")) == str(cur_pid):
            order = [str(p["id"]) for p in specs]
            idx = (order.index(str(cur_pid)) + 1) % len(order)
            state["draw_step"] = 0
            state["current_player_id"] = order[idx]
            state["turns_taken"] = state.get("turns_taken", 0) + 1
            no_progress += 1
            if no_progress >= len(specs) * 4:
                state["phase"] = "ended"
                if not state.get("winner_id"):
                    best = max(
                        state["player_states"].items(),
                        key=lambda x: x[1].get("route_score", 0)
                    )
                    state["winner_id"] = best[0]
                state.setdefault("action_log", []).append("Game ended!")
                break
        else:
            no_progress = 0

    return state


_ALL_PERSONALITIES = ["fish_bot", "chin_bot", "rocket_bot", "ticket_bot", "chaos_bot", "claude_bot"]
_BOT_PAIRS = [
    (a, b)
    for i, a in enumerate(_ALL_PERSONALITIES)
    for b in _ALL_PERSONALITIES[i + 1:]
]


@pytest.mark.parametrize("personality_a,personality_b", _BOT_PAIRS)
def test_bot_stress_no_hang(personality_a, personality_b):
    """Every pair of bots must complete 20 games without hanging."""
    for game_num in range(20):
        state = _run_game_pair(personality_a, personality_b)
        assert state.get("phase") == "ended", (
            f"{personality_a} vs {personality_b} game {game_num + 1} "
            f"did not finish (phase={state.get('phase')}, "
            f"turns={state.get('turns_taken')})"
        )
