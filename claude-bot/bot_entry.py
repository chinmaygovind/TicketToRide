"""
Integration point: plugs ISMCTS into bot.py's _claude_turn signature.

Called by bot.py whenever a claude_bot player needs to take a turn.
Returns (action, params) matching bot.py's expected format.
"""
import sys
import os
_HERE   = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
sys.path.insert(0, _PARENT)
sys.path.insert(0, _HERE)

from adapter    import get_legal_moves, apply_move, is_terminal, terminal_score, current_player
from determinize import sample as det_sample
from rollout    import heuristic_policy, random_policy, run_rollout
from ismcts     import ismcts

# ---------------------------------------------------------------------------
# Hyperparameters — override via env var CLAUDE_BOT_ITER / CLAUDE_BOT_POLICY
# ---------------------------------------------------------------------------
import os as _os
N_ITER       = int(_os.environ.get("CLAUDE_BOT_ITER",    "100"))
UCB_C        = float(_os.environ.get("CLAUDE_BOT_C",     "1.41"))
MAX_CLAIMS   = int(_os.environ.get("CLAUDE_BOT_CLAIMS",  "6"))    # prune to top-N claim moves
_POLICY_NAME = _os.environ.get("CLAUDE_BOT_POLICY", "heuristic")  # "heuristic"|"random"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _get_policy():
    return heuristic_policy if _POLICY_NAME != "random" else random_policy


def claude_ismcts_turn(
    state, pid, route_by_id, ticket_by_id,
    hand, trains, draw_step, face_up, claimed,
) -> tuple:
    """
    Drop-in replacement for _claude_turn in bot.py.
    Signature matches the internal turn-function signature used by _DISPATCH.
    """
    policy = _get_policy()

    # draw_step == 1: second card of a draw.  The choice is low-stakes;
    # skip ISMCTS overhead and just use the policy directly.
    if draw_step == 1:
        return policy(state, pid)

    return ismcts(
        state              = state,
        observer_pid       = pid,
        n_iter             = N_ITER,
        c                  = UCB_C,
        sample_fn          = det_sample,
        rollout_policy_fn  = policy,
        get_legal_moves_fn = get_legal_moves,
        apply_move_fn      = apply_move,
        is_terminal_fn     = is_terminal,
        score_fn           = terminal_score,
        current_player_fn  = current_player,
        rollout_fn         = run_rollout,
        max_claims         = MAX_CLAIMS,
    )
