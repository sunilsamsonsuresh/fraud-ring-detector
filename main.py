"""Entry point for the Fraud Ring Detector.

This file only reads the command and calls one function.
Each step in PLAN.md adds one command here.
"""

import argparse

from neo4j.exceptions import DriverError, Neo4jError

from src import config
from src.datagen.make_pdfs import generate_pdfs
from src.datagen.make_tables import generate_tables
from src.graph.loader import load_graph


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find possible fraud rings in personal auto injury claims.",
    )
    subparsers = parser.add_subparsers(dest="command", title="commands", metavar="<command>")

    generate_parser = subparsers.add_parser("generate-data", help="Make fake data.")
    generate_parser.add_argument(
        "--tables", action="store_true", help="Make the CSV tables and ground_truth.json.",
    )
    generate_parser.add_argument(
        "--pdfs", action="store_true", help="Make the PDF documents (uses the LLM; answers are cached).",
    )
    generate_parser.add_argument("--limit", type=int, help="Only the first N claims (for a small test).")
    generate_parser.add_argument("--claim-ids", help="Only these claims, comma separated. Example: C-1003,C-1006")
    generate_parser.add_argument("--workers", type=int, default=1,
                                 help="How many claims to work on at the same time (default 1). Example: 8")

    subparsers.add_parser("load-graph", help="Load the CSV tables into Neo4j.")
    return parser


def run_load_graph() -> None:
    try:
        node_counts, edge_counts = load_graph(config.TABLES_DIR)
    except (FileNotFoundError, RuntimeError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
    except (Neo4jError, DriverError) as error:
        print(f"Error from Neo4j: {error}")
        raise SystemExit(1)

    print("Neo4j now holds:")
    for label in sorted(node_counts):
        print(f"  node  {label:<18} {node_counts[label]:>5}")
    for edge_type in sorted(edge_counts):
        print(f"  edge  {edge_type:<18} {edge_counts[edge_type]:>5}")


def run_generate_tables() -> None:
    try:
        row_counts = generate_tables(config.RANDOM_SEED, config.TABLES_DIR, config.GROUND_TRUTH_FILE)
    except OSError as error:
        print(f"Error: could not write the data files: {error}")
        raise SystemExit(1)

    print(f"Wrote CSV files to {config.TABLES_DIR} (seed {config.RANDOM_SEED}):")
    for table_name, row_count in row_counts.items():
        print(f"  {table_name:<12} {row_count:>5} rows")
    print(f"Wrote {config.GROUND_TRUTH_FILE}")


def run_generate_pdfs(arguments) -> None:
    claim_ids = None
    if arguments.claim_ids:
        claim_ids = [claim_id.strip() for claim_id in arguments.claim_ids.split(",")]

    if claim_ids is None and arguments.limit is None:
        # A full run makes thousands of LLM calls (CLAUDE.md, section 7).
        answer = input("This makes PDFs for ALL claims and calls the LLM for every text that is not cached. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            print("Stopped. Nothing was made.")
            return

    if arguments.workers < 1 or arguments.workers > 16:
        print("Error: --workers must be between 1 and 16.")
        raise SystemExit(1)

    try:
        summary = generate_pdfs(config.RANDOM_SEED, config.TABLES_DIR, config.GROUND_TRUTH_FILE,
                                config.PDFS_DIR, claim_ids=claim_ids, limit=arguments.limit,
                                workers=arguments.workers)
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nStopped. LLM answers made so far are saved in the cache; run the same command to continue.")
        raise SystemExit(1)

    print(f"Wrote {summary['documents']} PDFs ({summary['pages']} pages) to {config.PDFS_DIR}")
    print(f"Planted date conflicts: {summary['planted_conflicts']} (see planted_conflicts.csv)")
    if summary["failed_claims"]:
        print(f"WARNING: {len(summary['failed_claims'])} claims failed and are missing from documents.csv.")
        print("Run the same command again. Finished texts come from the cache and cost nothing.")
        raise SystemExit(1)


def run_generate_data(arguments) -> None:
    if not arguments.tables and not arguments.pdfs:
        print("Nothing to do. Add --tables or --pdfs.")
        return
    if arguments.tables:
        run_generate_tables()
    if arguments.pdfs:
        run_generate_pdfs(arguments)


def main() -> None:
    parser = build_argument_parser()
    arguments = parser.parse_args()

    if arguments.command == "generate-data":
        run_generate_data(arguments)
    elif arguments.command == "load-graph":
        run_load_graph()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
