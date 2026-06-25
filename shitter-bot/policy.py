"""
shitter-bot — the sophisticated Ticket to Ride brain.

A self-contained, instant (no tree search) policy that plays the way a strong
human does. Public entry: shitter_policy(state, pid) -> (action, params).

Design goals (all validated by benchmark vs the other bots):
  1. Know which tickets it still owes and PRIORITISE completing them, closest
     ticket first, by claiming the next route on that ticket's path.
  2. Prefer to complete tickets with FEWER, LONGER routes — a slightly longer
     path made of long routes scores more route points and feeds longest-path
     (the `_HOP_PENALTY` term in path-finding biases toward long segments).
  3. Grow ONE mostly-continuous network so it reliably earns the longest-path
     bonus (continuity bonus for routes that extend / join its own track).
  4. Model opponents from their claimed routes (which clusters they are linking)
     and block a route that bridges their network — but only once its own
     tickets are done or the block is convenient, so it never wastes trains.

While it still owes tickets it only ever claims routes on a ticket path; long
value routes, longest-path extension and speculative blocking unlock once every
ticket is complete (or unreachable). That ordering is what keeps completion high.
"""
import os
import sys
import heapq

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import game_logic as logic
from game_data_na import (ROUTE_BY_ID, ROUTE_SCORING, TICKET_BY_ID,
                          DOUBLE_ROUTE_GROUPS)

# Routes pre-sorted by point value (high first) for claim scanning.
ROUTES_BY_VALUE = sorted(
    [(ROUTE_SCORING.get(r["length"], 1), rid, r) for rid, r in ROUTE_BY_ID.items()],
    reverse=True,
)

# route_id -> partner route id (the other side of a double route).
DOUBLE_ROUTE_PARTNER = {}
for _rid, _r in ROUTE_BY_ID.items():
    _dg = _r.get("double_group")
    if _dg:
        for _oid in DOUBLE_ROUTE_GROUPS.get(_dg, []):
            if _oid != _rid:
                DOUBLE_ROUTE_PARTNER[_rid] = _oid
                break

_PTS = ROUTE_SCORING          # length -> route points {1:1,2:2,3:4,4:7,5:10,6:15}

# Per-route penalty added during ticket path-finding. It makes a path of a few
# LONG routes cheaper than many short ones for the same cities, so the bot takes
# a slightly longer route built from long segments (more route score + longest
# path) rather than the strict minimum-train path. Kept small so it never causes
# a wasteful detour.
_HOP_PENALTY = 0.8

# Draw extra destination tickets once the network is LARGE and current tickets
# are done. DB lesson: humans who end with 4-6 tickets score ~115 vs ~90 for 3,
# because with a big network newly-drawn tickets are often already connected (free
# points). But drawing costs a turn, so we only do it as a FALLBACK — when there's
# no worthwhile route to claim anyway (we'd otherwise just draw cards) and the
# network is big enough that a drawn ticket is very likely already connected/cheap.
# The EV ticket chooser (bot.py) then keeps only the finishable ones.
_DRAW_TICKET_MIN_TRAINS = 15
_DRAW_TICKET_MIN_CITIES = 11


# ---------------------------------------------------------------------------
# Claim feasibility
# ---------------------------------------------------------------------------

def _can_claim_fast(hand, route, trains, n_players, claimed, pid,
                    sorted_hand=None, locos=None):
    """Return the card dict to claim `route`, or None if not affordable/legal."""
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
        if cu:
            r[c] = cu
        if lu:
            r["locomotive"] = lu
        return r

    if color == "gray":
        sh = sorted_hand if sorted_hand is not None else sorted(
            ((c, n) for c, n in hand.items() if c != "locomotive" and n > 0),
            key=lambda x: -x[1],
        )
        for c, _ in sh:
            r = _try(c)
            if r is not None:
                return r
        return {"locomotive": length} if locos >= length else None
    r = _try(color)
    if r is not None:
        return r
    return {"locomotive": length} if locos >= length else None


# ---------------------------------------------------------------------------
# Graph helpers
# ---------------------------------------------------------------------------

def _available_adj(state, pid):
    """Adjacency over routes still usable by pid (owned cost 0, opponent = blocked)."""
    claimed   = state["claimed_routes"]
    n_players = len(state.get("turn_order", []))
    adj = {}
    for rid, r in ROUTE_BY_ID.items():
        owner = claimed.get(str(rid))
        if owner is not None and owner != pid:
            continue
        if owner is None and n_players <= 3:
            partner = DOUBLE_ROUTE_PARTNER.get(rid)
            if partner and str(partner) in claimed:
                continue
        cost = 0.0 if owner == pid else r["length"]
        adj.setdefault(r["city1"], []).append((cost, r["city2"], rid))
        adj.setdefault(r["city2"], []).append((cost, r["city1"], rid))
    return adj


def _path_route_ids(adj, start, end):
    """Dijkstra over available routes, biased toward fewer/longer segments via
    _HOP_PENALTY. Returns the route-id list of the chosen path, or None."""
    if start == end:
        return []
    dist = {start: 0.0}
    prev = {}
    heap = [(0.0, start)]
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
            nd = d + cost + (_HOP_PENALTY if cost > 0 else 0.0)
            if nd < dist.get(nbr, float("inf")):
                dist[nbr] = nd
                prev[nbr] = (city, rid)
                heapq.heappush(heap, (nd, nbr))
    return None


def _my_cities(claimed, pid):
    cities = set()
    for rid, owner in claimed.items():
        if owner == pid:
            r = ROUTE_BY_ID.get(int(rid))
            if r:
                cities.add(r["city1"]); cities.add(r["city2"])
    return cities


def _component_root(edges):
    """Union-find over (city1, city2) edges -> {city: root}."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    for a, b in edges:
        parent[find(a)] = find(b)
    return {c: find(c) for c in parent}


def _estimate_opponent_needs(state, pid):
    """Routes that would link an opponent's separate clusters (they likely want
    these to finish tickets). Returns {route_id: block_value}."""
    claimed = state["claimed_routes"]
    need = {}
    for opp in state["player_states"]:
        if opp == pid:
            continue
        edges = [(ROUTE_BY_ID[int(rid)]["city1"], ROUTE_BY_ID[int(rid)]["city2"])
                 for rid, o in claimed.items() if o == opp and int(rid) in ROUTE_BY_ID]
        if not edges:
            continue
        root = _component_root(edges)
        for rid, route in ROUTE_BY_ID.items():
            if str(rid) in claimed:
                continue
            r1 = root.get(route["city1"]); r2 = root.get(route["city2"])
            if r1 and r2 and r1 != r2:                 # bridges two of their clusters
                need[rid] = need.get(rid, 0) + 6 + route["length"]
            elif r1 or r2:                             # merely extends their network
                need[rid] = need.get(rid, 0) + 2
    return need


def _draw_toward(face_up, focus_routes, draw_step):
    """Draw a locomotive or a colour the focus routes need; else draw blind."""
    need_colors = {}
    for rid in focus_routes:
        col = ROUTE_BY_ID[rid].get("color", "gray")
        if col not in ("gray", "locomotive"):
            need_colors[col] = need_colors.get(col, 0) + 1
    if draw_step == 0:
        for i, card in enumerate(face_up):
            if card == "locomotive":
                return "draw_face_up", {"slot": i}
    for i, card in enumerate(face_up):
        if card and card != "locomotive" and card in need_colors:
            return "draw_face_up", {"slot": i}
    return "draw_blind", {}


# ---------------------------------------------------------------------------
# Public policy
# ---------------------------------------------------------------------------

def shitter_policy(state, pid):
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

    my_cities = _my_cities(claimed, pid)
    adj       = _available_adj(state, pid)

    # Incomplete reachable tickets -> their (long-route-biased) path.
    targets = []   # (remaining_trains, points, set(needed route ids))
    for tid in tickets:
        t = TICKET_BY_ID.get(tid)
        if not t or logic.is_path_connected(state, pid, t["city1"], t["city2"]):
            continue
        path = _path_route_ids(adj, t["city1"], t["city2"])
        if not path:
            continue
        need = [rid for rid in path if str(rid) not in claimed]
        targets.append((sum(ROUTE_BY_ID[r]["length"] for r in need),
                        t.get("points", 0), set(need)))
    targets.sort(key=lambda x: (x[0], -x[1]))

    plan_routes = set()
    for _rem, _pts, need in targets:
        plan_routes |= need
    closest  = targets[0][2] if targets else set()
    opp_need = _estimate_opponent_needs(state, pid)
    owing    = bool(targets)

    if draw_step == 0:
        best_rid, best_cards, best_score = None, None, -1.0
        for _val, rid, route in ROUTES_BY_VALUE:
            if str(rid) in claimed:
                continue
            on_plan = rid in plan_routes
            if owing and not on_plan:
                continue                                 # reserve trains for tickets
            cards = _can_claim_fast(hand, route, trains, n_players, claimed, pid,
                                    sorted_hand, locos)
            if cards is None:
                continue
            length = route["length"]
            score  = 0.0

            if on_plan:                                  # ticket completion dominates
                score += 50.0
                if rid in closest:
                    score += 15.0                        # focus the closest ticket

            score += _PTS.get(length, 1) + 0.8 * length  # route points + longest-path nudge

            c1in = route["city1"] in my_cities
            c2in = route["city2"] in my_cities
            if c1in or c2in:
                score += 5.0                             # continuity: extend the network
            if c1in and c2in:
                score += 3.0                             # join two of my own clusters

            ob = opp_need.get(rid, 0)
            if ob > 0 and (on_plan or length >= 4 or trains > 22):
                score += min(ob, 8.0)                    # convenient, worthwhile block

            if score > best_score:
                best_score, best_rid, best_cards = score, rid, cards

        # Owing tickets: claim any plan route. Otherwise require a worthwhile route,
        # but drop the bar as trains dwindle so we USE our trains instead of leaving
        # them unused (DB: winners end with ~4 trains left, losers ~18 — unused
        # trains are wasted route points + longest-path track).
        if owing:
            threshold = 0.0
        elif trains <= 12:
            threshold = 1.0          # end-game: grab almost anything affordable
        else:
            threshold = 4.0          # early: don't waste good cards on junk routes
        if best_rid is not None and best_score >= threshold:
            return "claim", {"route_id": best_rid, "cards": best_cards}

        # No worthwhile route to claim: if our network is large and tickets are
        # done, draw new tickets (likely already-connected free points) instead
        # of just drawing cards. This is free tempo — we weren't going to build.
        if (not owing
                and trains >= _DRAW_TICKET_MIN_TRAINS
                and len(my_cities) >= _DRAW_TICKET_MIN_CITIES
                and len(state.get("dest_deck", [])) >= 3):
            return "draw_tickets", {}

    return _draw_toward(face_up, closest or plan_routes, draw_step)
