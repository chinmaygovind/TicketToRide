"""
Self-play training harness (Stage 5 — stub).

Planned approach:
  1. Maintain a persistent pool of opponents:
       - fish_bot, chin_bot, rocket_bot (fixed heuristics)
       - Periodic snapshots of claude_bot (past checkpoints)
       - A blocking-heavy variant and a greedy variant
  2. Each training round: run N 2-player games against a random pool member.
  3. Update the eval / value network weights via self-play signal.
  4. Evaluate on the held-out ladder (eval.py); accept only if improvement.

To implement:
  - features.py  — board-state → feature vector
  - value.py     — logistic regression / small MLP value estimator
  - Plug value.py into rollout.py as an alternative to run_rollout

Run:
    python train.py --rounds 50 --games-per-round 20
"""

import argparse

def run_training(rounds: int, games_per_round: int):
    raise NotImplementedError(
        "Self-play training not yet implemented. "
        "Complete features.py and value.py first."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds",          type=int, default=50)
    parser.add_argument("--games-per-round", type=int, default=20)
    args = parser.parse_args()
    run_training(args.rounds, args.games_per_round)
