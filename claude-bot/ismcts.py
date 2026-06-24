"""
Information Set Monte Carlo Tree Search — single-observer open-loop variant.

Tree structure
--------------
Nodes are identified by the sequence of the OBSERVER's actions from the root
(opponent actions are invisible in the tree; they are sampled via the rollout
policy during tree traversal).

Each tree node tracks:
  n  — visit count (times this action was selected)
  a  — availability count (times this action was legal when its parent was visited)
  w  — cumulative reward

UCB1 score = w/n  +  c * sqrt(log(a) / n)

The availability term handles the fact that, across different determinizations,
the same opponent move sequence may or may not lead to a state where a
particular bot action is legal.  In practice, for TtR USA the bot's legal moves
depend only on its own (known) hand + public claimed routes, so all moves are
available in every determinization — but we track `a` anyway for correctness
and future-proofing.

Usage
-----
    from ismcts import ismcts
    action, params = ismcts(state, pid, n_iter=200, ...)
"""
import math
import random
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))

from collections import defaultdict
from typing import Callable

# Route value lookup for pruning (pre-sorted descending by point value)
try:
    from graph_cache import ROUTES_BY_VALUE as _RBV
    _ROUTE_VALUE_RANK: dict[int, int] = {rid: rank for rank, (_, rid, _) in enumerate(_RBV)}
except Exception:
    _ROUTE_VALUE_RANK = {}


# ---------------------------------------------------------------------------
# Node storage (flat dict avoids object overhead)
# ---------------------------------------------------------------------------

def _node():
    return [0, 0, 0.0]   # [n, a, w]


def _ucb1(node, c: float) -> float:
    n, a, w = node
    if n == 0:
        return float("inf")
    return w / n + c * math.sqrt(math.log(max(a, 1)) / n)


def _q(node) -> float:
    n, _, w = node
    return w / n if n > 0 else 0.0


# ---------------------------------------------------------------------------
# Move key — compact, hashable representation of an action
# ---------------------------------------------------------------------------

def move_key(action: str, params: dict) -> tuple:
    if action == "claim":
        return ("C", params["route_id"])
    if action == "draw_face_up":
        return ("F", params["slot"])
    return ("B",)   # draw_blind


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def _prune_moves(moves: list, max_claims: int = 6) -> list:
    """
    Keep all draw moves; limit claim moves to the top-max_claims by route value.
    Uses pre-computed rank from ROUTES_BY_VALUE (rank 0 = highest value).
    Reduces effective branching factor so each move gets more iterations.
    """
    claims = [m for m in moves if m[0] == "claim"]
    draws  = [m for m in moves if m[0] != "claim"]
    if len(claims) > max_claims:
        claims.sort(key=lambda m: _ROUTE_VALUE_RANK.get(m[1]["route_id"], 999))
        claims = claims[:max_claims]
    return claims + draws


def ismcts(
    state:              dict,
    observer_pid:       str,
    n_iter:             int,
    c:                  float,
    sample_fn:          Callable,   # (state, pid) -> det_state
    rollout_policy_fn:  Callable,   # (state, pid) -> (action, params)
    get_legal_moves_fn: Callable,   # (state, pid) -> list[(action, params)]
    apply_move_fn:      Callable,   # (state, pid, action, params) -> None
    is_terminal_fn:     Callable,   # (state) -> bool
    score_fn:           Callable,   # (state, pid) -> float
    current_player_fn:  Callable,   # (state) -> str
    rollout_fn:         Callable,   # (state, pid, policy_fn) -> float
    max_claims:         int = 6,    # max claim moves to explore in tree (reduces branching)
) -> tuple:
    """Run ISMCTS and return (action, params) for observer_pid."""

    # tree[path_key] = {move_key: [n, a, w]}
    # path_key is a tuple of move_keys for each observer action taken so far
    tree: dict = defaultdict(lambda: defaultdict(_node))

    root_moves = _prune_moves(get_legal_moves_fn(state, observer_pid),
                              max_claims=max_claims)
    if not root_moves:
        return "draw_blind", {}
    if len(root_moves) == 1:
        return root_moves[0]

    for _ in range(n_iter):
        det = sample_fn(state, observer_pid)
        _simulate(
            det, observer_pid, tree, c,
            get_legal_moves_fn, apply_move_fn, is_terminal_fn,
            score_fn, current_player_fn, rollout_policy_fn, rollout_fn,
            path=(), max_claims=max_claims,
        )

    # Select root action with highest Q-value (exploit, not UCB1)
    root_nodes = tree[()]
    best = max(root_moves, key=lambda m: _q(root_nodes.get(move_key(*m), _node())))
    return best


def _simulate(state, observer_pid, tree, c,
              legal_moves_fn, apply_fn, is_terminal_fn, score_fn,
              current_player_fn, rollout_policy_fn, rollout_fn, path, max_claims=6):
    """One ISMCTS iteration. Returns reward for observer_pid."""
    import game_logic as logic

    if is_terminal_fn(state):
        return score_fn(state, observer_pid)

    cur = current_player_fn(state)
    if not cur:
        return score_fn(state, observer_pid)

    # Handle pending tickets (can arise mid-simulation)
    ps = state["player_states"].get(cur, {})
    if ps.get("pending_tickets"):
        pend = ps["pending_tickets"]
        res = logic.keep_drawn_tickets(state, cur, pend)
        if not res.get("ok") and pend:
            logic.keep_drawn_tickets(state, cur, pend[:1])
        return _simulate(state, observer_pid, tree, c,
                         legal_moves_fn, apply_fn, is_terminal_fn, score_fn,
                         current_player_fn, rollout_policy_fn, rollout_fn, path,
                         max_claims)

    moves = legal_moves_fn(state, cur)
    if not moves:
        logic._next_turn(state)
        return _simulate(state, observer_pid, tree, c,
                         legal_moves_fn, apply_fn, is_terminal_fn, score_fn,
                         current_player_fn, rollout_policy_fn, rollout_fn, path,
                         max_claims)

    if cur != observer_pid:
        # Opponent turn: use rollout policy and continue traversal in-tree
        action, params = rollout_policy_fn(state, cur)
        apply_fn(state, cur, action, params)
        return _simulate(state, observer_pid, tree, c,
                         legal_moves_fn, apply_fn, is_terminal_fn, score_fn,
                         current_player_fn, rollout_policy_fn, rollout_fn, path,
                         max_claims)

    # Observer's turn: tree policy
    # Prune to top-max_claims routes to reduce branching factor
    tree_moves = _prune_moves(moves, max_claims=max_claims)
    node_children = tree[path]  # {mk: [n, a, w]}

    # Mark all (pruned) tree moves as available
    for m in tree_moves:
        mk = move_key(*m)
        node_children[mk][1] += 1   # a += 1

    unvisited = [m for m in tree_moves if node_children[move_key(*m)][0] == 0]

    if unvisited:
        # Expansion: pick one unvisited move, then rollout
        chosen = random.choice(unvisited)
        mk = move_key(*chosen)
        node_children[mk][0] = 1    # n = 1
        action, params = chosen
        apply_fn(state, cur, action, params)
        reward = rollout_fn(state, observer_pid, rollout_policy_fn)
    else:
        # Selection: UCB1 among visited moves
        chosen = max(tree_moves, key=lambda m: _ucb1(node_children[move_key(*m)], c))
        mk = move_key(*chosen)
        node_children[mk][0] += 1  # n += 1
        action, params = chosen
        apply_fn(state, cur, action, params)
        new_path = path + (mk,)
        reward = _simulate(state, observer_pid, tree, c,
                           legal_moves_fn, apply_fn, is_terminal_fn, score_fn,
                           current_player_fn, rollout_policy_fn, rollout_fn,
                           new_path, max_claims)

    # Backpropagate
    node_children[mk][2] += reward   # w += reward
    return reward
