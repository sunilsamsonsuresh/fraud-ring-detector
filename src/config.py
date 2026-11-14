"""Settings of the new system. Every other file reads its settings from here.

Secrets (the Neo4j password) come from the .env file. The code never contains a password.
This file holds only what the files written so far need. When a new file needs a new
setting, we add it here at that time.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# This file is src/config.py, so the project folder is one level above src/.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Copy the lines of .env into the environment. If .env is missing, nothing breaks here.
# The file that needs a value checks it and prints a clear message.
load_dotenv(PROJECT_ROOT / ".env")

# --- Folders ---
DATA_DIR = PROJECT_ROOT / "data"
TABLES_DIR = DATA_DIR / "tables"  # the CSV files that were loaded into the graph
PDFS_DIR = (
    DATA_DIR / "pdfs"
)  # one folder for each claim, and documents.csv (the list of all PDFs)
CACHE_DIR = DATA_DIR / "cache"  # every LLM answer is saved here, so we never pay twice
GRAPH_MAP_FILE = (
    DATA_DIR / "graph_map.json"
)  # what is in the graph: the graph query agent reads it

# --- PDFs ---
# The line at the bottom of each page. The data generator writes it. The reader removes it.
PDF_FOOTER_TEXT = "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD"
# A chunk is a piece of page text. Neighbour chunks share some words, so a sentence on a border is in both.
CHUNK_MAX_WORDS = 150
CHUNK_OVERLAP_WORDS = 30

# --- LLM (Anthropic Claude) ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CHEAP_MODEL_NAME = "claude-haiku-5-5"  # data pipeline only: reads PDF pages (entities and findings). Cached.
STRONG_MODEL_NAME = (
    "claude-opus-5-5"  # the chat: router, specialist agents, report writer. Not cached.
)

# --- Embeddings ---
# The local model that turns text into numbers. The size must equal the size of the vector index
# (src/data_loading/graph_schema.py). Change both together, and load the chunks again.
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

# --- Neo4j ---
# The second value is the default, used when .env has no such line.
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# --- Fake data (src/data_generation/) ---
# The generators use this seed. The same seed gives the same files.
RANDOM_SEED = 42
GROUND_TRUTH_FILE = (
    DATA_DIR / "ground_truth.json"
)  # which claims are fraud, lookalikes, and which rules were planted
FILING_DEADLINE_YEARS = (
    2  # a suit must be filed within this many years of the loss date
)
TOTAL_CLAIMS = 500
TOTAL_LAWSUITS = 50
# Planted fraud: claims for each fraud type (about 12% of all claims).
FRAUD_TYPE_SIZES = {
    "ring_a": 10,
    "ring_b": 14,
    "ring_c": 11,
    "build_up": 5,
    "jump_in": 5,
    "billing_inflation": 5,
    "coverage_trigger": 5,
    "paper_accident": 5,
}
# Lookalikes: honest claims that look like fraud on purpose.
FAMILY_PAIRS = 8  # two family members: shared address and phone, different incidents
MULTI_CLAIMANT_INCIDENT_SIZES = [
    2,
    3,
    4,
    2,
    3,
    2,
    4,
    3,
    2,
    3,
]  # honest incidents: claimants in each
LOOKALIKE_GROUP_SIZES = {
    "busy_law_firm": 25,
    "busy_repair_shop": 25,
    "large_clinic": 25,
    "late_reporter": 15,
    "new_customer": 10,
    "serious_injury": 10,
    "pre_existing": 10,
}
BUSY_LAW_FIRM_LAWSUITS = 6  # how many of the busy law firm's claims go to court

# Profile of each fraud type: rule ID -> the chance that ONE claim of this type shows the signal.
# A claim never shows every signal; some show few. On purpose.
# These values were set before any data existed. Do not change them to make the results look better.
FRAUD_PROFILES = {
    "ring_a": {"AS-5": 0.75, "AS-6": 0.80, "BF-4": 0.80, "NL-1": 0.90, "NL-4": 0.85},
    "ring_b": {"BI-2": 0.80, "BI-3": 0.70, "BI-5": 0.75, "BI-6": 0.80, "NL-3": 0.90},
    "ring_c": {"CT-7": 0.85, "NL-4": 0.80, "NL-5": 0.90},
    "build_up": {"BI-2": 0.90, "BI-3": 0.70, "BI-6": 0.75, "BF-1": 0.75},
    "jump_in": {"AS-5": 0.90, "AS-6": 0.80, "BI-1": 0.70},
    "billing_inflation": {"BF-3": 0.70, "BF-4": 0.80, "BF-5": 0.85, "BF-6": 0.80},
    "coverage_trigger": {"CT-1": 0.75, "CT-2": 0.70, "CT-3": 0.70, "CT-5": 0.80},
    "paper_accident": {"AS-2": 0.80, "AS-3": 0.70, "AS-4": 0.80, "AS-7": 0.75},
}

# Base rates: the share of ORDINARY honest claims (not fraud, not in a lookalike group) where the rule
# fires, among the claims where the rule can apply (BI-5: claims with an attorney; BF-4 and BF-6: claims
# with a repair; AS-6 and AS-7: claims with a police report; CT-7 and NL-5: claims with a lawsuit).
# Set before any data existed. Nobody changes it later to make the results look better.
HONEST_RULE_RATES = {
    "BI-1": 0.03,
    "BI-2": 0.05,
    "BI-3": 0.10,
    "BI-4": 0.08,
    "BI-5": 0.08,
    "BI-6": 0.05,
    "AS-1": 0.06,
    "AS-2": 0.02,
    "AS-3": 0.03,
    "AS-4": 0.04,
    "AS-5": 0.02,
    "AS-6": 0.02,
    "AS-7": 0.05,
    "BF-1": 0.06,
    "BF-2": 0.03,
    "BF-3": 0.05,
    "BF-4": 0.06,
    "BF-5": 0.03,
    "BF-6": 0.05,
    "CT-1": 0.03,
    "CT-2": 0.03,
    "CT-3": 0.02,
    "CT-4": 0.06,
    "CT-5": 0.04,
    "CT-6": 0.03,
    "CT-7": 0.06,
    "NL-1": 0.05,
    "NL-2": 0.03,
    "NL-3": 0.03,
    "NL-4": 0.03,
    "NL-5": 0.12,
    "NL-6": 0.03,
}

# --- Rule thresholds ---
# Numbers that rules compare with. Names say what they measure. Weights and bands come with the engine.
HEAVY_EARLY_TREATMENT_VISITS = 12  # BI-6: more than this many visits ...
HEAVY_EARLY_TREATMENT_DAYS = 30  # ... in this many days after the loss date
CLINIC_AND_ATTORNEY_MIN_CLAIMS = (
    5  # NL-3: linked through the same clinic AND attorney to this many claims or more
)
NEW_CUSTOMER_DAYS = 30  # CT-1: loss under this many days after customer_since
COVERAGE_INCREASE_DAYS = 30  # CT-2: loss 0 to this many days after a coverage increase
LATE_REPORT_DAYS = 30  # CT-4: reported more than this many days after the loss
SUIT_NEAR_DEADLINE_DAYS = (
    30  # CT-7: suit filed 0 to this many days before the filing deadline
)
RESERVE_RISE_SHARE = 0.50  # BF-1: the reserve grows more than 50% ...
RESERVE_RISE_DAYS = 30  # ... within this many days
PAID_TO_RESERVE_RATIO = 1.5  # BF-2: paid is at least 1.5 times the latest reserve
PAYMENT_CLUSTER_COUNT = 3  # BF-3: this many payments or more ...
PAYMENT_CLUSTER_DAYS = 14  # ... within this many days
REPAIR_GROWTH_RATIO = 1.5  # BF-4: repair paid is at least 1.5 times the first estimate
REPEAT_CLAIM_OTHER_CLAIMS = (
    2  # NL-2: the claimant has this many other claims or more ...
)
REPEAT_CLAIM_MONTHS = 36  # ... with a loss within this many months of this loss
FIRM_AND_EXPERT_MIN_LAWSUITS = 3  # NL-5: linked through the same law firm AND expert to this many claims or more ...
FIRM_AND_EXPERT_MONTHS = (
    12  # ... with a suit filed within this many months of this suit
)
SIMILARITY_THRESHOLD = 0.985  # NL-4: story chunk similarity (Neo4j cosine, 0 to 1) at or above this is a copy
# NL-4 compares only the claimant's story and the legal wording. Forms and tables look alike by design.
# Medical treatment summaries are left out: their LLM boilerplate reached 0.995 between unrelated claims.
STORY_DOCUMENT_TYPES = ["fnol", "complaint", "demand_letter"]
CHUNK_VECTOR_INDEX_NAME = (
    "chunk_embedding_index"  # the Neo4j vector index over the text chunks
)
CHUNK_TEXT_INDEX_NAME = (
    "chunk_text_index"  # the Neo4j full-text index over the text chunks
)
# Hybrid document search: each index gives this many chunks, then plain code mixes the two lists.
HYBRID_SEARCH_CANDIDATES = 20
# Reciprocal rank fusion: a chunk at place p of a list gets 1 / (RANK_FUSION_CONSTANT + p) points.
# 60 is the usual value. A bigger number makes the first places count less.
RANK_FUSION_CONSTANT = 60
# Generated queries (graph query agent): a query that runs longer is stopped, and at most this many rows come back.
GENERATED_QUERY_SECONDS = 10
GENERATED_QUERY_MAX_ROWS = 50
COPY_CANDIDATES = (
    100  # NL-4: the index returns this many closest chunks for each own chunk
)
SHARED_CONTACT_MIN_CLAIMS = (
    2  # group list: a phone or an address shared by this many claims or more
)
MAX_CLAIMS_SHOWN_BY_SCORE = (
    10  # score list: show this many claims (the highest score first)
)
MAX_SHARED_GROUPS_SHOWN = 10  # group list: show this many groups (the biggest first)
CLUSTER_MIN_CLAIMS = 8  # NL-6: a group of this many claims or more ...
COMMUNITY_MIN_CLAIMS = (
    3  # global search: a community has this many claims or more, joined by strong links
)
MAX_COMMUNITIES_SHOWN = (
    10  # global search: list this many communities (the biggest first)
)
MAX_SHARED_VALUES_SHOWN = 8  # a community lists this many shared phones, addresses, clinics ... (most claims first)
COMMUNITY_REPORT_MAX_TOKENS = (
    600  # one community report of the cheap LLM: a few sentences
)
CLUSTER_MAX_HOPS = 3  # ... joined by direct links, counted up to this many links away

# --- Score ---
# The weight of each category in the total score. They add up to 1.
CATEGORY_WEIGHTS = {"BI": 0.25, "AS": 0.25, "BF": 0.15, "CT": 0.15, "NL": 0.20}

# Findings read from PDFs: a finding below MIN_CONFIDENCE is kept for the report but fires no rule.
CONFIDENCE_LEVELS = ["Low", "Medium", "High"]  # least to most sure
MIN_CONFIDENCE = "Medium"

# Bands and actions. The first row whose minimum the total score reaches wins.
BANDS = [
    (30, "Very High", "Refer to the special investigation unit (SIU)."),
    (20, "High", "Assign an investigator."),
    (10, "Medium", "Monitor and score again in 30 days."),
    (0, "Low", "No action."),
]
