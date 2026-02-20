"""Packing list PDF generator.

Generates a 4x6 inch packing list for Rollo thermal printer.
"""

import logging
from pathlib import Path

from reportlab.lib.pagesizes import inch
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

# 4x6 inch label size
LABEL_WIDTH = 4 * inch
LABEL_HEIGHT = 6 * inch


def generate_packing_list(order: dict, output_path: Path) -> Path:
    """Generate a packing list PDF from an eBay order.

    Returns the path to the generated PDF.
    """
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=(LABEL_WIDTH, LABEL_HEIGHT),
        leftMargin=0.2 * inch,
        rightMargin=0.2 * inch,
        topMargin=0.2 * inch,
        bottomMargin=0.2 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PackingTitle",
        parent=styles["Heading1"],
        fontSize=14,
        spaceAfter=6,
    )
    normal_style = ParagraphStyle(
        "PackingNormal",
        parent=styles["Normal"],
        fontSize=9,
        spaceAfter=2,
    )
    small_style = ParagraphStyle(
        "PackingSmall",
        parent=styles["Normal"],
        fontSize=7,
        spaceAfter=2,
    )

    elements = []

    # Title
    elements.append(Paragraph("PACKING LIST", title_style))
    elements.append(Spacer(1, 4))

    # Order info
    order_id = order.get("orderId", "N/A")
    creation_date = order.get("creationDate", "N/A")
    if "T" in creation_date:
        creation_date = creation_date.split("T")[0]

    elements.append(Paragraph(f"Order: {order_id}", normal_style))
    elements.append(Paragraph(f"Date: {creation_date}", normal_style))
    elements.append(Spacer(1, 6))

    # Ship to
    fulfillment = order.get("fulfillmentStartInstructions", [{}])
    if fulfillment:
        ship_to = fulfillment[0].get("shippingStep", {}).get("shipTo", {})
        name = ship_to.get("fullName", "N/A")
        address = ship_to.get("contactAddress", {})
        line1 = address.get("addressLine1", "")
        line2 = address.get("addressLine2", "")
        city = address.get("city", "")
        state = address.get("stateOrProvince", "")
        postal = address.get("postalCode", "")

        elements.append(Paragraph("<b>Ship To:</b>", normal_style))
        elements.append(Paragraph(name, normal_style))
        if line1:
            elements.append(Paragraph(line1, normal_style))
        if line2:
            elements.append(Paragraph(line2, normal_style))
        elements.append(Paragraph(f"{city}, {state} {postal}", normal_style))
    elements.append(Spacer(1, 8))

    # Line items table
    line_items = order.get("lineItems", [])
    table_data = [["Qty", "SKU", "Item"]]
    for item in line_items:
        qty = str(item.get("quantity", 1))
        sku = item.get("sku", "N/A")
        title = item.get("title", "N/A")
        # Truncate long titles
        if len(title) > 30:
            title = title[:27] + "..."
        table_data.append([qty, sku, title])

    table = Table(table_data, colWidths=[0.4 * inch, 1.0 * inch, 2.0 * inch])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, "black"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 8))

    # Total
    total = order.get("pricingSummary", {}).get("total", {}).get("value", "0.00")
    currency = order.get("pricingSummary", {}).get("total", {}).get("currency", "USD")
    elements.append(Paragraph(f"<b>Total: ${total} {currency}</b>", normal_style))

    # Footer
    elements.append(Spacer(1, 12))
    elements.append(Paragraph("Thank you for your purchase!", small_style))
    elements.append(Paragraph("Longracks Labs", small_style))

    doc.build(elements)
    logger.info("Packing list generated: %s", output_path)
    return output_path
