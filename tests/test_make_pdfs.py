"""Step 3 tests: the PDF generator, with a fake LLM so the tests cost nothing.

pytest's `monkeypatch` swaps the real ask_llm for fake_ask_llm during each
test and puts the real one back afterwards.
"""

import csv
import datetime
import hashlib
import json
import random
import re

import pytest
from pypdf import PdfReader

from src.datagen import claim_documents, lawsuit_documents
from src.datagen.claim_documents import split_amount
from src.datagen.make_pdfs import generate_pdfs
from src.datagen.make_tables import generate_tables
from src.datagen.noise import add_typos, format_date

TEST_SEED = 42


def fake_ask_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
    # Same prompt gives the same text, like the real cache. Like a well-behaved model,
    # it uses exactly the placeholders that the prompt asks for, so we test the filling step.
    prompt_hash = hashlib.sha256(user_prompt.encode("utf-8")).hexdigest()[:10]
    asked_placeholders = sorted(set(re.findall(r"\[[A-Z_]+\]", user_prompt)))
    return (f"Fake free text number {prompt_hash} written for testing the document layout. "
            f"{' '.join(asked_placeholders)}\n\nA second paragraph of fake text.")


@pytest.fixture(scope="module")
def tables_dir(tmp_path_factory):
    folder = tmp_path_factory.mktemp("tables_for_pdfs")
    generate_tables(TEST_SEED, folder / "tables", folder / "ground_truth.json")
    return folder


def run_generator(monkeypatch, tables_dir, output_dir, claim_ids=None, limit=None, workers=1, fake_llm=fake_ask_llm):
    monkeypatch.setattr(claim_documents, "ask_llm", fake_llm)
    monkeypatch.setattr(lawsuit_documents, "ask_llm", fake_llm)
    return generate_pdfs(TEST_SEED, tables_dir / "tables", tables_dir / "ground_truth.json",
                         output_dir, claim_ids=claim_ids, limit=limit, workers=workers)


def test_many_workers_give_the_same_output_as_one(monkeypatch, tables_dir, tmp_path):
    run_generator(monkeypatch, tables_dir, tmp_path / "one", limit=12, workers=1)
    run_generator(monkeypatch, tables_dir, tmp_path / "four", limit=12, workers=4)
    for file_name in ["documents.csv", "planted_conflicts.csv"]:
        assert (tmp_path / "one" / file_name).read_text() == (tmp_path / "four" / file_name).read_text()
    with open(tmp_path / "one" / "documents.csv", newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            one_text = pdf_text(tmp_path / "one" / row["claim_id"] / row["file_name"])
            four_text = pdf_text(tmp_path / "four" / row["claim_id"] / row["file_name"])
            assert one_text == four_text, f"{row['file_name']} differs"


def test_one_failed_claim_does_not_stop_the_others(monkeypatch, tables_dir, tmp_path):
    def failing_for_one_claim(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        if "Internal reference C-1002;" in user_prompt:
            raise RuntimeError("Simulated API failure")
        return fake_ask_llm(user_prompt, model_name, system_prompt, max_tokens, effort)

    summary = run_generator(monkeypatch, tables_dir, tmp_path, limit=4, workers=2, fake_llm=failing_for_one_claim)
    assert list(summary["failed_claims"]) == ["C-1002"]
    with open(tmp_path / "documents.csv", newline="", encoding="utf-8") as file:
        claim_ids_written = {row["claim_id"] for row in csv.DictReader(file)}
    assert claim_ids_written == {"C-1001", "C-1003", "C-1004"}


def ring_claim_ids(tables_dir, ring_index, count):
    with open(tables_dir / "ground_truth.json", encoding="utf-8") as file:
        return json.load(file)["rings"][ring_index]["claim_ids"][:count]


def pdf_text(file_path):
    pages = PdfReader(file_path).pages
    return "\n".join(page.extract_text() for page in pages)


def test_every_pdf_has_text_and_the_listed_page_count(monkeypatch, tables_dir, tmp_path):
    claim_ids = ring_claim_ids(tables_dir, 0, 1) + ring_claim_ids(tables_dir, 2, 1)   # Ring A and Ring C
    run_generator(monkeypatch, tables_dir, tmp_path, claim_ids)

    with open(tmp_path / "documents.csv", newline="", encoding="utf-8") as file:
        document_rows = list(csv.DictReader(file))
    assert len(document_rows) >= 9          # a lawsuit claim alone has at least 9 documents
    for row in document_rows:
        file_path = tmp_path / row["claim_id"] / row["file_name"]
        assert len(PdfReader(file_path).pages) == int(row["page_count"])
        text = pdf_text(file_path)
        assert len(text) > 200, f"pypdf found almost no text in {row['file_name']}"
        assert re.search(r"\[[A-Z_]+\]", text) is None, f"Unfilled placeholder in {row['file_name']}"


def test_ring_a_claims_share_the_same_story(monkeypatch, tables_dir, tmp_path):
    first_claim, second_claim = ring_claim_ids(tables_dir, 0, 2)
    run_generator(monkeypatch, tables_dir, tmp_path, [first_claim, second_claim])
    first_text = pdf_text(tmp_path / first_claim / f"{first_claim}_fnol.pdf")
    second_text = pdf_text(tmp_path / second_claim / f"{second_claim}_fnol.pdf")
    first_story = first_text.split("Fake free text number")[1][:12]
    second_story = second_text.split("Fake free text number")[1][:12]
    assert first_story == second_story


def test_same_claim_gives_same_text_and_conflicts(monkeypatch, tables_dir, tmp_path):
    claim_ids = ring_claim_ids(tables_dir, 1, 3)
    run_generator(monkeypatch, tables_dir, tmp_path / "first", claim_ids)
    run_generator(monkeypatch, tables_dir, tmp_path / "second", claim_ids)
    for claim_id in claim_ids:
        first_file = tmp_path / "first" / claim_id / f"{claim_id}_fnol.pdf"
        second_file = tmp_path / "second" / claim_id / f"{claim_id}_fnol.pdf"
        assert pdf_text(first_file) == pdf_text(second_file)
    first_conflicts = (tmp_path / "first" / "planted_conflicts.csv").read_text()
    assert first_conflicts == (tmp_path / "second" / "planted_conflicts.csv").read_text()


def test_invented_placeholder_triggers_one_stricter_retry(monkeypatch):
    prompts_seen = []

    def placeholder_once(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        prompts_seen.append(user_prompt)
        if "Never use square brackets" in user_prompt:
            return "Clean text without any placeholder."
        return "Text that mentions [CLAIMANT NAME] by mistake."

    monkeypatch.setattr(claim_documents, "ask_llm", placeholder_once)
    text = claim_documents.write_free_text("Write a note.", random.Random(1))
    assert "[" not in text
    assert len(prompts_seen) == 2


def test_split_amount_adds_up_to_the_exact_cent():
    parts = split_amount("8307.57", [0.1, 0.4, 0.3, 0.15])
    assert round(sum(parts), 2) == 8307.57
    assert len(parts) == 4


def test_format_date_styles():
    date_value = datetime.date(2024, 3, 5)
    assert format_date(date_value, "iso") == "2024-03-05"
    assert format_date(date_value, "us_slash") == "03/05/2024"
    assert format_date(date_value, "long") == "March 5, 2024"
    assert format_date(date_value, "day_month") == "5 Mar 2024"
    assert format_date(date_value, "us_short") == "3-5-24"


def test_typos_never_change_numbers():
    text = "Claim C-1001 paid 8307.57 on 2024-03-05 " + "accident " * 400
    noisy_text = add_typos(text, random.Random(1))
    assert noisy_text != text                      # some typos were added
    assert noisy_text.startswith("Claim C-1001 paid 8307.57 on 2024-03-05 ")
