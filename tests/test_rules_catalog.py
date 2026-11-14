"""Tests of src/scoring/rules_catalog.py (new system). No Neo4j needed.

The rule IDs, names and points must not change by accident: saved scores and reports depend on them.
"""

import dataclasses

import pytest

from src.scoring.rules_catalog import (
    CATEGORY_NAMES,
    RULES,
    RULES_BY_ID,
    Rule,
    points_by_category,
)


def test_there_are_32_rules_with_unique_ids_in_the_right_category():
    assert len(RULES) == 32
    assert len(RULES_BY_ID) == 32
    for rule in RULES:
        assert rule.rule_id.startswith(rule.category + "-")
        assert rule.category in CATEGORY_NAMES
        assert rule.points > 0
        assert rule.name and rule.description


def test_the_rules_per_category():
    counts = {
        category: sum(1 for rule in RULES if rule.category == category)
        for category in CATEGORY_NAMES
    }
    assert counts == {"BI": 6, "AS": 7, "BF": 6, "CT": 7, "NL": 6}


def test_the_points_per_category_do_not_change():
    # The saved scores were made with these totals. A change here changes every score.
    assert points_by_category() == {"BI": 57, "AS": 95, "BF": 54, "CT": 80, "NL": 66}


def test_the_points_per_category_for_a_worked_example():
    # BI: 15 + 12 + 8 + 8 + 6 + 8 = 57. NL: 8 + 8 + 14 + 14 + 12 + 10 = 66.
    assert points_by_category()["BI"] == 57
    assert points_by_category()["NL"] == 66


def test_a_rule_cannot_be_changed():
    with pytest.raises(dataclasses.FrozenInstanceError):
        RULES_BY_ID["BI-5"].points = 99
    assert isinstance(RULES_BY_ID["BI-5"], Rule)
