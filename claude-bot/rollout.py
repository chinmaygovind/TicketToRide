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

import heapq
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
# Ticket-path policy — COMMITS to building each ticket's connecting path
#
# The plain heuristic grabs whichever single route scores highest (length +
# fuzzy ticket halo) and so claims scattered "relevant" routes that never join
# up — rollouts finish ~0 tickets, leaving ISMCTS blind to ticket value. This
# policy instead computes the actual shortest *route path* between an incomplete
# ticket's two cities (over routes still available to us, already-owned = free)
# and claims the next route ON that path, focusing the ticket closest to done.
# That builds connected networks that actually complete tickets.
# ---------------------------------------------------------------------------

def _available_adj(state: dict, pid: str) -> dict:
    """Adjacency over routes still usable by pid (owned cost 0, opponent = blocked)."""
    claimed   = state["claimed_routes"]
    n_players = len(state.get("turn_order", []))
    adj: dict = {}
    for rid, r in ROUTE_BY_ID.items():
        owner = claimed.get(str(rid))
        if owner is not None and owner != pid:
            continue                                   # opponent owns this side
        if owner is None and n_players <= 3:
            partner = DOUBLE_ROUTE_PARTNER.get(rid)    # double route, ≤3p: one side only
            if partner and str(partner) in claimed:
                continue
        cost = 0 if owner == pid else r["length"]
        adj.setdefault(r["city1"], []).append((cost, r["city2"], rid))
        adj.setdefault(r["city2"], []).append((cost, r["city1"], rid))
    return adj


def _path_route_ids(adj: dict, start: str, end: str):
    """Dijkstra over available routes; return route-id list of the cheapest path, or None."""
    if start == end:
        return []
    dist = {start: 0}
    prev = {}
    heap = [(0, start)]
    while heap:
        d, city = heapq.heappop(heap)
        if city == end:
            path, cur = [], end
            while cur in prev:
                pc, rid = prev[cur]
                path.append(rid)
                cur = pc
            return list(reversed(path))
        if d > dist.get(city, float("inf")):
            continue
        for cost, nbr, rid in adj.get(city, []):
            nd = d + cost
            if nd < dist.get(nbr, float("inf")):
                dist[nbr] = nd
                prev[nbr] = (city, rid)
                heapq.heappush(heap, (nd, nbr))
    return None


def ticket_path_policy(state: dict, pid: str) -> tuple:
    ps        = state["player_states"].get(pid, {})
    hand      = ps.get("hand", {})
    trains    = ps.get("trains", 45)
    tickets   = ps.get("tickets", [])
    draw_step = state.get("draw_step", 0)
    face_up   = state["face_up"]
    claimed   = state["claimed_routes"]
    n_players = len(state.get("turn_order", []))
    locos     = hand.get("locomotive", 0)
    sorted_hand = sorted(
        ((c, n) for c, n in hand.items() if c != "locomotive" and n > 0),
        key=lambda x: -x[1],
    )

    # Incomplete tickets -> their still-needed (unclaimed) routes, by remaining trains.
    adj = _available_adj(state, pid)
    targets = []   # (remaining_trains, points, [needed route ids])
    for tid in tickets:
        t = TICKET_BY_ID.get(tid)
        if not t or logic.is_path_connected(state, pid, t["city1"], t["city2"]):
            continue
        path = _path_route_ids(adj, t["city1"], t["city2"])
        if not path:
            continue                                   # currently unreachable — don't chase it
        need = [rid for rid in path if str(rid) not in claimed]
        remaining = sum(ROUTE_BY_ID[rid]["length"] for rid in need)
        targets.append((remaining, t.get("points", 0), need))

    if targets:
        # Focus the ticket closest to completion (then highest points).
        targets.sort(key=lambda x: (x[0], -x[1]))

        # 1) Claim a route on a target path if we can afford one (longest = most progress).
        if draw_step == 0:
            for _remaining, _pts, need in targets:
                claimable = []
                for rid in need:
                    route = ROUTE_BY_ID[rid]
                    cards = _can_claim_fast(hand, route, trains, n_players, claimed, pid,
                                            sorted_hand, locos)
                    if cards is not None:
                        claimable.append((route["length"], rid, cards))
                if claimable:
                    claimable.sort(reverse=True)
                    _ln, rid, cards = claimable[0]
                    return "claim", {"route_id": rid, "cards": cards}

        # 2) Can't build yet — draw cards toward the focus ticket's needed colors.
        need_colors: dict = {}
        for rid in targets[0][2]:
            col = ROUTE_BY_ID[rid].get("color", "gray")
            if col not in ("gray", "locomotive"):
                need_colors[col] = need_colors.get(col, 0) + ROUTE_BY_ID[rid]["length"]
        for i, card in enumerate(face_up):              # locomotives are universally useful
            if card == "locomotive" and draw_step == 0:
                return "draw_face_up", {"slot": i}
        for i, card in enumerate(face_up):
            if card and card != "locomotive" and card in need_colors:
                return "draw_face_up", {"slot": i}
        return "draw_blind", {}

    # No incomplete reachable tickets: maximize route points with the plain heuristic.
    return heuristic_policy(state, pid)


# ---------------------------------------------------------------------------
# Greedy policy — ticket-grabber; claims any route with ticket synergy
# ---------------------------------------------------------------------------

def greedy_policy(state: dict, pid: str) -> tuple:
    """Aggressive ticket completion; low threshold for claiming."""
    ps        = state["player_states"].get(pid, {})
    hand      = ps.get("hand", {})
    trains    = ps.get("trains", 45)
    tickets   = ps.get("tickets", [])
    draw_step = state.get("draw_step", 0)
    face_up   = state["face_up"]
    claimed   = state["claimed_routes"]
    n_players = len(state.get("turn_order", []))
    locos     = hand.get("locomotive", 0)

    sorted_hand = sorted(
        ((c, n) for c, n in hand.items() if c != "locomotive" and n > 0),
        key=lambda x: -x[1],
    )

    ticket_bonus: dict[int, float] = {}
    for tid in tickets:
        t = TICKET_BY_ID.get(tid)
        if not t or logic.is_path_connected(state, pid, t["city1"], t["city2"]):
            continue
        for rid, bonus in TICKET_ROUTE_RELEVANCE.get(tid, ()):
            if str(rid) not in claimed:
                ticket_bonus[rid] = ticket_bonus.get(rid, 0) + bonus

    # Claim any route with positive ticket bonus (no patience required)
    if draw_step == 0 and ticket_bonus:
        best_rid, best_cards, best_score = None, None, -1.0
        for _, rid, route in ROUTES_BY_VALUE:
            if rid not in ticket_bonus:
                continue
            cards = _can_claim_fast(hand, route, trains, n_players, claimed, pid,
                                    sorted_hand, locos)
            if cards is None:
                continue
            score = ticket_bonus[rid]
            if score > best_score:
                best_score = score; best_rid = rid; best_cards = cards
        if best_rid is not None:
            return "claim", {"route_id": best_rid, "cards": best_cards}

    # Fall back to heuristic for draws and non-ticket routes
    return heuristic_policy(state, pid)


# ---------------------------------------------------------------------------
# Blocking policy — prioritises routes adjacent to the opponent's network
# ---------------------------------------------------------------------------

def blocking_policy(state: dict, pid: str) -> tuple:
    """Claims routes that extend or complete the opponent's network first."""
    ps        = state["player_states"].get(pid, {})
    hand      = ps.get("hand", {})
    trains    = ps.get("trains", 45)
    draw_step = state.get("draw_step", 0)
    face_up   = state["face_up"]
    claimed   = state["claimed_routes"]
    n_players = len(state.get("turn_order", []))
    locos     = hand.get("locomotive", 0)

    sorted_hand = sorted(
        ((c, n) for c, n in hand.items() if c != "locomotive" and n > 0),
        key=lambda x: -x[1],
    )

    # Build opponent city set
    opp_cities: set = set()
    for rid_str, owner in claimed.items():
        if owner != pid:
            r = ROUTE_BY_ID.get(int(rid_str))
            if r:
                opp_cities.add(r["city1"]); opp_cities.add(r["city2"])

    if draw_step == 0 and opp_cities:
        best_rid, best_cards, best_score = None, None, -1.0
        for _, rid, route in ROUTES_BY_VALUE:
            cards = _can_claim_fast(hand, route, trains, n_players, claimed, pid,
                                    sorted_hand, locos)
            if cards is None:
                continue
            c1_opp = route["city1"] in opp_cities
            c2_opp = route["city2"] in opp_cities
            if c1_opp and c2_opp:
                block_bonus = 8.0
            elif c1_opp or c2_opp:
                block_bonus = 3.0
            else:
                continue   # only consider blocking moves
            ln = route["length"]
            score = block_bonus + ln  # base route value
            if score > best_score:
                best_score = score; best_rid = rid; best_cards = cards
        if best_rid is not None:
            return "claim", {"route_id": best_rid, "cards": best_cards}

    # Fall back to heuristic
    return heuristic_policy(state, pid)


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
