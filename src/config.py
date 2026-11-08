"""All project settings in one place.

Secrets and connection values come from the .env file.
Fixed choices (model names, folder paths) are plain constants here.
Other files import from this file. They never hard-code these values.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# The project folder is two levels above this file: src/config.py -> project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Read .env into the environment. If .env is missing, nothing breaks here;
# the code that needs a value checks for it and prints a clear message.
load_dotenv(PROJECT_ROOT / ".env")

# --- Neo4j ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Cheaper model: data generation, PDF extraction, Question Router.
CHEAP_MODEL_NAME = "claude-haiku-5-5"
# Stronger model: Challenger and Report Writer.
STRONG_MODEL_NAME = "claude-sonnet-5-5"

# --- Embeddings (free local model, used from Step 7) ---
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Each text chunk becomes a list of this many numbers. The Neo4j vector
# index must use the same number, so both values must change together.
EMBEDDING_DIMENSIONS = 384

# --- Fake data ---
# The data generator uses this seed. Same seed gives the same files.
RANDOM_SEED = 42

# --- Folders ---
DATA_DIR = PROJECT_ROOT / "data"
TABLES_DIR = DATA_DIR / "tables"
PDFS_DIR = DATA_DIR / "pdfs"
CACHE_DIR = DATA_DIR / "cache"
GROUND_TRUTH_FILE = DATA_DIR / "ground_truth.json"

# --- Text search and copied text (Step 7) ---
# Two chunks count as "copied text" at this score or higher (Neo4j cosine scale, 0 to 1).
# Measured on our data: 36 of 37 ring claims have a copy, and only 3 claim pairs
# outside the rings reach it. Measure again on any new data.
COPIED_TEXT_MIN_SCORE = 0.985
# Only documents with the claimant's own story or wording. Forms and tables (repair
# estimates, itemized bills, settlement forms) look alike by design and give false copies.
COPY_CHECK_DOCUMENT_TYPES = ["fnol", "medical_records", "complaint", "demand_letter"]

# --- Litigation and risk score (Step 8, PLAN.md A8) ---
# A lawsuit filed this many days (or fewer) before its limitation deadline is "near the deadline".
NEAR_DEADLINE_DAYS = 14
# Two demands are "similar" when they differ by this share or less (0.03 = 3%).
SIMILAR_DEMAND_SHARE = 0.03
# signal name: (points for each piece of evidence, most points the signal can give).
# The caps stop one signal from deciding the score alone. Same signals -> same score.
RISK_SIGNAL_WEIGHTS = {
    "shared_phone": (5, 15),
    "shared_address": (5, 15),
    "shared_repair_shop": (1, 5),
    "shared_clinic": (1, 5),
    "law_firm_and_clinic_together": (3, 15),
    "law_firm_and_expert_together": (3, 15),
    "copied_text": (5, 25),
    "document_conflicts": (3, 6),
    "lawsuit_filed_near_deadline": (10, 10),
    "related_lawsuits_near_deadline": (2, 10),
    "similar_demand_amounts": (2, 10),
}
MAX_RISK_SCORE = 100
HIGH_RISK_MIN_SCORE = 60
MEDIUM_RISK_MIN_SCORE = 30

# --- Challenger and workflow (Step 9) ---
# A signal with an accepted innocent explanation keeps this share of its points.
CHALLENGER_DISCOUNT = 0.5
# The Challenger can send the case back to the Graph Investigator at most this many times.
MAX_INVESTIGATION_LOOPS = 2
REPORTS_DIR = DATA_DIR / "reports"

# =====================================================================================
# v2 settings (PLAN-v2.md). All weights, bands and thresholds of the v2 score live here
# (CLAUDE.md, rule 21). They are starting values. V10 tunes them on the tuning split only.
# The v1 settings above stay for the v1 agents until V11 and V12 replace them.
# =====================================================================================

# --- Category weights (A7). They add up to 1. ---
CATEGORY_WEIGHTS = {"BI": 0.25, "AS": 0.25, "BF": 0.15, "CT": 0.15, "NL": 0.20}

# --- Bands and actions (A7). The first row whose minimum the total score reaches wins. ---
BANDS = [
    (30, "Very High", "Refer to the special investigation unit (SIU)."),
    (20, "High", "Assign an investigator."),
    (10, "Medium", "Monitor and score again in 30 days."),
    (0, "Low", "No action."),
]

# --- Rule thresholds (A7). Names say what they measure. ---
HEAVY_EARLY_TREATMENT_VISITS = 12      # BI-6: more than this many visits ...
HEAVY_EARLY_TREATMENT_DAYS = 30        # ... in this many days after the loss date
RESERVE_RISE_SHARE = 0.50              # BF-1: the reserve grows more than 50% ...
RESERVE_RISE_DAYS = 30                 # ... within this many days
PAID_TO_RESERVE_RATIO = 1.5            # BF-2: paid is at least 1.5 times the reserve
PAYMENT_CLUSTER_COUNT = 3              # BF-3: this many payments or more ...
PAYMENT_CLUSTER_DAYS = 14              # ... within this many days
REPAIR_GROWTH_RATIO = 1.5              # BF-4: repair paid is at least 1.5 times the first estimate
NEW_CUSTOMER_DAYS = 30                 # CT-1: loss under this many days after customer_since
COVERAGE_INCREASE_DAYS = 30            # CT-2: loss 0 to this many days after a coverage increase
LATE_REPORT_DAYS = 30                  # CT-4: reported more than this many days after the loss
SUIT_NEAR_DEADLINE_DAYS = 30           # CT-7: suit filed within this many days before the deadline
FILING_DEADLINE_YEARS = 2              # filing_deadline = loss date plus this many years
REPEAT_CLAIM_OTHER_CLAIMS = 2          # NL-2: the claimant has this many other claims or more ...
REPEAT_CLAIM_MONTHS = 36               # ... within this many months
CLINIC_AND_ATTORNEY_MIN_CLAIMS = 5     # NL-3: strong link (c) to this many claims or more
FIRM_AND_EXPERT_MIN_LAWSUITS = 3       # NL-5: strong link (d) to this many lawsuits or more ...
FIRM_AND_EXPERT_MONTHS = 12            # ... within this many months
SIMILARITY_THRESHOLD = 0.985           # NL-4: story chunk similarity (Neo4j cosine, 0 to 1)
CLUSTER_MIN_CLAIMS = 8                 # NL-6: a group of this many claims or more ...
CLUSTER_MAX_HOPS = 3                   # ... joined by strong links, up to this many hops

# --- Findings and the Challenger (A6, A8) ---
CONFIDENCE_LEVELS = ["Low", "Medium", "High"]
MIN_CONFIDENCE = "Medium"              # a finding below this is saved but fires no rule
BUSY_PROVIDER_LIMIT = 20               # a provider with more claims than this is "busy"

# --- Base rates: how often each rule fires on ordinary honest claims (A4) ---
# Proposed in V3. Nobody changes it later to make the results look better.
HONEST_RULE_RATES = {}
