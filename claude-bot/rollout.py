"""
Rollout policies for ISMCTS simulations.

Each policy: (state, pid) -> (action, params)
run_rollout: play state to terminal with policy_fn, return score for observer_pid.
"""
import sys
import os
_HERE   = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
sys.path.insert(0, _PARENT)
sys.path.insert(0, _HERE)

import random
import game_logic as logic
from adapter import get_legal_moves, apply_move, is_terminal, terminal_score, current_player
from graph_cache import ROUTES_BY_VALUE, static_cost, DOUBLE_ROUTE_PARTNER, TICKET_ROUTE_RELEVANCE
from game_data_na import ROUTE_BY_ID, ROUTE_SCORING, TICKET_BY_ID


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _can_claim_fast(hand, route, trains, n_players, claimed, pid,
                    sorted_hand=None, locos=None):
    """Inline claim check. Pass sorted_hand/locos to avoid recomputation."""
    length = route["length"]
    if length > trains:
        return None
    rid_str = str(route["id"])
    if rid_str in claimed:
        return None
    if n_players <= 3:
        partner = DOUBLE_ROUTE_PARTNER.get(route["id"])
        if partner and str(partner) in claimed:
            return None
    color = route.get("color", "gray")
    if locos is None:
        locos = hand.get("locomotive", 0)

    def _try(c):
        have = hand.get(c, 0)
        cu = min(have, length)
        lu = length - cu
        if lu > locos:
            return None
        r = {}
        if cu: r[c] = cu
        if lu: r["locomotive"] = lu
        return r

    if color == "gray":
        sh = sorted_hand if sorted_hand is not None else sorted(
            ((c, n) for c, n in hand.items() if c != "locomotive" and n > 0),
            key=lambda x: -x[1],
        )
        for c, _ in sh:
            r = _try(c)
            if r is not None: return r
        return {"locomotive": length} if locos >= length else None
    r = _try(color)
    if r is not None: return r
    return {"locomotive": length} if locos >= length else None


# ---------------------------------------------------------------------------
# Random policy — fastest; good enough for early ISMCTS iterations
# ---------------------------------------------------------------------------

def random_policy(state: dict, pid: str) -> tuple:
    moves = get_legal_moves(state, pid)
    if not moves:
        return "draw_blind", {}
    return random.choice(moves)


# ---------------------------------------------------------------------------
# Fast heuristic policy — O(routes) per call, zero Dijkstra
# Scores routes by point value + ticket proximity (via APSP cache)
# ---------------------------------------------------------------------------

def heuristic_policy(state: dict, pid: str) -> tuple:
    ps        = state["player_states"].get(pid, {})
    hand      = ps.get("hand", {})
    trains    = ps.get("trains", 45)
    tickets   = ps.get("tickets", [])
    draw_step = state.get("draw_step", 0)
    face_up   = state["face_up"]
    claimed   = state["claimed_routes"]
    n_players = len(state.get("turn_order", []))
    locos     = hand.get("locomotive", 0)

    # Precompute sorted hand for gray routes (once per call, not per route)
    sorted_hand = sorted(
        ((c, n) for c, n in hand.items() if c != "locomotive" and n > 0),
        key=lambda x: -x[1],
    )

    # Ticket bonus via precomputed relevance map — zero static_cost calls at runtime
    ticket_bonus: dict[int, float] = {}
    for tid in tickets:
        t = TICKET_BY_ID.get(tid)
        if not t or logic.is_path_connected(state, pid, t["city1"], t["city2"]):
            continue  # skip completed tickets
        for rid, bonus in TICKET_ROUTE_RELEVANCE.get(tid, ()):
            if str(rid) not in claimed:
                ticket_bonus[rid] = ticket_bonus.get(rid, 0) + bonus

    # Chain bonus: cities already reachable from player's network
    my_claimed_cities: set[str] = set()
    for rid_str, owner in claimed.items():
        if owner == pid:
            r = ROUTE_BY_ID.get(int(rid_str))
            if r:
                my_claimed_cities.add(r["city1"])
                my_claimed_cities.add(r["city2"])

    # Score routes using fish_bot-style long-route weighting.
    # Only claim if score clears threshold (mimics fish_bot's patient strategy).
    _LW = {1: 0.1, 2: 0.2, 3: 0.5, 4: 1.0, 5: 3.0, 6: 6.0}
    CLAIM_THRESHOLD = 2.0   # 4-car route (score=4.0) always clears this

    if draw_step == 0:
        best_rid, best_cards, best_score = None, None, -1.0
        for _, rid, route in ROUTES_BY_VALUE:
            cards = _can_claim_fast(hand, route, trains, n_players, claimed, pid,
                                    sorted_hand, locos)
            if cards is None:
                continue
            ln = route["length"]
            score = _LW.get(ln, 1.0) * ln + ticket_bonus.get(rid, 0)
            if route["city1"] in my_claimed_cities or route["city2"] in my_claimed_cities:
                score *= 1.3
            if score > best_score:
                best_score = score
                best_rid   = rid
                best_cards = cards
        if best_rid is not None and best_score >= CLAIM_THRESHOLD:
            return "claim", {"route_id": best_rid, "cards": best_cards}

    # Prefer locomotive on draw_step=0
    if draw_step == 0:
        for i, card in enumerate(face_up):
            if card == "locomotive":
                return "draw_face_up", {"slot": i}

    # Draw a needed color
    needed: set[str] = set()
    for _, rid, route in ROUTES_BY_VALUE[:10]:
        if str(rid) not in claimed:
            c = route.get("color", "gray")
            if c not in ("gray", "locomotive"):
                needed.add(c)
    for i, card in enumerate(face_up):
        if card and card != "locomotive" and card in needed:
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


# ---------------------------------------------------------------------------
# Full game rollout
# ---------------------------------------------------------------------------

def run_rollout(state: dict, observer_pid: str, policy_fn) -> float:
    """
    Play state to terminal using policy_fn for all players.
    Returns normalised score differential for observer_pid.
    """
    for _ in range(600):  # safety cap (patient strategy needs more steps)
        if is_terminal(state):
            break

        phase = state.get("phase")
        if phase not in ("main", "final_round", "initial_tickets"):
            break

        cur = current_player(state)
        if not cur:
            break

        ps = state["player_states"].get(cur, {})

        # Resolve pending tickets: keep all (fast heuristic for rollouts)
        if ps.get("pending_tickets"):
            pend = ps["pending_tickets"]
            res  = logic.keep_drawn_tickets(state, cur, pend)
            if not res.get("ok") and pend:
                logic.keep_drawn_tickets(state, cur, pend[:1])
            continue

        if phase == "initial_tickets":
            # Shouldn't happen in mid-game rollouts; keep first 2 and move on
            pend = ps.get("pending_tickets", [])
            if pend:
                logic.keep_initial_tickets(state, cur, pend[:2])
            else:
                logic._advance_initial_tickets(state)
            continue

        action, params = policy_fn(state, cur)
        apply_move(state, cur, action, params)

    return terminal_score(state, observer_pid)
