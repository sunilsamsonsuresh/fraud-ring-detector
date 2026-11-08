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
