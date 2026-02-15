"""
Rule evaluation logic and roast messages for Mjolnir threshold system.
Pure functions with no DB/Discord dependencies for easy testing.
"""
import random
from typing import List, Optional, Set

from .models import ThresholdRule

# ---------------------------------------------------------------------------
# Roast message pools
# ---------------------------------------------------------------------------

ROAST_MESSAGES_WARN = [
    "Touch grass challenge: FAILED",
    "Your League rank isn't going up, but your hours sure are",
    "At this rate, Riot should be paying YOU",
    "Your chair called. It wants a break",
    "Fun fact: the sun still exists. You should check it out",
    "Even your loading screen is tired of seeing you",
    "Your teammates wish you played this much in ranked",
    "Bro has logged more hours than a 9-5",
    "This is your intervention. The boys are worried",
    "League isn't a personality trait... right?",
    "Your mouse is filing a workers' comp claim",
    "Somewhere, a gym membership is crying",
    "You've spent more time in Summoner's Rift than some people spend sleeping",
]

ROAST_MESSAGES_TIMEOUT = [
    "Mjolnir has spoken. Go outside.",
    "Banned from the rift AND the server. Impressive.",
    "You have been deemed unworthy. Mjolnir sends you to the shadow realm.",
    "Log off. Touch grass. Hydrate. In that order.",
    "Your punishment has been decided. The hammer has fallen.",
    "Even Thor thinks you need a break",
    "Mjolnir said: 'Enough.' And so it was.",
    "Congratulations, you played yourself (and way too much League)",
    "The hammer drops! Time to go remember what sunlight feels like",
    "You've been yeeted from the server. Mjolnir does not miss.",
    "Court is in session. The verdict: too much League. Sentence: timeout.",
    "Imagine losing your server privileges to a video game",
    "Your teammates are free. For now.",
]


def evaluate_rules(
    rules: List[ThresholdRule],
    playtime_hours: float,
    already_triggered_ids: Set[int],
) -> List[ThresholdRule]:
    """
    Given rules sorted by hours ASC, return newly-triggered rules whose hour
    threshold is exceeded and that haven't been triggered yet in this window.
    """
    triggered = []
    for rule in rules:
        if playtime_hours >= rule.hours and rule.id not in already_triggered_ids:
            triggered.append(rule)
    return triggered


def get_highest_action(rules: List[ThresholdRule]) -> Optional[ThresholdRule]:
    """
    From a list of triggered rules, return the most severe one.
    Timeout with highest duration_hours wins. If no timeouts, return highest-hour warn.
    Returns None if list is empty.
    """
    if not rules:
        return None

    timeouts = [r for r in rules if r.action == "timeout"]
    if timeouts:
        return max(timeouts, key=lambda r: r.duration_hours or 0)

    # All warns — return the one with the highest hour threshold
    return max(rules, key=lambda r: r.hours)


def get_roast(action: str) -> str:
    """Return a random roast message for the given action type."""
    if action == "timeout":
        return random.choice(ROAST_MESSAGES_TIMEOUT)
    return random.choice(ROAST_MESSAGES_WARN)
