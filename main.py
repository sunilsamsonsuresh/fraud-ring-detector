"""Entry point for the Fraud Ring Detector. This file only reads the command and calls the code that does the work.

python main.py generate-data --tables          make the fake CSV tables and ground_truth.json (no LLM)
python main.py generate-data --pdfs            make the fake PDFs (cheap LLM; every answer is cached)
python main.py build-graph                     load everything into Neo4j: pipeline steps 2 to 5
python main.py build-graph --write-reports     ... and let the cheap LLM write the community reports (cached)
python main.py score-claim C-1088              print the score of one claim (saves nothing)
python main.py show-rules                      print the 32 scoring rules
python main.py chat                            talk with the fraud agents; the chat remembers the session
"""

import argparse
import uuid

from neo4j.exceptions import DriverError, Neo4jError

from src import config
from src.data_generation.generate_pdfs import generate_pdfs
from src.data_generation.generate_tables import generate_tables
from src.data_loading.load_communities_into_graph import load_communities_into_graph
from src.data_loading.load_pdfs_into_graph import load_pdfs_into_graph
from src.data_loading.load_tables_into_graph import load_tables_into_graph
from src.data_loading.save_scores_into_graph import save_all_scores
from src.data_loading.write_graph_map import write_graph_map
from src.graph.connection import open_neo4j_driver
from src.scoring.rules_catalog import CATEGORY_NAMES, RULES
from src.tools.checks import check_claim_id
from src.tools.score_tools import get_claim_score
from src.workflow import build_chat_workflow, chat_turn


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find possible fraud rings in personal auto injury claims."
    )
    subparsers = parser.add_subparsers(
        dest="command", title="commands", metavar="<command>"
    )

    generate_parser = subparsers.add_parser("generate-data", help="Make fake data.")
    generate_parser.add_argument(
        "--tables", action="store_true", help="Make the CSV tables."
    )
    generate_parser.add_argument(
        "--pdfs", action="store_true", help="Make the PDFs (cheap LLM; cached)."
    )
    generate_parser.add_argument(
        "--limit", type=int, help="PDFs: only the first N claims."
    )
    generate_parser.add_argument(
        "--claim-ids",
        help="PDFs: only these claims, comma separated. Example: C-1003,C-1006",
    )

    build_parser = subparsers.add_parser(
        "build-graph",
        help="Load tables, PDFs, scores, communities and the graph map into Neo4j.",
    )
    build_parser.add_argument(
        "--write-reports",
        action="store_true",
        help="Also write one community report each with the cheap LLM (cached).",
    )

    score_parser = subparsers.add_parser(
        "score-claim", help="Print the score of one claim."
    )
    score_parser.add_argument("claim_id", help="The claim. Example: C-1026")
    subparsers.add_parser("show-rules", help="Print the scoring rules.")
    subparsers.add_parser(
        "chat", help="Talk with the fraud agents. It remembers the session."
    )
    return parser


def ask_yes(question):
    return input(f"{question} [y/N] ").strip().lower() == "y"


def run_generate_data(arguments) -> None:
    if not arguments.tables and not arguments.pdfs:
        print("Nothing to do. Add --tables or --pdfs.")
        return
    if arguments.tables:
        row_counts = generate_tables(
            config.RANDOM_SEED, config.TABLES_DIR, config.GROUND_TRUTH_FILE
        )
        print(
            f"Wrote the CSV files to {config.TABLES_DIR} (seed {config.RANDOM_SEED}):"
        )
        for table_name, row_count in row_counts.items():
            print(f"  {table_name:<12} {row_count:>5} rows")
    if arguments.pdfs:
        claim_ids = None
        if arguments.claim_ids:
            claim_ids = [
                claim_id.strip() for claim_id in arguments.claim_ids.split(",")
            ]
        # A full run calls the LLM for every text that is not cached (CLAUDE.md, section 10), so ask first.
        is_full_run = claim_ids is None and arguments.limit is None
        if is_full_run and not ask_yes(
            "This makes the PDFs of ALL claims and replaces data/pdfs. Continue?"
        ):
            print("Stopped. Nothing was made.")
            return
        summary = generate_pdfs(
            config.RANDOM_SEED,
            config.TABLES_DIR,
            config.GROUND_TRUTH_FILE,
            config.PDFS_DIR,
            claim_ids,
            arguments.limit,
        )
        print(
            f"Wrote {summary['documents']} PDFs ({summary['pages']} pages) to {config.PDFS_DIR}"
        )
        if summary["failed_claims"]:
            print(
                f"WARNING: {len(summary['failed_claims'])} claims failed. Run the same command again; "
                "finished texts come from the cache and cost nothing."
            )
            raise SystemExit(1)


def run_build_graph(arguments) -> None:
    """Pipeline steps 2 to 5, in order. Each step needs the nodes of the step before."""
    print(
        "This loads the tables and the PDFs of ALL claims into Neo4j. A PDF page that is not in "
        "data/cache/ costs one cheap LLM call."
    )
    if not ask_yes("Continue?"):
        print("Stopped. Nothing was loaded.")
        return
    driver = open_neo4j_driver()
    try:
        node_counts, _ = load_tables_into_graph(driver)
        print(f"2. Tables loaded: {sum(node_counts.values())} nodes.")
        summary = load_pdfs_into_graph(driver)
        print(
            f"3. PDFs loaded: {summary['claims']} claims, {summary['chunks']} chunks, "
            f"{summary['findings']} findings, {len(summary['warnings'])} warnings."
        )
        # The scores come before the communities: a community counts the newest bands of its claims.
        band_counts = save_all_scores(driver)
        print(f"4. Scores saved: {band_counts}")
        summary = load_communities_into_graph(driver, arguments.write_reports)
        print(
            f"5. Communities saved: {summary['communities']} "
            f"({summary['reports']} reports written)."
        )
        graph_map = write_graph_map(driver)
        print(f"5. Graph map written: {len(graph_map['nodes'])} node labels.")
    finally:
        driver.close()


def run_score_claim(arguments) -> None:
    claim_id, problem = check_claim_id(arguments.claim_id)
    if problem is not None:
        print(problem)
        raise SystemExit(1)
    driver = open_neo4j_driver()
    try:
        answer = get_claim_score(driver, claim_id)
    finally:
        driver.close()
    if "message" in answer:
        print(answer["message"])
        raise SystemExit(1)
    score = answer["facts"]
    print(f"{claim_id}: {score['total_score']} ({score['band']}). {score['action']}")
    print(f"Coverage: {score['coverage_pct']}% of the rules could run.")
    for rule in score["fired_rules"]:
        print(f"  fired      {rule['rule_id']:<5} {rule['fires_when']}")
    for rule in score["not_evaluated_rules"]:
        print(f"  not run    {rule['rule_id']:<5} missing: {rule['missing']}")


def run_show_rules() -> None:
    for category, category_name in CATEGORY_NAMES.items():
        print(f"\n{category}: {category_name}")
        for rule in RULES:
            if rule.category == category:
                print(f"  {rule.rule_id:<5} {rule.points:>3} points  {rule.name}")


def run_chat() -> None:
    print(
        "Ask about claims, people, documents, rings and scores. Follow-up questions are fine. "
        "Type 'exit' to stop."
    )
    graph = build_chat_workflow()
    session_id = str(uuid.uuid4())  # one chat session = one thread = one memory
    try:
        while True:
            question = input("> ").strip()
            if question.lower() in ("exit", "quit"):
                return
            if question:
                chat_turn(graph, session_id, question)
    except (KeyboardInterrupt, EOFError):
        print("\nChat ended. Nothing is remembered.")


def main() -> None:
    parser = build_argument_parser()
    arguments = parser.parse_args()
    try:
        if arguments.command == "generate-data":
            run_generate_data(arguments)
        elif arguments.command == "build-graph":
            run_build_graph(arguments)
        elif arguments.command == "score-claim":
            run_score_claim(arguments)
        elif arguments.command == "show-rules":
            run_show_rules()
        elif arguments.command == "chat":
            run_chat()
        else:
            parser.print_help()
    except (RuntimeError, ValueError, FileNotFoundError, OSError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
    except (Neo4jError, DriverError) as error:
        print(f"Error from Neo4j: {error}")
        raise SystemExit(1)
    except (KeyboardInterrupt, EOFError):
        print("\nStopped. LLM answers made so far are saved in data/cache/.")


if __name__ == "__main__":
    main()
