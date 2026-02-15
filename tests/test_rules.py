"""Tests for rule evaluation logic and roast messages."""
import pytest

from app.core.models import ThresholdRule
from app.core.rules import (
    ROAST_MESSAGES_TIMEOUT,
    ROAST_MESSAGES_WARN,
    evaluate_rules,
    get_highest_action,
    get_roast,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_RULES = [
    ThresholdRule(id=1, hours=10.0, action="warn", window_type="rolling_7d"),
    ThresholdRule(id=2, hours=15.0, action="timeout", duration_hours=1, window_type="rolling_7d"),
    ThresholdRule(id=3, hours=20.0, action="timeout", duration_hours=6, window_type="rolling_7d"),
    ThresholdRule(id=4, hours=30.0, action="timeout", duration_hours=24, window_type="rolling_7d"),
]


# ---------------------------------------------------------------------------
# evaluate_rules
# ---------------------------------------------------------------------------


def test_evaluate_rules_no_match():
    """Playtime below all thresholds returns empty list."""
    result = evaluate_rules(SAMPLE_RULES, 5.0, set())
    assert result == []


def test_evaluate_rules_single_match():
    """Playtime exceeds only the first rule."""
    result = evaluate_rules(SAMPLE_RULES, 12.0, set())
    assert len(result) == 1
    assert result[0].id == 1


def test_evaluate_rules_multiple_match():
    """Playtime exceeds several rules at once."""
    result = evaluate_rules(SAMPLE_RULES, 22.0, set())
    assert len(result) == 3
    assert [r.id for r in result] == [1, 2, 3]


def test_evaluate_rules_all_match():
    """Playtime exceeds all rules."""
    result = evaluate_rules(SAMPLE_RULES, 50.0, set())
    assert len(result) == 4


def test_evaluate_rules_skips_already_triggered():
    """Rules in already_triggered_ids are excluded."""
    result = evaluate_rules(SAMPLE_RULES, 22.0, {1, 2})
    assert len(result) == 1
    assert result[0].id == 3


def test_evaluate_rules_all_already_triggered():
    """All matching rules already triggered returns empty."""
    result = evaluate_rules(SAMPLE_RULES, 22.0, {1, 2, 3})
    assert result == []


def test_evaluate_rules_exact_boundary():
    """Playtime exactly at a threshold triggers the rule (>=)."""
    result = evaluate_rules(SAMPLE_RULES, 10.0, set())
    assert len(result) == 1
    assert result[0].id == 1


# ---------------------------------------------------------------------------
# get_highest_action
# ---------------------------------------------------------------------------


def test_get_highest_action_empty():
    """Returns None for empty list."""
    assert get_highest_action([]) is None


def test_get_highest_action_timeout_wins():
    """Timeout preferred over warn."""
    rules = [
        ThresholdRule(id=1, hours=10.0, action="warn"),
        ThresholdRule(id=2, hours=15.0, action="timeout", duration_hours=1),
    ]
    result = get_highest_action(rules)
    assert result.id == 2
    assert result.action == "timeout"


def test_get_highest_action_highest_duration():
    """Among timeouts, highest duration_hours wins."""
    rules = [
        ThresholdRule(id=2, hours=15.0, action="timeout", duration_hours=1),
        ThresholdRule(id=3, hours=20.0, action="timeout", duration_hours=6),
    ]
    result = get_highest_action(rules)
    assert result.id == 3
    assert result.duration_hours == 6


def test_get_highest_action_warns_only():
    """When all rules are warns, returns the one with highest hours."""
    rules = [
        ThresholdRule(id=1, hours=5.0, action="warn"),
        ThresholdRule(id=2, hours=10.0, action="warn"),
    ]
    result = get_highest_action(rules)
    assert result.id == 2
    assert result.hours == 10.0


def test_get_highest_action_single_rule():
    """Single rule is returned regardless of type."""
    rule = ThresholdRule(id=1, hours=10.0, action="warn")
    result = get_highest_action([rule])
    assert result.id == 1


# ---------------------------------------------------------------------------
# get_roast
# ---------------------------------------------------------------------------


def test_get_roast_warn_returns_from_pool():
    """Warn roast comes from the warn pool."""
    result = get_roast("warn")
    assert result in ROAST_MESSAGES_WARN


def test_get_roast_timeout_returns_from_pool():
    """Timeout roast comes from the timeout pool."""
    result = get_roast("timeout")
    assert result in ROAST_MESSAGES_TIMEOUT


def test_get_roast_unknown_defaults_to_warn():
    """Unknown action type falls back to warn pool."""
    result = get_roast("unknown")
    assert result in ROAST_MESSAGES_WARN
