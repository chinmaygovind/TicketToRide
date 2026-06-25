"""
Game-state → fixed-length feature vector for value estimation.

All features are normalised to approximately [-1, 1] or [0, 1].
Designed for 2-player games only (opp = the single other player).
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import game_logic as logic
from game_data_na import TICKET_BY_ID

N_FEATURES = 20

FEATURE_NAMES = [
    "route_score_diff",         #  0  (my_route - opp_route) / 50
    "completed_ticket_diff",    #  1  (my_comp  - opp_comp ) / 50
    "my_completed_pts",         #  2  my completed ticket pts / 50
    "opp_completed_pts",        #  3
    "my_pending_pts",           #  4  my uncompleted ticket pts / 50
    "opp_pending_pts",          #  5
    "my_trains_used",           #  6  (45 - my_trains) / 45
    "opp_trains_used",          #  7
    "trains_used_diff",         #  8  (my_used - opp_used) / 45
    "my_hand_size",             #  9  total cards / 20
    "opp_hand_size",            # 10
    "hand_size_diff",           # 11
    "my_locos",                 # 12  locomotives / 5
    "deck_pct",                 # 13  remaining deck / 110
    "my_ticket_count",          # 14  tickets / 5
    "opp_ticket_count",         # 15
    "my_completion_rate",       # 16  completed / total tickets
    "opp_completion_rate",      # 17
    "routes_claimed",           # 18  total claimed routes / 50
    "game_stage",               # 19  1 - deck_pct
]


def _ticket_stats(state: dict, pid: str) -> tuple:
    """(completed_pts, pending_pts, n_tickets, n_completed)"""
    ps = state["player_states"].get(pid, {})
    completed_pts = pending_pts = n_completed = 0
    tickets = ps.get("tickets", [])
    for tid in tickets:
        t = TICKET_BY_ID.get(tid)
        if not t:
            continue
        if logic.is_path_connected(state, pid, t["city1"], t["city2"]):
            completed_pts += t["points"]
            n_completed   += 1
        else:
            pending_pts += t["points"]
    return completed_pts, pending_pts, len(tickets), n_completed


def extract(state: dict, pid: str) -> list:
    """Return a list of N_FEATURES floats for observer pid."""
    ps  = state["player_states"]
    me  = ps.get(pid, {})
    opp_pid = next((p for p in ps if p != pid), None)
    opp = ps.get(opp_pid, {}) if opp_pid else {}

    my_route  = me.get("route_score", 0)
    opp_route = opp.get("route_score", 0)

    my_cp, my_pp, my_nt, my_nc   = _ticket_stats(state, pid)
    opp_cp, opp_pp, opp_nt, opp_nc = (
        _ticket_stats(state, opp_pid) if opp_pid else (0, 0, 0, 0)
    )

    my_trains  = me.get("trains", 45)
    opp_trains = opp.get("trains", 45)
    my_used    = 45 - my_trains
    opp_used   = 45 - opp_trains

    my_hand    = sum(me.get("hand", {}).values())
    opp_hand   = sum(opp.get("hand", {}).values())
    my_locos   = me.get("hand", {}).get("locomotive", 0)

    deck_size  = len(state.get("deck", []))
    deck_pct   = deck_size / 110.0
    n_claimed  = len(state.get("claimed_routes", {}))

    my_cr  = my_nc  / max(my_nt,  1)
    opp_cr = opp_nc / max(opp_nt, 1)

    return [
        (my_route - opp_route)  / 50.0,   #  0
        (my_cp    - opp_cp)     / 50.0,   #  1
        my_cp    / 50.0,                  #  2
        opp_cp   / 50.0,                  #  3
        my_pp    / 50.0,                  #  4
        opp_pp   / 50.0,                  #  5
        my_used  / 45.0,                  #  6
        opp_used / 45.0,                  #  7
        (my_used - opp_used) / 45.0,      #  8
        my_hand  / 20.0,                  #  9
        opp_hand / 20.0,                  # 10
        (my_hand - opp_hand) / 20.0,      # 11
        my_locos / 5.0,                   # 12
        deck_pct,                         # 13
        my_nt  / 5.0,                     # 14
        opp_nt / 5.0,                     # 15
        my_cr,                            # 16
        opp_cr,                           # 17
        n_claimed / 50.0,                 # 18
        1.0 - deck_pct,                   # 19
    ]
