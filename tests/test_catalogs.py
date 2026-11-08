"""V1 tests: the rule catalog, the feature catalog and the v2 settings. No Neo4j, no LLM."""

from src import config
from src.documents.feature_catalog import FEATURES, FEATURES_BY_CODE, MERGE_METHODS
from src.scoring.rules_catalog import (CATEGORY_NAMES, RULES, RULES_BY_ID, SOURCE_NAMES,
                                       enabled_points_by_category, features_needed)


def test_rule_ids_are_unique_and_there_are_32_rules():
    rule_ids = [rule.rule_id for rule in RULES]
    assert len(rule_ids) == len(set(rule_ids)) == 32
    for rule in RULES:
        assert rule.rule_id.startswith(rule.category + "-")
        assert rule.category in CATEGORY_NAMES and rule.source in SOURCE_NAMES
        assert rule.points > 0 and rule.needs


def test_category_totals_match_the_plan():
    assert enabled_points_by_category() == {"BI": 57, "AS": 95, "BF": 54, "CT": 80, "NL": 66}


def test_every_feature_used_by_a_rule_exists():
    for rule in RULES:
        for code in features_needed(rule):
            assert code in FEATURES_BY_CODE, (rule.rule_id, code)
            assert rule.rule_id in FEATURES_BY_CODE[code].used_by, (rule.rule_id, code)


def test_every_feature_has_a_rule():
    codes = [feature.code for feature in FEATURES]
    assert len(codes) == len(set(codes)) == 14
    for feature in FEATURES:
        assert feature.used_by, feature.code
        for rule_id in feature.used_by:
            assert feature.code in features_needed(RULES_BY_ID[rule_id]), (feature.code, rule_id)
        assert feature.merge in MERGE_METHODS
        if feature.value_type == "rating":
            assert len(feature.ratings) >= 3 and len(set(feature.ratings)) == len(feature.ratings)
        else:
            assert feature.value_type == "number" and feature.ratings == ()


def test_weights_add_up_to_one_and_bands_are_ordered():
    assert set(config.CATEGORY_WEIGHTS) == set(CATEGORY_NAMES)
    assert abs(sum(config.CATEGORY_WEIGHTS.values()) - 1) < 1e-9
    minimums = [minimum for minimum, _, _ in config.BANDS]
    assert minimums == sorted(minimums, reverse=True) and minimums[-1] == 0
    assert [band for _, band, _ in config.BANDS] == ["Very High", "High", "Medium", "Low"]
    assert config.MIN_CONFIDENCE in config.CONFIDENCE_LEVELS
