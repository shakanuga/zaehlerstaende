"""Excel-Export im Aufbau der bisherigen Liste und PDF-Nachweis mit Fotos."""
import json
import os
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image as RLImage, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)


FONTS = os.path.join(os.path.dirname(__file__), "fonts")
pdfmetrics.registerFont(TTFont("Plain", os.path.join(FONTS, "pdf.ttf")))
pdfmetrics.registerFont(TTFont("Plain-Bold", os.path.join(FONTS, "pdf-bold.ttf")))


def de_date(iso):
    if not iso:
        return ""
    d = date.fromisoformat(iso[:10])
    return f"{d.day:02d}.{d.month:02d}.{d.year}"


def de_datetime(iso):
    if not iso:
        return "nicht im Foto gespeichert"
    d = datetime.fromisoformat(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}, {d.hour:02d}:{d.minute:02d} Uhr"


def de_num(value, decimals):
    if value is None:
        return ""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "§").replace(".", ",").replace("§", ".")


def workbook(data, base_url, folder):
    wb = Workbook()
    ws = wb.active
    ws.title = "Zählerstände"
    head_fill = PatternFill("solid", fgColor="DDE1DE")
    headers = ["Datum"]
    for block in data:
        m = block["meter"]
        headers += [f"{m['name']} ({m['unit']})", f"Differenz ({m['unit']})", "Foto"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True), head_fill
        cell.alignment = Alignment(wrap_text=True, vertical="center")

    # Eine Zeile je Monat, wie in der bisherigen Liste.
    rounds = {}
    for pos, block in enumerate(data):
        for r in block["readings"]:
            rounds.setdefault((r["read_on"][:7]), {}).setdefault(pos, []).append(r)
    row_no = 2
    for month in sorted(rounds):
        depth = max(len(v) for v in rounds[month].values())
        for n in range(depth):
            entries = {pos: items[n] for pos, items in rounds[month].items() if n < len(items)}
            first = min(e["read_on"] for e in entries.values())
            cell = ws.cell(row_no, 1, date.fromisoformat(first))
            cell.number_format = "DD.MM.YYYY"
            for pos, entry in entries.items():
                dec = data[pos]["meter"]["decimals"]
                col = 2 + pos * 3
                fmt = "#,##0" + ("." + "0" * dec if dec else "")
                ws.cell(row_no, col, entry["value"]).number_format = fmt
                if entry["delta"] is not None:
                    ws.cell(row_no, col + 1, entry["delta"]).number_format = fmt
                if entry["photo"]:
                    link = ws.cell(row_no, col + 2, "Foto")
                    link.hyperlink = f"{base_url}/api/photos/{entry['photo']}/original"
                    link.font = Font(color="0B5CAD", underline="single")
            row_no += 1
    ws.freeze_panes = "B2"
    ws.column_dimensions["A"].width = 12
    for col in range(2, len(headers) + 1):
        ws.column_dimensions[get_column_letter(col)].width = 8 if headers[col - 1] == "Foto" else 14

    exact = wb.create_sheet("Alle Ablesungen")
    exact.append(["Zähler", "Einheit", "Datum", "Stand", "Differenz", "Tage", "Pro Tag", "Zähler getauscht",
                  "Notiz", "Foto aufgenommen", "SHA-256 des Fotos"])
    for cell in exact[1]:
        cell.font, cell.fill = Font(bold=True), head_fill
    for block in data:
        m = block["meter"]
        for r in block["readings"]:
            p = r["photo_row"] or {}
            exact.append([m["name"], m["unit"], date.fromisoformat(r["read_on"]), r["value"], r["delta"], r["days"],
                          r["per_day"], "ja" if r["new_meter"] else "", r["note"], p.get("taken_at") or "",
                          p.get("sha256") or ""])
            exact.cell(exact.max_row, 3).number_format = "DD.MM.YYYY"
    for letter, width in zip("ABCDEFGHIJK", (24, 8, 12, 13, 12, 7, 9, 10, 24, 20, 66)):
        exact.column_dimensions[letter].width = width
    exact.freeze_panes = "A2"
    path = os.path.join(folder, "zaehlerstaende.xlsx")
    wb.save(path)
    return path


def proof_pdf(block, changes, start, end, author, photo_path, folder):
    meter, readings = block["meter"], block["readings"]
    dec = meter["decimals"]
    title = ParagraphStyle("t", fontName="Plain-Bold", fontSize=18, leading=22, spaceAfter=4)
    text = ParagraphStyle("b", fontName="Plain", fontSize=9, leading=13.5)
    small = ParagraphStyle("s", fontName="Plain", fontSize=8, leading=11, textColor=colors.HexColor("#46504F"))
    head = ParagraphStyle("h", fontName="Plain-Bold", fontSize=11.5, leading=15, spaceBefore=12, spaceAfter=5)
    span = f"{de_date(readings[0]['read_on'])} bis {de_date(readings[-1]['read_on'])}"
    story = [
        Paragraph(f"Zählerstände {_esc(meter['name'])}", title),
        Paragraph(f"Zeitraum {span}, {len(readings)} Ablesungen"
                  + (f", Zählernummer {_esc(meter['number'])}" if meter["number"] else ""), text),
        Paragraph(f"Erstellt am {de_date(date.today().isoformat())} von {_esc(author)}", text),
        Spacer(1, 8),
    ]
    rows = [["Datum", f"Stand ({meter['unit']})", f"Differenz ({meter['unit']})", "Tage", "Pro Tag", "Foto"]]
    for r in readings:
        rows.append([de_date(r["read_on"]), de_num(r["value"], dec),
                     "neuer Zähler" if r["new_meter"] else de_num(r["delta"], dec),
                     r["days"] or "", de_num(r["per_day"], 3), "ja" if r["photo_row"] else "nein"])
    table = Table(rows, repeatRows=1, colWidths=[26 * mm, 34 * mm, 34 * mm, 14 * mm, 24 * mm, 16 * mm])
    table.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Plain-Bold", 8.5), ("FONT", (0, 1), (-1, -1), "Plain", 8.5),
        ("ALIGN", (1, 0), (4, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#B7BEBB")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story += [table, Spacer(1, 8), Paragraph(
        "Die Differenz ist der Abstand zur vorherigen Ablesung. Die Fotos stehen auf den folgenden Seiten. "
        "Zu jedem Foto ist die SHA-256-Prüfsumme der unveränderten Originaldatei angegeben.", small)]
    if changes:
        story.append(Paragraph("Nachträgliche Änderungen", head))
        for c in changes:
            old, new = json.loads(c["old_json"] or "{}"), json.loads(c["new_json"] or "{}")
            names = {"value": "Stand", "read_on": "Datum", "new_meter": "Zählertausch", "note": "Notiz"}
            parts = [f"{names.get(k, k)}: {old.get(k)} zu {new.get(k)}" for k in new if old.get(k) != new.get(k)]
            story.append(Paragraph(
                f"{de_datetime(c['at'])}, {_esc(c['user_name'])}, Ablesung {de_date(c['read_on'])}: "
                f"{_esc('; '.join(parts))}" + (f" ({_esc(c['reason'])})" if c["reason"] else ""), small))
    with_photo = [r for r in readings if r["photo_row"]]
    if with_photo:
        story.append(PageBreak())
        story.append(Paragraph("Fotos", title))
    for r in with_photo:
        p = r["photo_row"]
        try:
            path = photo_path(p["id"], p["path"])
            w, h = ImageReader(path).getSize()
        except OSError:
            continue
        scale = min(170 * mm / w, 105 * mm / h)
        story.append(KeepTogether([
            Paragraph(f"{de_date(r['read_on'])}: {de_num(r['value'], dec)} {meter['unit']}", head),
            RLImage(path, width=w * scale, height=h * scale, hAlign="LEFT"), Spacer(1, 3),
            Paragraph(f"Aufnahme laut Foto: {de_datetime(p['taken_at'])}<br/>"
                      f"Eingetragen: {de_datetime(p['uploaded_at'])}<br/>SHA-256: {p['sha256']}", small),
            Spacer(1, 6),
        ]))

    def footer(canvas, doc):
        canvas.setFont("Plain", 8)
        canvas.setFillColor(colors.HexColor("#46504F"))
        canvas.drawString(20 * mm, 11 * mm, f"Zählerstände {meter['name']}")
        canvas.drawRightString(190 * mm, 11 * mm, f"Seite {doc.page}")

    path = os.path.join(folder, "nachweis.pdf")
    SimpleDocTemplate(path, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                      bottomMargin=18 * mm, title=f"Zählerstände {meter['name']}").build(
        story, onFirstPage=footer, onLaterPages=footer)
    return path


def _esc(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
