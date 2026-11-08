"""Entry point for the Fraud Ring Detector.

This file only reads the command and calls one function.
Each step in PLAN.md adds one command here.
"""

import argparse

from neo4j.exceptions import DriverError, Neo4jError

from src import config
from src.datagen.make_pdfs import generate_pdfs
from src.datagen.make_tables import generate_tables
from src.documents.ingest import all_document_rows, ingest_documents, print_summary, select_claims
from src.documents.store_chunks import store_chunks
from src.documents.feature_catalog import features_table_lines
from src.graph.loader import load_graph
from src.scoring.rules_catalog import rules_table_lines
from src.workflow import investigate_claim


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

    ingest_parser = subparsers.add_parser("ingest-documents", help="Read the PDFs into the graph.")
    ingest_parser.add_argument("--chunks", action="store_true",
                               help="Save text chunks with embeddings for the text search (free, local model).")
    ingest_parser.add_argument("--entities", action="store_true",
                               help="Find entities and conflicts in the PDFs (uses the LLM; answers are cached).")
    ingest_parser.add_argument("--limit", type=int, help="Only the first N claims (for a small test).")
    ingest_parser.add_argument("--claim-ids", help="Only these claims, comma separated. Example: C-1003,C-1006")
    ingest_parser.add_argument("--workers", type=int, default=1,
                               help="--entities only: claims to work on at the same time (default 1). Example: 8")

    subparsers.add_parser("show-rules", help="Print the rule catalog.")
    subparsers.add_parser("show-features", help="Print the feature catalog.")

    investigate_parser = subparsers.add_parser("investigate", help="Run the full investigation on one claim.")
    investigate_parser.add_argument("claim_id", help="The claim to investigate. Example: C-1037")
    return parser


def run_ingest_chunks(selected_claim_ids) -> None:
    print(f"Saving chunks for {len(selected_claim_ids)} claims (first run loads the embedding model) ...")
    try:
        chunk_count, warnings = store_chunks(selected_claim_ids, all_document_rows())
    except (RuntimeError, Neo4jError, DriverError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
    print(f"Saved {chunk_count} chunks.")
    for warning in warnings:
        print(f"  Warning: {warning}")


def run_ingest_entities(selected_claim_ids, page_count, ask_first, workers) -> None:
    # One LLM call per page that is not cached yet (CLAUDE.md, section 7).
    print(f"Entities: {len(selected_claim_ids)} claims, {page_count} PDF pages: up to {page_count} LLM calls.")
    if ask_first:
        answer = input("This reads ALL claims with the LLM. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            print("Stopped. No entities were read.")
            return
    try:
        result_by_claim_id, error_by_claim_id = ingest_documents(selected_claim_ids, workers)
    except (RuntimeError, Neo4jError, DriverError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nStopped. LLM answers made so far are saved in the cache; run the same command to continue.")
        raise SystemExit(1)

    print_summary(result_by_claim_id)
    if error_by_claim_id:
        print(f"\nWARNING: {len(error_by_claim_id)} claims failed. Run the same command again.")
        raise SystemExit(1)


def run_ingest_documents(arguments) -> None:
    if not arguments.chunks and not arguments.entities:
        print("Nothing to do. Add --chunks, --entities or both.")
        return
    claim_ids = None
    if arguments.claim_ids:
        claim_ids = [claim_id.strip() for claim_id in arguments.claim_ids.split(",")]
    if arguments.workers < 1 or arguments.workers > 16:
        print("Error: --workers must be between 1 and 16.")
        raise SystemExit(1)
    try:
        selected_claim_ids, page_count = select_claims(claim_ids, arguments.limit)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)

    if arguments.chunks:
        run_ingest_chunks(selected_claim_ids)
    if arguments.entities:
        ask_first = claim_ids is None and arguments.limit is None
        run_ingest_entities(selected_claim_ids, page_count, ask_first, arguments.workers)


def run_investigate(arguments) -> None:
    claim_id = arguments.claim_id.strip().upper()
    print(f"Investigating {claim_id} (LLM answers are cached; a new claim costs a few cents) ...")
    try:
        state = investigate_claim(claim_id)
    except (RuntimeError, Neo4jError, DriverError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
    if state.get("error_message"):
        print(f"Error: {state['error_message']}")
        raise SystemExit(1)
    print()
    print(state["report_text"])
    print(f"Saved on the Claim node: {state['saved_summary']}")
    print(f"Report file: {state['report_file']}")


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
    elif arguments.command == "ingest-documents":
        run_ingest_documents(arguments)
    elif arguments.command == "investigate":
        run_investigate(arguments)
    elif arguments.command == "show-rules":
        print("\n".join(rules_table_lines()))
    elif arguments.command == "show-features":
        print("\n".join(features_table_lines()))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
