"""Tests of src/data_generation/ (new system).

Part 1: small examples worked out by hand. They need no Neo4j and no LLM.
Part 2: the new generators make the SAME files as the committed data/ and the same as the old code.
        The PDF test blanks the API key, so a saved LLM answer that is missing stops the test (no cost).
"""

import csv
import datetime
import json
import random
import sys

import pytest

from src import config
from src.data_generation import generate_pdfs as new_pdfs
from src.data_generation import generate_tables as new_tables
from src.data_generation.claim_plan_blocks import pair_is_safe
from src.data_generation.compute_network_truth import (
    claims_within_hops,
    compute_structural_rules,
    strong_link_kinds,
)
from src.data_generation.document_noise import (
    DATE_FORMATS,
    add_typos,
    format_date,
    maybe_blank_fields,
)
from src.data_generation.document_text_helpers import fill_placeholders, split_amount
from src.data_generation.fact_sheets import (
    FACT_PHRASES,
    facts_for_document,
    find_forbidden_labels,
    replace_forbidden_labels,
)
from src.data_generation.plan_fraud_claims import split_into_incidents
from src.data_generation.plan_signals_and_features import (
    FIRING_VALUES,
    HARMLESS_VALUES,
    weighted_choice,
)
from src.data_generation.table_row_helpers import add_days, add_years, make_id
from src.data_loading.finding_features import FEATURES
from src.scoring.rules_catalog import RULES

# --- Part 1: small examples ---


def test_ring_a_cars_hold_two_or_three_claimants():
    assert split_into_incidents(10) == [3, 3, 2, 2]
    assert split_into_incidents(7) == [3, 2, 2]
    assert split_into_incidents(3) == [3]
    assert split_into_incidents(2) == [2]


def test_the_five_date_styles():
    day = datetime.date(2024, 3, 5)
    assert [format_date(day, style) for style in DATE_FORMATS] == [
        "2024-03-05",
        "03/05/2024",
        "March 5, 2024",
        "5 Mar 2024",
        "3-5-24",
    ]


def test_a_typo_never_changes_numbers_or_short_words():
    always_typo = random.Random(0)
    always_typo.random = lambda: 0.0  # every long word gets a typo
    assert add_typos("12345 abcd 67890", always_typo) == "12345 abcd 67890"
    assert add_typos("hospital", always_typo) != "hospital"


def test_the_same_seed_gives_the_same_typos():
    text = " ".join(["The insured vehicle was struck near the hospital."] * 40)
    assert add_typos(text, random.Random("a")) == add_typos(text, random.Random("a"))


def test_only_optional_fields_can_be_blank():
    rows = [("Claim number", "C-1001"), ("Phone", "713-555-0100")]
    for seed in range(200):
        result = maybe_blank_fields(rows, random.Random(seed))
        assert result[0] == ("Claim number", "C-1001")


def test_split_amount_adds_up_to_the_exact_cent():
    assert split_amount(100.00, [1, 1, 1]) == [33.33, 33.33, 33.34]
    assert round(sum(split_amount(1234.57, [0.15, 0.12, 0.1, 0.3, 0.2])), 2) == 1234.57


def test_a_leap_day_moves_to_28_february():
    assert add_years(datetime.date(2024, 2, 29), 1) == datetime.date(2025, 2, 28)
    assert add_years(datetime.date(2024, 6, 1), 2) == datetime.date(2026, 6, 1)
    assert add_days(datetime.date(2024, 12, 15), 20) == datetime.date(2025, 1, 4)


def test_ids_count_up_from_the_row_count():
    tables = {"providers": []}
    assert make_id(tables, "providers", "PR") == "PR-0001"
    tables["providers"].append({})
    assert make_id(tables, "providers", "PR") == "PR-0002"


def test_the_guard_against_links_nobody_planted():
    # Three other incidents are fine. A fifth incident on the pair gives some claims 4 links: not safe.
    assert pair_is_safe({1: 1, 2: 1, 3: 1}, 4, 3) is True
    assert pair_is_safe({1: 1, 2: 1, 3: 1, 4: 1}, 5, 3) is False
    assert pair_is_safe({}, 1, 3) is True


def test_a_weight_of_zero_is_never_chosen():
    class FakeWithOneSeed:
        random = random.Random(1)

    assert {
        weighted_choice(FakeWithOneSeed, [("yes", 1), ("no", 0)]) for _ in range(50)
    } == {"yes"}


def test_strong_links():
    first = {
        "incident_id": "I-1",
        "phone": "713-555-0100",
        "address_id": "A-1",
        "clinic_id": "PR-1",
        "attorney_id": "AT-1",
        "law_firm_id": "LF-1",
        "expert_id": "EX-1",
    }
    other_incident = dict(first, incident_id="I-2", address_id="A-2")
    assert strong_link_kinds(first, other_incident) == {
        "phone",
        "clinic_and_attorney",
        "firm_and_expert",
    }
    assert strong_link_kinds(first, dict(other_incident, phone="713-555-0199")) == {
        "clinic_and_attorney",
        "firm_and_expert",
    }
    assert (
        strong_link_kinds(first, dict(first, address_id="A-3")) == set()
    )  # same incident: rule 20


def test_claims_within_hops():
    neighbours = {
        "C-1": {"C-2"},
        "C-2": {"C-1", "C-3"},
        "C-3": {"C-2", "C-4"},
        "C-4": {"C-3"},
    }
    assert claims_within_hops(neighbours, "C-1", 2) == {"C-1", "C-2", "C-3"}
    assert claims_within_hops(neighbours, "C-1", 3) == {"C-1", "C-2", "C-3", "C-4"}
    assert claims_within_hops(neighbours, "C-1", 0) == {"C-1"}


def test_two_claimants_but_one_listed_occupant_fires_as_6_for_both():
    tables = {
        "claimants": [
            {
                "claimant_id": f"CL-{number}",
                "phone_number": f"713-555-010{number}",
                "address_id": f"A-{number}",
            }
            for number in (1, 2)
        ],
        "lawsuits": [],
        "claims": [
            {
                "claim_id": f"C-{number}",
                "incident_id": "I-1",
                "claimant_id": f"CL-{number}",
                "loss_date": datetime.date(2024, 1, 1),
                "clinic_id": f"PR-{number}",
                "attorney_id": "",
            }
            for number in (1, 2)
        ],
    }
    fired = compute_structural_rules(tables, {"C-1": 1, "C-2": 1}, {})
    assert fired == {"C-1": {"AS-6"}, "C-2": {"AS-6"}}


def test_the_placeholders_are_filled():
    assert (
        fill_placeholders(
            "On [LOSS_DATE] in [CITY].", {"[LOSS_DATE]": "5 Mar 2024", "[CITY]": "Katy"}
        )
        == "On 5 Mar 2024 in Katy."
    )


def test_a_fact_sheet_never_contains_a_rating_label():
    planted = {
        "treatment_growth": "Extreme",
        "objective_support": "Contradicted",
        "occupant_presence": "Not present",
    }
    for document_type in ["medical_records", "police_report", "adjuster_file"]:
        assert find_forbidden_labels(facts_for_document(document_type, planted)) == []
    assert (
        replace_forbidden_labels("It was Disproportionate and UNCORROBORATED.")
        == "It was out of proportion and not confirmed by anyone else."
    )


def test_every_rating_has_a_fact_sentence():
    for feature in FEATURES:
        for rating in feature.ratings:
            assert (feature.code, rating) in FACT_PHRASES, (feature.code, rating)


def test_the_settings_fit_together():
    rule_ids = [rule.rule_id for rule in RULES]
    assert sorted(config.HONEST_RULE_RATES) == sorted(rule_ids)
    assert list(config.FRAUD_PROFILES) == list(config.FRAUD_TYPE_SIZES)
    for profile in config.FRAUD_PROFILES.values():
        assert set(profile) <= set(rule_ids)
        assert all(0 < chance <= 1 for chance in profile.values())
    for feature_code, _ in FIRING_VALUES.values():
        assert feature_code in HARMLESS_VALUES


# --- Part 2: the same files as the committed data and as the old code ---


@pytest.fixture(scope="module")
def new_data_dir(tmp_path_factory):
    """Run the new table generator once into a scratch folder (the real data/ is not touched)."""
    data_dir = tmp_path_factory.mktemp("new_data")
    new_tables.generate_tables(
        config.RANDOM_SEED, data_dir / "tables", data_dir / "ground_truth.json"
    )
    return data_dir


def test_the_new_tables_equal_the_committed_tables(new_data_dir):
    for committed_file in sorted(config.TABLES_DIR.glob("*.csv")):
        assert (
            new_data_dir / "tables" / committed_file.name
        ).read_bytes() == committed_file.read_bytes(), committed_file.name


def test_the_new_ground_truth_equals_the_committed_one_except_one_note(new_data_dir):
    committed = json.loads(config.GROUND_TRUTH_FILE.read_text(encoding="utf-8"))
    new = json.loads((new_data_dir / "ground_truth.json").read_text(encoding="utf-8"))
    # The first note names the file that computes the network truth. The file has a new name.
    assert "compute_network_truth.py" in new["notes"][0]
    committed["notes"][0] = new["notes"][0]
    assert new == committed


def test_the_same_seed_gives_the_same_tables(new_data_dir, tmp_path):
    new_tables.generate_tables(
        config.RANDOM_SEED, tmp_path / "tables", tmp_path / "ground_truth.json"
    )
    assert (tmp_path / "tables" / "claims.csv").read_bytes() == (
        new_data_dir / "tables" / "claims.csv"
    ).read_bytes()


def read_rows(file_path):
    with open(file_path, newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def pdf_text(file_path):
    from pypdf import PdfReader

    return [page.extract_text() for page in PdfReader(file_path).pages]


def test_the_new_pdfs_equal_the_committed_pdfs_without_any_llm_call(
    new_data_dir, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        config, "ANTHROPIC_API_KEY", ""
    )  # a missing saved answer now raises an error
    conflict_claim = read_rows(config.PDFS_DIR / "planted_conflicts.csv")[0]["claim_id"]
    lawsuit_claim = read_rows(config.TABLES_DIR / "lawsuits.csv")[0]["claim_id"]
    claim_ids = sorted({"C-1001", "C-1002", "C-1088", conflict_claim, lawsuit_claim})

    pdfs_dir = tmp_path / "pdfs"
    summary = new_pdfs.generate_pdfs(
        config.RANDOM_SEED,
        new_data_dir / "tables",
        new_data_dir / "ground_truth.json",
        pdfs_dir,
        claim_ids,
    )
    assert summary["failed_claims"] == {}

    committed_rows = [
        row
        for row in read_rows(config.PDFS_DIR / "documents.csv")
        if row["claim_id"] in claim_ids
    ]
    new_rows = read_rows(pdfs_dir / "documents.csv")
    assert [dict(row, page_count=int(row["page_count"])) for row in new_rows] == [
        dict(row, page_count=int(row["page_count"])) for row in committed_rows
    ]
    assert len(new_rows) > 15
    for row in new_rows:
        path = f"{row['claim_id']}/{row['file_name']}"
        assert pdf_text(pdfs_dir / path) == pdf_text(config.PDFS_DIR / path), path
    assert any(
        row["claim_id"] == conflict_claim
        for row in read_rows(pdfs_dir / "planted_conflicts.csv")
    )


def test_every_page_has_the_footer_from_the_config(new_data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    new_pdfs.generate_pdfs(
        config.RANDOM_SEED,
        new_data_dir / "tables",
        new_data_dir / "ground_truth.json",
        tmp_path / "pdfs",
        ["C-1001"],
    )
    for page_text in pdf_text(tmp_path / "pdfs" / "C-1001" / "C-1001_fnol.pdf"):
        assert config.PDF_FOOTER_TEXT in page_text


def test_an_unknown_claim_id_is_refused(new_data_dir, tmp_path):
    with pytest.raises(ValueError, match="C-9999"):
        new_pdfs.generate_pdfs(
            config.RANDOM_SEED,
            new_data_dir / "tables",
            new_data_dir / "ground_truth.json",
            tmp_path / "pdfs",
            ["C-9999"],
        )


def test_a_missing_table_gives_a_clear_message(tmp_path):
    with pytest.raises(FileNotFoundError, match="generate_tables"):
        new_pdfs.load_tables(tmp_path)


# --- The runners do not overwrite existing data without --overwrite ---


def test_the_table_runner_does_not_replace_existing_tables(
    tmp_path, monkeypatch, capsys
):
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / "claims.csv").write_text("keep me")
    monkeypatch.setattr(sys, "argv", ["x", "--data-dir", str(tmp_path)])
    new_tables.main()
    assert (tmp_path / "tables" / "claims.csv").read_text() == "keep me"
    assert "Nothing was changed" in capsys.readouterr().out


def test_the_pdf_runner_does_not_replace_existing_pdfs(tmp_path, monkeypatch, capsys):
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "documents.csv").write_text("keep me")
    monkeypatch.setattr(sys, "argv", ["x", "--data-dir", str(tmp_path)])
    new_pdfs.main()
    assert (tmp_path / "pdfs" / "documents.csv").read_text() == "keep me"
    assert "Nothing was changed" in capsys.readouterr().out
