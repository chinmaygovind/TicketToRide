"""Bot chat reactions.

Gives bots a personality in the in-game chat: they react to game events with
random lines from a phrase bank. Phrase banks are grouped by category; triggers
map onto a bank. app.py detects the events and calls `pick(trigger)` to get a line
(or None when that trigger's bank is empty -> stays silent).

Detection helpers (completed_count / all_tickets_complete / route_on_bot_plan) are
here so app.py stays thin; they only read state, never mutate it.
"""
import random
import heapq

import game_logic as logic


# ---------------------------------------------------------------------------
# Phrase banks  (edit freely — empty list => that trigger stays silent)
# ---------------------------------------------------------------------------

_SALT = [
    "noooooo", "fuck", "idiot", "shitter", "fuck you", "damnit",
    "NO NO NO NO NO I THOUGHT WE WERE HAVING A NICE TIME", "aw man",
]
_HYPE = ["yipeeee"]

# Flex / banter — PROPOSED, pending user approval. Cocky salty train robot vibe.
_OPENING = [
    "hey whats up", "lets ride", "buckle up shitters", "choo choo motherfuckers",
    "i was trained on your games btw", "go easy on me 😇",
]
_OPP_DRAWS_TICKETS = ["thats not gonna help you", "i see you", "ah hell nah"]
_DREW_LOCO = ["gimme that"]
_IDLE = [
    "this is my game", "any day now", "im built different",
    "you cant stop the train", "tick tock",
    "im literally a robot and im beating you",
    "nerd",   # technoblade
]

PHRASES = {
    # salt (something went against the bot)
    "route_blocked":        _SALT,
    "double_snipe":         _SALT,
    "forced_bad_ticket":    _SALT,
    "final_round_panic":    _SALT,
    # hype (something went its way)
    "ticket_complete":      _HYPE,
    "all_tickets_complete": _HYPE,
    "big_route":            _HYPE,
    # flex / banter
    "opening":              _OPENING,
    "opp_draws_tickets":    _OPP_DRAWS_TICKETS,
    "drew_loco":            _DREW_LOCO,
    "idle":                 _IDLE,
    # endgame
    "win":                  ["gg ez", "gg", "youre a shitter"],
    "lose":                 ["gg"],
    "longest_path":         ["longest. choo choo"],
}


def pick(trigger):
    """Random line for `trigger`, or None if its bank is empty/unknown."""
    opts = PHRASES.get(trigger)
    return random.choice(opts) if opts else None


# ---------------------------------------------------------------------------
# Event detection helpers (read-only)
# ---------------------------------------------------------------------------

def _map(state):
    return logic._map_data(state.get("map", "usa"))   # route_by_id, ticket_by_id, scoring, doubles


def completed_count(state, pid):
    """How many of pid's kept tickets are currently connected."""
    _, ticket_by_id, _, _ = _map(state)
    ps = state["player_states"].get(pid, {})
    n = 0
    for tid in ps.get("tickets", []):
        t = ticket_by_id.get(tid)
        if t and logic.is_path_connected(state, pid, t["city1"], t["city2"]):
            n += 1
    return n


def all_tickets_complete(state, pid):
    ps = state["player_states"].get(pid, {})
    held = ps.get("tickets", [])
    return bool(held) and completed_count(state, pid) == len(held)


def route_length(state, route_id):
    route_by_id, _, _, _ = _map(state)
    r = route_by_id.get(int(route_id))
    return r["length"] if r else 0


def route_on_bot_plan(state, pid, claimed_rid):
    """True if `claimed_rid` (just taken by an opponent) was on pid's cheapest
    available path for an UNFINISHED ticket — i.e. the opponent blocked it.

    Builds a graph treating the just-claimed route as if still available, then
    checks each incomplete ticket's shortest path for that route id.
    """
    try:
        claimed_rid = int(claimed_rid)
        route_by_id, ticket_by_id, _, _ = _map(state)
        claimed = state["claimed_routes"]
        adj = {}
        for rid, r in route_by_id.items():
            owner = claimed.get(str(rid))
            # opponent-owned routes are blocked, EXCEPT the one we're testing,
            # which we pretend is still free so we can see if the bot wanted it.
            if owner is not None and owner != pid and rid != claimed_rid:
                continue
            cost = 0.0 if owner == pid else float(r["length"])
            adj.setdefault(r["city1"], []).append((cost, r["city2"], rid))
            adj.setdefault(r["city2"], []).append((cost, r["city1"], rid))

        ps = state["player_states"].get(pid, {})
        for tid in ps.get("tickets", []):
            t = ticket_by_id.get(tid)
            if not t or logic.is_path_connected(state, pid, t["city1"], t["city2"]):
                continue
            path = _shortest_path_rids(adj, t["city1"], t["city2"])
            if path and claimed_rid in path:
                return True
    except Exception:
        pass
    return False


def _shortest_path_rids(adj, start, end):
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
            nd = d + cost
            if nd < dist.get(nbr, float("inf")):
                dist[nbr] = nd
                prev[nbr] = (city, rid)
                heapq.heappush(heap, (nd, nbr))
    return None
