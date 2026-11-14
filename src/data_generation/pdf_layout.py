"""PDF building blocks and layouts (reportlab).

A "layout" is a small dict: font, colour, title alignment and date format.
Each repair shop, clinic and law firm gets its own layout from its ID number,
so their documents look different.

reportlab "platypus" builds a PDF from a list of "flowables": Paragraph
(text), Table, Spacer (empty space) and PageBreak. It fills the pages for us.
"""

from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src import config
from src.data_generation.document_noise import DATE_FORMATS

# Fictional organisations. Real-sounding but not real.
INSURER_NAME = "Harbor Point Mutual Auto Insurance"
POLICE_AGENCY_NAME = "Gulf Coast Metro Traffic Division"
DEFENSE_FIRM_NAME = "Ashford & Lyle LLP"

FONTS = ["Helvetica", "Times-Roman", "Courier"]
BOLD_FONTS = {
    "Helvetica": "Helvetica-Bold",
    "Times-Roman": "Times-Bold",
    "Courier": "Courier-Bold",
}
COLORS = ["#1f3a5f", "#7a1f1f", "#1f5f3a", "#5f3a1f", "#3a1f5f", "#333333", "#0f5c6e"]


def make_layout(layout_number):
    """Different parts of the number pick different styles. 3 x 7 x 2 x 5 = 210
    combinations, so each of our 74 providers gets its own look."""
    font = FONTS[layout_number % 3]
    return {
        "font": font,
        "bold_font": BOLD_FONTS[font],
        "color": colors.HexColor(COLORS[layout_number % 7]),
        "title_alignment": TA_CENTER if layout_number % 2 == 1 else TA_LEFT,
        "date_format": DATE_FORMATS[layout_number % 5],
    }


def layout_for_id(entity_id):
    """'PR-0012' -> layout number 12."""
    return make_layout(int(entity_id.split("-")[1]))


def title_block(organisation_name, document_title, subtitle_lines, layout):
    organisation_style = ParagraphStyle(
        "organisation",
        fontName=layout["bold_font"],
        fontSize=15,
        leading=19,
        textColor=layout["color"],
        alignment=layout["title_alignment"],
    )
    title_style = ParagraphStyle(
        "title",
        fontName=layout["bold_font"],
        fontSize=12,
        leading=16,
        alignment=layout["title_alignment"],
        spaceBefore=4,
    )
    small_style = ParagraphStyle(
        "small",
        fontName=layout["font"],
        fontSize=8.5,
        leading=11,
        alignment=layout["title_alignment"],
    )
    flowables = [Paragraph(escape(organisation_name), organisation_style)]
    for line in subtitle_lines:
        flowables.append(Paragraph(escape(line), small_style))
    flowables.append(Paragraph(escape(document_title), title_style))
    flowables.append(Spacer(1, 10))
    return flowables


def section_heading(text, layout):
    style = ParagraphStyle(
        "heading",
        fontName=layout["bold_font"],
        fontSize=10.5,
        leading=14,
        textColor=layout["color"],
        spaceBefore=8,
        spaceAfter=4,
    )
    return Paragraph(escape(text), style)


def field_table(field_rows, layout):
    """A two-column table: label | value."""
    table_data = []
    for label, value in field_rows:
        table_data.append([label + ":", str(value)])
    table = Table(table_data, colWidths=[1.9 * inch, 4.6 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), layout["bold_font"]),
                ("FONTNAME", (1, 0), (1, -1), layout["font"]),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def line_item_table(header, rows, layout):
    """A table with a header row, for estimates and bills. The last column is money."""
    table = Table([header] + rows, colWidths=[3.6 * inch, 1.2 * inch, 1.7 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), layout["bold_font"]),
                ("FONTNAME", (0, 1), (-1, -1), layout["font"]),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 0), (-1, 0), layout["color"]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    return table


def text_block(text, layout):
    """Free text as paragraphs. A blank line starts a new paragraph."""
    style = ParagraphStyle(
        "body", fontName=layout["font"], fontSize=9.5, leading=13, spaceAfter=6
    )
    flowables = []
    for paragraph_text in text.split("\n\n"):
        if paragraph_text.strip() == "":
            continue
        # escape() turns & < > into safe codes; reportlab reads text as simple HTML.
        safe_text = escape(paragraph_text.strip()).replace("\n", "<br/>")
        flowables.append(Paragraph(safe_text, style))
    return flowables


def money(amount):
    return f"${float(amount):,.2f}"


def draw_footer(canvas, document):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.drawString(
        0.75 * inch, 0.5 * inch, f"{config.PDF_FOOTER_TEXT}  |  Page {document.page}"
    )
    canvas.restoreState()


def write_pdf(file_path, pages):
    """Write a PDF. `pages` is a list of pages; each page is a list of flowables.
    Return the real number of pages (long text can fill more than one)."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    flowables = []
    for page_number, page in enumerate(pages):
        if page_number > 0:
            flowables.append(PageBreak())
        flowables.extend(page)
    document = SimpleDocTemplate(
        str(file_path),
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.7 * inch,
        bottomMargin=0.8 * inch,
    )
    document.build(flowables, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return document.page


# --- DEBUG SNIPPET: remove when you understand the file. ---
# Run:  .venv/bin/python -m src.data_generation.pdf_layout      (needs no Neo4j and makes no LLM call)
if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    layout = layout_for_id("PR-0012")
    print(
        "1. layout_for_id('PR-0012'):",
        layout["font"],
        layout["date_format"],
        layout["title_alignment"],
    )
    page = title_block("Debug Clinic", "Debug Bill", ["Houston, TX"], layout)
    page.append(
        field_table([("Claim number", "C-0000"), ("Phone", "713-555-0100")], layout)
    )
    page.append(
        line_item_table(
            ["Service", "Units", "Charge"], [["Exam", "1", money(250)]], layout
        )
    )
    page.extend(text_block("First paragraph.\n\nSecond paragraph.", layout))
    folder = Path(tempfile.mkdtemp())
    print(
        "2. write_pdf: pages =",
        write_pdf(folder / "debug.pdf", [page]),
        "| file:",
        folder / "debug.pdf",
    )
