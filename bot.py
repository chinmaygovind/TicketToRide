"""
Multi-personality Ticket to Ride bots.

Personalities:
  fish-bot   — The Patient (fishy/kmit70): chains 15-pt routes, huge blind-draw bursts
  chin-bot   — The Collector (chinmay): grabs locos aggressively, draws tickets multiple times
  rocket-bot — Speed Demon: claims the first affordable route every turn, spreads fast
  ticket-bot — The Completionist: draws tickets constantly, completes every single one
  chaos-bot  — Random Goblin: chaotic but weighted, unpredictable and fun

All bots expose the same API:
  bot_turn(state, pid, personality) -> (action, params)
  bot_resolve_tunnel(state, pid, personality) -> (proceed, extra_cards)
  bot_keep_initial_tickets(state, pid, pending, personality) -> [ticket_ids]
"""

import heapq
import random
from collections import defaultdict

BOT_TYPES = [
    ("fish-bot",   "fish_bot"),
    ("chin-bot",   "chin_bot"),
    ("rocket-bot", "rocket_bot"),
    ("ticket-bot", "ticket_bot"),
    ("chaos-bot",  "chaos_bot"),
    ("claude-bot", "claude_bot"),
]

# route length -> priority weight for long-route-focused bots
_LONG_WEIGHT  = {1: 0.1, 2: 0.2, 3: 0.5, 4: 1.0, 5: 3.0, 6: 6.0, 7: 8.0, 8: 10.0}
# route length -> priority weight for balanced bots
_MIXED_WEIGHT = {1: 0.5, 2: 0.7, 3: 1.0, 4: 1.5, 5: 2.0, 6: 2.5, 7: 3.0, 8: 3.5}
# route length -> priority weight for speed bots (shorter = faster)
_FAST_WEIGHT  = {1: 3.0, 2: 2.5, 3: 2.0, 4: 1.5, 5: 1.0, 6: 0.8, 7: 0.6, 8: 0.5}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_map_data(state: dict):
    if state.get("map") == "europe":
        from game_data_europe import EUROPE_ROUTE_BY_ID, EUROPE_TICKET_BY_ID
        return EUROPE_ROUTE_BY_ID, EUROPE_TICKET_BY_ID
    from game_data_na import ROUTE_BY_ID, TICKET_BY_ID
    return ROUTE_BY_ID, TICKET_BY_ID


def _build_adj(state: dict, pid: str, route_by_id: dict) -> dict:
    claimed = state["claimed_routes"]
    adj = defaultdict(list)
    for route in route_by_id.values():
        rid = str(route["id"])
        owner = claimed.get(rid)
        if owner is not None and owner != pid:
            continue
        cost = route["length"]
        adj[route["city1"]].append((cost, route["city2"], route["id"]))
        adj[route["city2"]].append((cost, route["city1"], route["id"]))
    return adj


def _dijkstra(adj: dict, start: str, end: str):
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


def _can_claim(hand: dict, route: dict, trains_left: int):
    """Return card dict to claim route, or None."""
    length = route["length"]
    color  = route.get("color", "gray")
    ferry  = route.get("ferry", 0)
    locos  = hand.get("locomotive", 0)

    if length > trains_left:
        return None

    def _try(target, loco_budget):
        have = hand.get(target, 0)
        cu = min(have, length)
        lu = max(0, length - cu)
        if lu > loco_budget:
            return None
        r = {}
        if cu:
            r[target] = cu
        if lu:
            r["locomotive"] = lu
        return r if sum(r.values()) == length else None

    if ferry > 0:
        if locos < ferry:
            return None
        loco_budget = locos - ferry
        remaining   = length - ferry
        fc = route.get("color", "gray")
        candidates = (
            [fc] if fc != "gray"
            else sorted([c for c in hand if c != "locomotive" and hand[c] > 0],
                        key=lambda c: -hand[c])
        )
        for c in candidates:
            have = hand.get(c, 0)
            cu = min(have, remaining)
            lu = max(0, remaining - cu)
            if lu > loco_budget:
                continue
            r = {"locomotive": ferry + lu}
            if cu:
                r[c] = cu
            if sum(r.values()) == length:
                return r
        return None

    if color == "gray":
        non_loco = sorted([(c, n) for c, n in hand.items() if c != "locomotive" and n > 0],
                          key=lambda x: -x[1])
        for c, _ in non_loco:
            r = _try(c, locos)
            if r:
                return r
        return {"locomotive": length} if locos >= length else None
    else:
        r = _try(color, locos)
        if r:
            return r
        return {"locomotive": length} if locos >= length else None


def _score_routes_weighted(state, pid, route_by_id, ticket_by_id, length_weights,
                           ticket_weight=1.0, chain_bonus=0.0):
    """Generic route scorer with pluggable weights."""
    from game_logic import is_path_connected

    claimed  = state["claimed_routes"]
    my_owned = {rid for rid, owner in claimed.items() if owner == pid}
    adj_all  = _build_adj(state, pid, route_by_id)
    ps       = state["player_states"].get(pid, {})

    my_cities = set()
    for rid in my_owned:
        r = route_by_id.get(int(rid))
        if r:
            my_cities.add(r["city1"])
            my_cities.add(r["city2"])

    scores = defaultdict(float)

    for route in route_by_id.values():
        rid_str = str(route["id"])
        if rid_str in claimed:
            continue
        length = route["length"]
        base   = length_weights.get(length, 1.0) * length
        scores[route["id"]] += base
        if chain_bonus and (route["city1"] in my_cities or route["city2"] in my_cities):
            scores[route["id"]] += base * chain_bonus

    for tid in ps.get("tickets", []):
        ticket = ticket_by_id.get(tid)
        if not ticket or is_path_connected(state, pid, ticket["city1"], ticket["city2"]):
            continue
        path = _dijkstra(adj_all, ticket["city1"], ticket["city2"])
        if not path:
            continue
        unowned = [r for r in path if str(r) not in my_owned]
        if not unowned:
            continue
        total_trains = sum(route_by_id[r]["length"] for r in unowned)
        for rid in unowned:
            scores[rid] += ticket_weight * ticket["points"] / max(total_trains, 1)

    return scores


def _needed_colors_for_scores(state, pid, route_by_id, scored, top_n=5):
    """Pick card colors needed for highest-scored routes."""
    claimed = state["claimed_routes"]
    color_score = defaultdict(float)
    for rid, score in sorted(scored.items(), key=lambda x: -x[1])[:top_n]:
        if str(rid) in claimed:
            continue
        route = route_by_id.get(rid)
        if not route:
            continue
        c = route.get("color", "gray")
        if c not in ("gray", "locomotive"):
            color_score[c] += score
    if not color_score:
        return set()
    top = max(color_score.values())
    return {c for c, s in color_score.items() if s >= top * 0.4}


def _best_claimable(scored, route_by_id, claimed, hand, trains, top_n=None):
    """Return (route, cards) for the highest-scored affordable route, or None."""
    candidates = sorted(scored.items(), key=lambda x: -x[1])
    if top_n:
        candidates = candidates[:top_n]
    for rid, _ in candidates:
        route = route_by_id.get(rid)
        if not route or str(rid) in claimed:
            continue
        cards = _can_claim(hand, route, trains)
        if cards:
            return route, cards
    return None, None


def _has_dest_deck(state):
    return len(state.get("dest_deck", [])) >= 3


# ---------------------------------------------------------------------------
# fish-bot: The Patient
# Chains 15-point routes, draws blind in huge bursts, rarely draws tickets
# ---------------------------------------------------------------------------

def _fish_turn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed):
    scored = _score_routes_weighted(
        state, pid, route_by_id, ticket_by_id,
        length_weights=_LONG_WEIGHT,
        ticket_weight=0.5,
        chain_bonus=1.5,
    )

    if draw_step == 0:
        route, cards = _best_claimable(scored, route_by_id, claimed, hand, trains)
        if route:
            return "claim", {"route_id": route["id"], "cards": cards}

    if draw_step == 0:
        for i, card in enumerate(face_up):
            if card == "locomotive":
                return "draw_face_up", {"slot": i}

    needed = _needed_colors_for_scores(state, pid, route_by_id, scored)
    for i, card in enumerate(face_up):
        if card in needed:
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


# ---------------------------------------------------------------------------
# chin-bot: The Collector
# Grabs face-up locos aggressively, draws tickets 2-3x per game, balanced routes
# ---------------------------------------------------------------------------

def _chin_turn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed):
    from game_logic import is_path_connected
    ps = state["player_states"].get(pid, {})
    tickets = ps.get("tickets", [])
    uncompleted = [
        t for tid in tickets
        if (t := ticket_by_id.get(tid))
        and not is_path_connected(state, pid, t["city1"], t["city2"])
    ]

    scored = _score_routes_weighted(
        state, pid, route_by_id, ticket_by_id,
        length_weights=_MIXED_WEIGHT,
        ticket_weight=2.5,
        chain_bonus=0.8,
    )

    if draw_step == 0:
        route, cards = _best_claimable(scored, route_by_id, claimed, hand, trains)
        if route:
            return "claim", {"route_id": route["id"], "cards": cards}

    # Draw more tickets if ≤ 1 uncompleted (chinmay draws tickets frequently)
    if draw_step == 0 and state.get("phase") == "main" and len(uncompleted) <= 1 and _has_dest_deck(state):
        return "draw_tickets", {}

    # Always grab face-up loco
    if draw_step == 0:
        for i, card in enumerate(face_up):
            if card == "locomotive":
                return "draw_face_up", {"slot": i}

    needed = _needed_colors_for_scores(state, pid, route_by_id, scored)
    for i, card in enumerate(face_up):
        if card in needed:
            return "draw_face_up", {"slot": i}

    # chin-bot also picks up good-looking face-up cards of any color
    hand_counts = {c: n for c, n in hand.items() if c != "loco"}
    for i, card in enumerate(face_up):
        if card != "loco" and hand.get(card, 0) >= 2:
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


# ---------------------------------------------------------------------------
# rocket-bot: Speed Demon
# Claims the first affordable route every turn regardless of length
# Spreads across the map fast, locks up territory early
# ---------------------------------------------------------------------------

def _rocket_turn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed):
    scored = _score_routes_weighted(
        state, pid, route_by_id, ticket_by_id,
        length_weights=_FAST_WEIGHT,
        ticket_weight=3.0,
        chain_bonus=0.3,
    )

    if draw_step == 0:
        route, cards = _best_claimable(scored, route_by_id, claimed, hand, trains)
        if route:
            return "claim", {"route_id": route["id"], "cards": cards}

    if draw_step == 0:
        for i, card in enumerate(face_up):
            if card == "locomotive":
                return "draw_face_up", {"slot": i}

    needed = _needed_colors_for_scores(state, pid, route_by_id, scored)
    for i, card in enumerate(face_up):
        if card in needed:
            return "draw_face_up", {"slot": i}

    # Speed demon takes whatever face-up card looks useful
    for i, card in enumerate(face_up):
        if card != "locomotive":
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


# ---------------------------------------------------------------------------
# ticket-bot: The Completionist
# Draws destination tickets aggressively, optimizes for completing every ticket
# ---------------------------------------------------------------------------

def _ticket_turn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed):
    from game_logic import is_path_connected
    ps = state["player_states"].get(pid, {})
    tickets = ps.get("tickets", [])
    uncompleted = [
        t for tid in tickets
        if (t := ticket_by_id.get(tid))
        and not is_path_connected(state, pid, t["city1"], t["city2"])
    ]

    # Ticket-first scoring: weight tickets very heavily
    scored = _score_routes_weighted(
        state, pid, route_by_id, ticket_by_id,
        length_weights=_MIXED_WEIGHT,
        ticket_weight=5.0,
        chain_bonus=1.0,
    )

    if draw_step == 0:
        route, cards = _best_claimable(scored, route_by_id, claimed, hand, trains)
        if route:
            return "claim", {"route_id": route["id"], "cards": cards}

    # Draw tickets whenever possible (completionist always wants more tickets)
    if draw_step == 0 and state.get("phase") == "main" and len(uncompleted) <= 2 and _has_dest_deck(state):
        return "draw_tickets", {}

    if draw_step == 0:
        for i, card in enumerate(face_up):
            if card == "locomotive":
                return "draw_face_up", {"slot": i}

    needed = _needed_colors_for_scores(state, pid, route_by_id, scored)
    for i, card in enumerate(face_up):
        if card in needed:
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


# ---------------------------------------------------------------------------
# chaos-bot: Random Goblin
# Picks randomly from the top few options — chaotic but not completely dumb
# ---------------------------------------------------------------------------

def _chaos_turn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed):
    scored = _score_routes_weighted(
        state, pid, route_by_id, ticket_by_id,
        length_weights=_MIXED_WEIGHT,
        ticket_weight=1.5,
        chain_bonus=0.5,
    )

    if draw_step == 0:
        # Randomly picks from top 5 (not always the best)
        candidates = sorted(scored.items(), key=lambda x: -x[1])[:5]
        random.shuffle(candidates)
        for rid, _ in candidates:
            route = route_by_id.get(rid)
            if not route or str(rid) in claimed:
                continue
            cards = _can_claim(hand, route, trains)
            if cards:
                return "claim", {"route_id": route["id"], "cards": cards}

    # Sometimes draws tickets randomly
    if draw_step == 0 and state.get("phase") == "main" and random.random() < 0.08 and _has_dest_deck(state):
        return "draw_tickets", {}

    # Randomly picks a face-up card (sometimes ignores loco)
    if draw_step == 0 or True:
        available = [(i, c) for i, c in enumerate(face_up)]
        if draw_step == 0:
            available = [(i, c) for i, c in available if c != "locomotive" or random.random() < 0.8]
        else:
            available = [(i, c) for i, c in available if c != "locomotive"]
        if available and random.random() < 0.6:
            i, _ = random.choice(available)
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# claude-bot: The Learned Bot
# Uses weights tuned by train_claude_bot.py. Falls back to fish_bot defaults.
# ---------------------------------------------------------------------------

import os as _os
_WEIGHTS_FILE = _os.path.join(_os.path.dirname(__file__), "claude_bot_weights.json")
_claude_weights = None

def _load_claude_weights():
    global _claude_weights
    if _claude_weights is None:
        if _os.path.exists(_WEIGHTS_FILE):
            import json as _json
            with open(_WEIGHTS_FILE) as f:
                _claude_weights = _json.load(f)
        else:
            # Fallback defaults (between fish and chin style)
            _claude_weights = {
                "length_weights": {"1":0.3,"2":0.4,"3":0.8,"4":1.2,"5":2.2,"6":4.0},
                "ticket_weight": 1.8,
                "chain_bonus": 1.0,
                "loco_slot_bias": 0.7,
                "ticket_draw_threshold": 1,
            }
    return _claude_weights


def _claude_turn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed):
    from game_logic import is_path_connected

    w = _load_claude_weights()
    lw = {int(k): v for k, v in w["length_weights"].items()}
    tw = w.get("ticket_weight", 1.8)
    cb = w.get("chain_bonus", 1.0)
    loco_bias = w.get("loco_slot_bias", 0.7)

    scored = _score_routes_weighted(
        state, pid, route_by_id, ticket_by_id,
        length_weights=lw, ticket_weight=tw, chain_bonus=cb,
    )

    if draw_step == 0:
        for rid, _ in sorted(scored.items(), key=lambda x: -x[1]):
            route = route_by_id.get(rid)
            if not route or str(rid) in claimed:
                continue
            cards = _can_claim(hand, route, trains)
            if cards:
                return "claim", {"route_id": rid, "cards": cards}

    if draw_step == 0 and state.get("phase") == "main":
        ps = state["player_states"].get(pid, {})
        uncompleted = sum(
            1 for tid in ps.get("tickets", [])
            if (t := ticket_by_id.get(tid)) and
            not is_path_connected(state, pid, t["city1"], t["city2"])
        )
        threshold = int(w.get("ticket_draw_threshold", 1))
        if uncompleted <= threshold and len(state.get("dest_deck", [])) >= 3:
            return "draw_tickets", {}

    if draw_step == 0 and random.random() < loco_bias:
        for i, card in enumerate(face_up):
            if card == "locomotive":
                return "draw_face_up", {"slot": i}

    needed = _needed_colors_for_scores(state, pid, route_by_id, scored)
    for i, card in enumerate(face_up):
        if card in needed:
            return "draw_face_up", {"slot": i}

    return "draw_blind", {}


_DISPATCH = {
    "fish_bot":   _fish_turn,
    "chin_bot":   _chin_turn,
    "rocket_bot": _rocket_turn,
    "ticket_bot": _ticket_turn,
    "chaos_bot":  _chaos_turn,
    "claude_bot": _claude_turn,
}


def _extract_personality(session_key: str) -> str:
    """Extract personality slug from session_key like 'bot_fish_bot_<uuid>'."""
    for _, slug in BOT_TYPES:
        if f"bot_{slug}_" in session_key:
            return slug
    return "fish_bot"  # default


def bot_turn(state: dict, pid: str, personality: str = "fish_bot"):
    """
    Return (action, params).
    actions: 'claim', 'draw_face_up', 'draw_blind', 'draw_tickets'
    """
    route_by_id, ticket_by_id = _get_map_data(state)
    ps        = state["player_states"].get(pid, {})
    hand      = dict(ps.get("hand", {}))
    trains    = ps.get("trains", 45)
    draw_step = state.get("draw_step", 0)
    face_up   = state["face_up"]
    claimed   = state["claimed_routes"]

    # Emergency: if hand is very large (all cards hoarded), always try to claim
    # any available route on the first draw step to prevent card-hoarding deadlock.
    if draw_step == 0 and sum(hand.values()) > 20:
        for rid, route in route_by_id.items():
            if str(rid) not in claimed:
                cards = _can_claim(hand, route, trains)
                if cards:
                    return "claim", {"route_id": rid, "cards": cards}

    fn = _DISPATCH.get(personality, _fish_turn)
    return fn(state, pid, route_by_id, ticket_by_id, hand, trains, draw_step, face_up, claimed)


def bot_resolve_tunnel(state: dict, pid: str, personality: str = "fish_bot"):
    """Proceed if we can afford extra cards."""
    pt = state.get("pending_tunnel", {})
    if not pt:
        return False, {}

    extra_cost  = pt.get("extra_cost", 0)
    extra_color = pt.get("extra_color")

    if extra_cost == 0:
        return True, {}

    ps   = state["player_states"].get(pid, {})
    hand = dict(ps.get("hand", {}))

    # chaos-bot randomly aborts tunnels ~30% of the time even if it can pay
    if personality == "chaos_bot" and random.random() < 0.3:
        return False, {}

    if not extra_color or extra_color == "locomotive":
        if hand.get("locomotive", 0) >= extra_cost:
            return True, {"locomotive": extra_cost}
        return False, {}

    have_color = hand.get(extra_color, 0)
    have_loco  = hand.get("locomotive", 0)
    cu = min(have_color, extra_cost)
    lu = extra_cost - cu
    if lu <= have_loco:
        cards = {}
        if cu:
            cards[extra_color] = cu
        if lu:
            cards["locomotive"] = lu
        return True, cards
    return False, {}


def bot_keep_initial_tickets(state: dict, pid: str, pending: list,
                             personality: str = "fish_bot") -> list:
    """Keep tickets based on personality."""
    route_by_id, ticket_by_id = _get_map_data(state)
    adj = _build_adj(state, pid, route_by_id)

    keepable, blocked = [], []
    for tid in pending:
        t = ticket_by_id.get(tid)
        if t and _dijkstra(adj, t["city1"], t["city2"]) is not None:
            keepable.append((t.get("points", 0), tid))
        else:
            blocked.append(tid)

    if personality == "ticket_bot":
        # Completionist keeps ALL reachable tickets
        keep = [tid for _, tid in keepable]
    elif personality == "chaos_bot":
        # Random goblin shuffles and picks randomly
        random.shuffle(keepable)
        keep = [tid for _, tid in keepable]
    elif personality == "fish_bot":
        # Fish prefers highest-value (longest journey) tickets
        keepable.sort(reverse=True)
        keep = [tid for _, tid in keepable]
    else:
        # chin-bot and rocket-bot keep all reachable
        keepable.sort(reverse=True)
        keep = [tid for _, tid in keepable]

    for tid in blocked:
        if len(keep) >= 2:
            break
        keep.append(tid)

    return keep
