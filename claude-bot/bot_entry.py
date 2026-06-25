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
# Hyperparameters — override via env vars
# ---------------------------------------------------------------------------
import os as _os
def _cfg():
    """Read hyperparams from env at call time so they can be changed after import."""
    return {
        "n_iter":     int(_os.environ.get("CLAUDE_BOT_ITER",    "100")),
        "ucb_c":      float(_os.environ.get("CLAUDE_BOT_C",     "1.41")),
        "max_claims": int(_os.environ.get("CLAUDE_BOT_CLAIMS",  "6")),
        "policy":     _os.environ.get("CLAUDE_BOT_POLICY", "heuristic"),
        "use_value":  _os.environ.get("CLAUDE_BOT_VALUE",  "auto"),
    }

# ---------------------------------------------------------------------------
# Value function — loaded lazily; falls back to rollout if model not found
# ---------------------------------------------------------------------------
_value_model = None

def _get_rollout_fn():
    """
    Return the rollout function to use in ISMCTS.

    If a trained value model exists (model/value_weights.json), use it as a
    zero-step rollout (instant board evaluation).  Otherwise fall back to the
    full heuristic rollout.

    CLAUDE_BOT_VALUE env var:
      "auto" (default) — use value model if weights file found
      "on"             — force value model (error if not found)
      "off"            — always use full rollout
    """
    global _value_model

    if _cfg()["use_value"] == "off":
        return run_rollout

    if _value_model is None:
        try:
            from value    import ValueModel
            from features import extract as _extract
            candidate = ValueModel.load()
            # Quick check: weights file must actually exist
            import os as _os2
            _wf = _os2.path.join(_os2.path.dirname(_os2.path.abspath(__file__)),
                                  "model", "value_weights.json")
            if not _os2.path.exists(_wf):
                raise FileNotFoundError("no weights file")
            # Wrap as rollout_fn signature: (state, pid, policy_fn) -> float
            def _vf(state, pid, policy_fn):
                return candidate.predict(_extract(state, pid))
            _value_model = _vf
        except Exception:
            _value_model = False   # sentinel: value model unavailable

    if _value_model is False:
        return run_rollout

    return _value_model


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _get_policy():
    return heuristic_policy if _cfg()["policy"] != "random" else random_policy


def claude_ismcts_turn(
    state, pid, route_by_id, ticket_by_id,
    hand, trains, draw_step, face_up, claimed,
) -> tuple:
    """
    Drop-in replacement for _claude_turn in bot.py.
    Signature matches the internal turn-function signature used by _DISPATCH.
    """
    cfg        = _cfg()
    policy     = _get_policy()
    rollout_fn = _get_rollout_fn()

    # draw_step == 1: second card draw.  Low-stakes; skip ISMCTS overhead.
    if draw_step == 1:
        return policy(state, pid)

    return ismcts(
        state              = state,
        observer_pid       = pid,
        n_iter             = cfg["n_iter"],
        c                  = cfg["ucb_c"],
        sample_fn          = det_sample,
        rollout_policy_fn  = policy,
        get_legal_moves_fn = get_legal_moves,
        apply_move_fn      = apply_move,
        is_terminal_fn     = is_terminal,
        score_fn           = terminal_score,
        current_player_fn  = current_player,
        rollout_fn         = rollout_fn,
        max_claims         = cfg["max_claims"],
    )
