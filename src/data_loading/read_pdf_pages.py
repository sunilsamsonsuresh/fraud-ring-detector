"""Read the text of a PDF, page by page.

Our PDFs are text-based, so the library pypdf reads the text directly. No OCR (reading of pictures).
Every later PDF step starts with this file: chunks, entities and findings all work on one page at a time,
so each fact can keep its page number (CLAUDE.md, rule 6).
"""

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src import config


def remove_footer(page_text):
    """Remove the footer line. It is the same on every page, carries no facts and only adds noise."""
    kept_lines = []
    for line in page_text.splitlines():
        if not line.startswith(config.PDF_FOOTER_TEXT):
            kept_lines.append(line)
    return "\n".join(kept_lines)


def read_pdf_pages(file_path):
    """Return [{"page_number": 1, "text": "..."}, ...]. Page numbers start at 1.

    Raises RuntimeError with a clear message when the file is missing or broken."""
    if not file_path.exists():
        raise RuntimeError(f"PDF not found: {file_path}")
    pages = []
    try:
        reader = PdfReader(file_path)
        for index, page in enumerate(reader.pages):
            pages.append(
                {"page_number": index + 1, "text": remove_footer(page.extract_text())}
            )
    except (PdfReadError, OSError, ValueError) as error:
        raise RuntimeError(f"Cannot read PDF {file_path.name}: {error}")
    return pages


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run with "Debug the open file", or:  .venv/bin/python -m src.data_loading.read_pdf_pages
# It needs no Neo4j.
if __name__ == "__main__":
    pdf_path = config.PDFS_DIR / "C-1088" / "C-1088_adjuster_file.pdf"
    pages = read_pdf_pages(pdf_path)
    print(
        f"{pdf_path.name} has {len(pages)} page(s). First page, first 300 characters:"
    )
    print(pages[0]["text"][:300])
