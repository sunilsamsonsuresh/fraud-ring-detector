"""Read the text of a PDF, page by page (PLAN.md, Step 6).

Our PDFs are text-based, so pypdf can read the text directly. No OCR.
"""

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from src.datagen.templates import FOOTER_TEXT


def read_pdf_pages(file_path):
    """Return [{"page_number": 1, "text": "..."}, ...]. Page numbers start at 1.

    Raises RuntimeError with a clear message when the file is missing or broken.
    """
    if not file_path.exists():
        raise RuntimeError(f"PDF not found: {file_path}")
    try:
        reader = PdfReader(file_path)
        pages = []
        for index, page in enumerate(reader.pages):
            pages.append({"page_number": index + 1, "text": remove_footer(page.extract_text())})
    except (PdfReadError, OSError, ValueError) as error:
        raise RuntimeError(f"Cannot read PDF {file_path.name}: {error}")
    return pages


def remove_footer(page_text):
    # The footer is the same on every page. It carries no facts and would only add noise.
    kept_lines = []
    for line in page_text.splitlines():
        if not line.startswith(FOOTER_TEXT):
            kept_lines.append(line)
    return "\n".join(kept_lines)
