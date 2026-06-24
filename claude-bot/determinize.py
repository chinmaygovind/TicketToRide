"""
Belief sampling for ISMCTS determinization.

Given the observer's legal knowledge (own hand, face-up cards, public counts),
sample a plausible full game state by redistributing:
  - Unknown cards (deck + opponent hands) → preserving each opponent's card count
  - Unknown tickets → preserving each opponent's ticket count
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import copy
import random
from game_data_na import CARD_COUNTS, TICKET_BY_ID

# Full 110-card pool
_POOL: list[str] = []
for _color, _count in CARD_COUNTS.items():
    _POOL.extend([_color] * _count)

_ALL_TICKET_IDS: list[int] = list(TICKET_BY_ID.keys())


def sample(state: dict, observer_pid: str) -> dict:
    """
    Deep-copy state and resample opponent hands + tickets to reflect
    the observer's uncertainty. Own hand, face-up cards, claimed routes,
    and discard pile are left unchanged (they are public/known).
    """
    s = copy.deepcopy(state)
    _resample_hands(s, observer_pid)
    _resample_tickets(s, observer_pid)
    return s


def _resample_hands(state: dict, observer_pid: str) -> None:
    """
    Redistribute unknown cards (actual deck + all opponent hands) uniformly
    at random, preserving each opponent's total card count.
    """
    # Unknown = current deck contents + opponent hands
    unknown: list[str] = list(state["deck"])
    for pid, ps in state["player_states"].items():
        if pid == observer_pid:
            continue
        for color, cnt in ps["hand"].items():
            unknown.extend([color] * cnt)

    random.shuffle(unknown)

    idx = 0
    for pid, ps in state["player_states"].items():
        if pid == observer_pid:
            continue
        count = sum(ps["hand"].values())
        new_cards = unknown[idx: idx + count]
        idx += count
        ps["hand"] = {}
        for card in new_cards:
            ps["hand"][card] = ps["hand"].get(card, 0) + 1

    # Remaining unknown cards become the new deck (already shuffled)
    state["deck"] = unknown[idx:]


def _resample_tickets(state: dict, observer_pid: str) -> None:
    """
    Sample tickets for opponents from the pool of tickets not held by the
    observer and not still in the destination deck.
    """
    my_tickets   = set(state["player_states"][observer_pid]["tickets"])
    dest_in_deck = set(state["dest_deck"])

    # Tickets that could be in an opponent's hand
    available = [t for t in _ALL_TICKET_IDS
                 if t not in my_tickets and t not in dest_in_deck]
    random.shuffle(available)

    idx = 0
    for pid, ps in state["player_states"].items():
        if pid == observer_pid:
            continue
        count = len(ps["tickets"])
        ps["tickets"] = available[idx: idx + count]
        idx += count
