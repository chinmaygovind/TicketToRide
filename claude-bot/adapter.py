"""
Adapter layer over game_logic.py for ISMCTS.

All functions take the raw state dict and return pure-Python values.
No state is stored here — this is a stateless interface over the simulator.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game_logic as logic
from game_data_na import ROUTE_BY_ID, DOUBLE_ROUTE_GROUPS

# ---------------------------------------------------------------------------
# Legal move generation
# ---------------------------------------------------------------------------

def get_legal_moves(state: dict, pid: str) -> list:
    """
    Return list of (action, params) for pid in the current state.
    draw_tickets is excluded — handled by a separate heuristic layer.
    At draw_step 1 only draw actions are returned (no claims).
    """
    phase = state.get("phase")
    if phase not in ("main", "final_round"):
        return []
    if state.get("current_player_id") != pid:
        return []

    ps = state["player_states"].get(pid, {})
    if ps.get("pending_tickets"):
        return []  # resolved externally

    hand      = ps.get("hand", {})
    trains    = ps.get("trains", 45)
    claimed   = state["claimed_routes"]
    draw_step = state.get("draw_step", 0)
    face_up   = state["face_up"]
    n_players = len(state.get("turn_order", []))

    moves = []

    if draw_step == 0:
        for route_id, route in ROUTE_BY_ID.items():
            cards = _can_claim(hand, route, trains, n_players, claimed, pid)
            if cards is not None:
                moves.append(("claim", {"route_id": route_id, "cards": cards}))

    for i, card in enumerate(face_up):
        if card is None:
            continue
        if card == "locomotive" and draw_step == 1:
            continue
        moves.append(("draw_face_up", {"slot": i}))

    if state.get("deck") or state.get("discard"):
        moves.append(("draw_blind", {}))

    return moves


def _can_claim(hand: dict, route: dict, trains: int,
               n_players: int, claimed: dict, pid: str):
    """Return card dict to claim route, or None. Greedy gray-route payment."""
    rid = str(route["id"])
    if rid in claimed:
        return None
    length = route["length"]
    if length > trains:
        return None

    dg = route.get("double_group")
    if dg:
        for oid in DOUBLE_ROUTE_GROUPS.get(dg, []):
            if oid == route["id"]:
                continue
            oid_str = str(oid)
            if oid_str in claimed:
                if n_players <= 3:
                    return None
                if claimed[oid_str] == pid:
                    return None

    color = route.get("color", "gray")
    locos = hand.get("locomotive", 0)

    def _try(target):
        have  = hand.get(target, 0)
        use_c = min(have, length)
        use_l = length - use_c
        if use_l > locos:
            return None
        cards = {}
        if use_c: cards[target]       = use_c
        if use_l: cards["locomotive"] = use_l
        return cards

    if color == "gray":
        candidates = sorted(
            [(c, n) for c, n in hand.items() if c != "locomotive" and n > 0],
            key=lambda x: -x[1],
        )
        for c, _ in candidates:
            r = _try(c)
            if r is not None:
                return r
        return {"locomotive": length} if locos >= length else None
    else:
        r = _try(color)
        if r is not None:
            return r
        return {"locomotive": length} if locos >= length else None


# ---------------------------------------------------------------------------
# Apply a move (mutates state in place)
# ---------------------------------------------------------------------------

def apply_move(state: dict, pid: str, action: str, params: dict) -> None:
    if action == "claim":
        res = logic.claim_route(state, pid, params["route_id"], params["cards"])
        if not res.get("ok"):
            _blind_fallback(state, pid)
    elif action == "draw_face_up":
        res = logic.draw_face_up(state, pid, params.get("slot", 0))
        if not res.get("ok"):
            _blind_fallback(state, pid)
    elif action == "draw_blind":
        res = logic.draw_blind(state, pid)
        if not res.get("ok"):
            logic._next_turn(state)
    elif action == "draw_tickets":
        res = logic.draw_destination_tickets(state, pid)
        if res.get("ok"):
            ps = state["player_states"][pid]
            pend = ps.get("pending_tickets", [])
            if pend:
                logic.keep_drawn_tickets(state, pid, pend)
        else:
            _blind_fallback(state, pid)


def _blind_fallback(state: dict, pid: str):
    res = logic.draw_blind(state, pid)
    if not res.get("ok"):
        logic._next_turn(state)


# ---------------------------------------------------------------------------
# Terminal checks and scoring
# ---------------------------------------------------------------------------

def is_terminal(state: dict) -> bool:
    return state.get("phase") == "ended"


def terminal_score(state: dict, pid: str) -> float:
    """Score differential: my_total - best_opponent_total, normalised to ~[-1,1]."""
    scores = state.get("scores", {})
    if not scores:
        return 0.0
    mine = scores.get(pid, {}).get("total", 0)
    opp  = max((scores[op].get("total", 0) for op in scores if op != pid), default=0)
    return (mine - opp) / 100.0


def current_player(state: dict) -> str:
    return state.get("current_player_id", "")
