"""Step 3 of loading the graph: one Document node for each PDF.

The list of all PDFs is the file data/pdfs/documents.csv (made by the data generator). Each row says
which claim a PDF belongs to, its type, its file name and its number of pages.

The chunks, the entities and the findings are all linked to a Document node. So this step comes first.
It needs the Claim nodes (load_tables_into_graph.py), because each Document is linked to its claim.
"""

import csv

from neo4j import Driver

from src import config
from src.data_loading import pdf_loading_queries as queries


def read_document_list(pdfs_dir=config.PDFS_DIR):
    """The rows of documents.csv: document_id, claim_id, document_type, file_name, page_count."""
    documents_file = pdfs_dir / "documents.csv"
    if not documents_file.exists():
        raise RuntimeError(
            f"{documents_file} is missing. The data generator makes the PDFs and this list."
        )
    with open(documents_file, newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def documents_of_claim(document_rows, claim_id):
    """The rows for one claim."""
    return [row for row in document_rows if row["claim_id"] == claim_id]


def load_documents_into_graph(driver: Driver, document_rows):
    """Save one Document node for each row. Return the number of rows saved."""
    for row in document_rows:
        driver.execute_query(
            queries.SAVE_DOCUMENT,
            claim_id=row["claim_id"],
            document_id=row["document_id"],
            document_type=row["document_type"],
            file_name=row["file_name"],
            page_count=int(row["page_count"]),
        )
    return len(document_rows)


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file". It only READS documents.csv. It needs no Neo4j and writes nothing.
if __name__ == "__main__":
    rows = read_document_list()
    print("PDFs in the list:", len(rows))
    print("The PDFs of claim C-1088:")
    for row in documents_of_claim(rows, "C-1088"):
        print(
            "  ",
            row["document_id"],
            "|",
            row["document_type"],
            "|",
            row["page_count"],
            "page(s)",
        )
