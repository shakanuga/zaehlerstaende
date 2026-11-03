"""Übernahme der bisherigen Excel-Liste.

Erwartete Spalten:
A Datum | B Gas | C Diff | D Foto | E Strom | F Diff | G Foto |
H Wasser | I Diff | J Foto | K Kleiner Wasserzähler | L Diff | M Foto

Die Differenzen werden nicht übernommen, sie ergeben sich aus den Ständen.
Fotos dürfen im Blatt eingebettet, als Link oder als Dateiname angegeben sein.
Links und Namen werden im Importordner anhand des Dateinamens gesucht. Gibt es
einen Namen mehrfach, entscheiden der Pfad im Link und der Ordner des Zählers.
Bleibt es unklar, wird kein Foto zugeordnet und die Vorschau nennt die Zeile.
"""
import os
import re
from datetime import date, datetime
from urllib.parse import unquote

from openpyxl import load_workbook

# Zähler, Spalte des Stands, mögliche Foto-Spalten
COLUMNS = [("gas", 2, (4,)), ("strom", 5, (7,)), ("wasser", 8, (10,)), ("wasser_klein", 11, (13, 12))]
LABELS = {"gas": "Gas", "strom": "Strom", "wasser": "Wasser Hauptzähler", "wasser_klein": "Kleiner Wasserzähler"}
FOLDER_WORDS = {"gas": ("gas",), "strom": ("strom",), "wasser": ("haupt",)}
MONTHS = {"jan": 1, "feb": 2, "mär": 3, "mar": 3, "apr": 4, "mai": 5, "may": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12}


class ImportProblem(ValueError):
    pass


def to_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip()
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text)
    if match:
        day, month, year = map(int, match.groups())
        return date(year + 2000 if year < 100 else year, month, day)
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        return date(*map(int, match.groups()))
    match = re.fullmatch(r"(\d{1,2})[./](\d{4})", text)
    if match:
        return date(int(match.group(2)), int(match.group(1)), 1)
    match = re.fullmatch(r"([A-Za-zäÄ]{3})[a-zä]*\.?\s*(\d{2,4})", text)
    if match and match.group(1).lower() in MONTHS:
        year = int(match.group(2))
        return date(year + 2000 if year < 100 else year, MONTHS[match.group(1).lower()], 1)
    return None


def to_number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 4) if value >= 0 else None
    text = re.sub(r"[^\d,.\-]", "", str(value))
    if not text or text in {"-", ".", ","}:
        return None
    # Text in einer deutschen Liste: Komma ist Dezimal, "2.100" sind Tausender.
    if "," in text or re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "").replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    return round(number, 4) if number >= 0 else None


def _basename(target):
    text = unquote(str(target or "").strip())
    return re.split(r"[\\/]", text)[-1].split("?")[0]


def _photo_index(folder):
    index = {}
    if folder and os.path.isdir(folder):
        for root, _dirs, files in os.walk(folder):
            rel = os.path.relpath(root, folder).lower()
            parts = [] if rel == "." else rel.split(os.sep)
            for name in files:
                index.setdefault(name.lower(), []).append((parts, os.path.join(root, name)))
    return index


def _tail_match(a, b):
    count = 0
    for left, right in zip(reversed(a), reversed(b)):
        if left != right:
            break
        count += 1
    return count


def _in_meter_folder(parts, key):
    text = " ".join(parts)
    if key in FOLDER_WORDS:
        return any(word in text for word in FOLDER_WORDS[key])
    return not any(word in text for words in FOLDER_WORDS.values() for word in words)


def _find_photo(index, name, link, key):
    """Liefert den Pfad, oder None, wenn nichts oder nichts Eindeutiges passt."""
    hits = index.get(name.lower(), [])
    if len(hits) <= 1:
        return hits[0][1] if hits else None
    link_parts = [p.lower() for p in re.split(r"[\\/]", unquote(str(link)))[:-1]]
    scores = [_tail_match(link_parts, parts) for parts, _path in hits]
    best = max(scores)
    if best > 0 and scores.count(best) == 1:
        return hits[scores.index(best)][1]
    by_folder = [path for parts, path in hits if _in_meter_folder(parts, key)]
    return by_folder[0] if len(by_folder) == 1 else None


def _formula_link(value):
    """Ziel aus =HYPERLINK("pfad";"Text"), sonst None."""
    if isinstance(value, str):
        match = re.match(r'=\s*(?:_xlfn\.)?HYPERLINK\(\s*"([^"]+)"', value, re.I)
        if match:
            return match.group(1)
    return None


def _header_row(ws):
    for row in range(1, min(ws.max_row, 10) + 1):
        if "datum" in str(ws.cell(row, 1).value or "").lower():
            return row
    return 0


def _embedded(ws):
    images = {}
    for image in getattr(ws, "_images", []):
        try:
            anchor = image.anchor._from
            images[(anchor.row + 1, anchor.col + 1)] = image._data()
        except (AttributeError, OSError, ValueError):
            continue
    return images


def parse(path, photo_folder=None):
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as exc:
        raise ImportProblem("Die Datei lässt sich nicht als Excel-Liste (.xlsx) öffnen.") from exc
    ws = wb.worksheets[0]
    formulas = load_workbook(path, data_only=False).worksheets[0]
    start = _header_row(ws) + 1
    index, images = _photo_index(photo_folder), _embedded(ws)
    readings, problems, missing = [], [], []
    for row in range(start, ws.max_row + 1):
        raw_date = ws.cell(row, 1).value
        values = [ws.cell(row, col).value for _k, col, _p in COLUMNS]
        if raw_date is None and all(v is None for v in values):
            continue
        day = to_date(raw_date)
        if not day:
            problems.append(f"Zeile {row}: Datum „{raw_date}“ nicht erkannt, übersprungen.")
            continue
        for key, col, photo_cols in COLUMNS:
            raw = ws.cell(row, col).value
            if raw is None or str(raw).strip() == "":
                continue
            value = to_number(raw)
            if value is None:
                problems.append(f"Zeile {row}: Wert „{raw}“ nicht erkannt, übersprungen.")
                continue
            item = {"meter": key, "read_on": day.isoformat(), "value": value, "row": row}
            for photo_col in photo_cols:
                cell = ws.cell(row, photo_col)
                if (row, photo_col) in images:
                    item["photo_bytes"] = images[(row, photo_col)]
                    item["photo_name"] = f"zeile{row}.jpg"
                    break
                link = (cell.hyperlink.target if cell.hyperlink and cell.hyperlink.target else None) \
                    or _formula_link(formulas.cell(row, photo_col).value) \
                    or (cell.value if isinstance(cell.value, str) else None)
                name = _basename(link)
                if not name:
                    continue
                found = _find_photo(index, name, link, key)
                if found:
                    with open(found, "rb") as fh:
                        item["photo_bytes"] = fh.read()
                    item["photo_name"] = name
                else:
                    missing.append(f"Zeile {row}, {LABELS[key]}: {name}")
                break
            readings.append(item)
    if not readings:
        raise ImportProblem("In der Datei wurden keine Zählerstände gefunden. Spalte A muss das Datum enthalten.")
    return {"readings": readings, "problems": problems, "missing_photos": missing}


def preview(plan, meters, existing):
    summary = {}
    for item in plan["readings"]:
        meter = meters[item["meter"]]
        row = summary.setdefault(item["meter"], {
            "name": meter["name"], "unit": meter["unit"], "count": 0, "photos": 0, "skip": 0,
            "first": item["read_on"], "last": item["read_on"], "drops": [], "_prev": None,
        })
        if (meter["id"], item["read_on"]) in existing:
            row["skip"] += 1
            continue
        row["count"] += 1
        row["photos"] += 1 if item.get("photo_bytes") else 0
        row["first"], row["last"] = min(row["first"], item["read_on"]), max(row["last"], item["read_on"])
        if row["_prev"] is not None and item["value"] < row["_prev"]:
            row["drops"].append(item["read_on"])
        row["_prev"] = item["value"]
    for row in summary.values():
        row.pop("_prev")
    return {"meters": list(summary.values()), "problems": plan["problems"][:30],
            "problem_count": len(plan["problems"]), "missing_photos": plan["missing_photos"][:30],
            "missing_count": len(plan["missing_photos"])}
