"""
Static graph pre-computation — loaded once at import time.

Provides:
  static_cost(city1, city2) -> int   min cards to connect, ignoring claimed routes
  ROUTES_BY_VALUE             list[(score, route_id, route_dict)] high→low

Both are used by fast_heuristic_policy in rollout.py to avoid
per-call Dijkstra and route sorting.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from game_data_na import ROUTE_BY_ID, ROUTE_SCORING, DOUBLE_ROUTE_GROUPS

# ---------------------------------------------------------------------------
# All-pairs shortest paths via Floyd-Warshall on the static map
# ---------------------------------------------------------------------------

_cities = sorted({c for r in ROUTE_BY_ID.values()
                  for c in (r["city1"], r["city2"])})
_N  = len(_cities)
_CI = {c: i for i, c in enumerate(_cities)}
_INF = float("inf")

# dist[i][j] = min number of train cards to connect city i to city j
_dist = [[_INF] * _N for _ in range(_N)]
for i in range(_N):
    _dist[i][i] = 0

for route in ROUTE_BY_ID.values():
    i = _CI[route["city1"]]
    j = _CI[route["city2"]]
    cost = route["length"]
    if cost < _dist[i][j]:
        _dist[i][j] = cost
        _dist[j][i] = cost

for k in range(_N):
    dk = _dist[k]
    for i in range(_N):
        di = _dist[i]
        dik = di[k]
        if dik == _INF:
            continue
        for j in range(_N):
            nd = dik + dk[j]
            if nd < di[j]:
                di[j] = nd


def static_cost(city1: str, city2: str) -> int:
    """Min train cards to connect two cities on the uncontested static map."""
    i = _CI.get(city1)
    j = _CI.get(city2)
    if i is None or j is None:
        return 20
    d = _dist[i][j]
    return d if d != _INF else 20


# ---------------------------------------------------------------------------
# Routes pre-sorted by point value (high first) — for fast rollout claiming
# ---------------------------------------------------------------------------

ROUTES_BY_VALUE = sorted(
    [(ROUTE_SCORING.get(r["length"], 1), r["id"], r)
     for r in ROUTE_BY_ID.values()],
    reverse=True,
)


# ---------------------------------------------------------------------------
# Double-route partner map: route_id -> partner_route_id (O(1) lookup)
# ---------------------------------------------------------------------------

DOUBLE_ROUTE_PARTNER: dict = {}
for _rid, _r in ROUTE_BY_ID.items():
    dg = _r.get("double_group")
    if dg:
        for _oid in DOUBLE_ROUTE_GROUPS.get(dg, []):
            if _oid != _rid:
                DOUBLE_ROUTE_PARTNER[_rid] = _oid
                break


# ---------------------------------------------------------------------------
# Per-ticket route relevance map — precomputed at import time
#
# TICKET_ROUTE_RELEVANCE[ticket_id] = [(route_id, bonus)]
# where bonus = (ticket_points / static_path_cost) * route_length
# and the route lies within 2 cards of the static shortest path.
#
# This replaces the inner loop of static_cost() calls in heuristic_policy,
# reducing 786 static_cost() calls/turn to ~15 simple list iterations/ticket.
# ---------------------------------------------------------------------------

from game_data_na import TICKET_BY_ID as _TICKET_BY_ID

TICKET_ROUTE_RELEVANCE: dict = {}  # ticket_id -> [(route_id, bonus_value)]

for _tid, _t in _TICKET_BY_ID.items():
    _c1, _c2, _pts = _t["city1"], _t["city2"], _t["points"]
    _cost = static_cost(_c1, _c2)
    if _cost == 0:
        TICKET_ROUTE_RELEVANCE[_tid] = []
        continue
    _bpc = _pts / _cost   # bonus per train-card on path
    _relevant = []
    for _, _rid, _route in ROUTES_BY_VALUE:
        _r1, _r2 = _route["city1"], _route["city2"]
        _d = min(
            _dist[_CI.get(_c1, 0)][_CI.get(_r1, 0)] + _dist[_CI.get(_r2, 0)][_CI.get(_c2, 0)],
            _dist[_CI.get(_c1, 0)][_CI.get(_r2, 0)] + _dist[_CI.get(_r1, 0)][_CI.get(_c2, 0)],
        ) + _route["length"]
        if _d <= _cost + 2:
            _relevant.append((_rid, _bpc * _route["length"]))
    TICKET_ROUTE_RELEVANCE[_tid] = _relevant
