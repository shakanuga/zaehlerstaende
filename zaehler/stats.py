"""Verbrauchsrechnung.

Abgelesen wird selten genau am Monatsersten. Deshalb wird jede Differenz
gleichmäßig auf die Tage zwischen zwei Ablesungen verteilt und erst danach zu
Monaten und Jahren addiert. So zählt der Verbrauch vom 1. bis 3. November auch
dann für November, wenn erst am 3. abgelesen wurde.
"""
from calendar import monthrange
from datetime import date, timedelta


def _d(value):
    return value if isinstance(value, date) else date.fromisoformat(value)


def intervals(readings):
    """Zeiträume zwischen zwei aufeinanderfolgenden Ablesungen.

    Eine Ablesung mit new_meter=1 ist der erste Stand eines neuen Zählers:
    über diesen Wechsel hinweg gibt es keine Differenz. Sinkt der Stand ohne
    Wechsel-Markierung, wird der Zeitraum als Fehler markiert und nicht gezählt.
    """
    rows = sorted(readings, key=lambda r: str(r["read_on"]))
    out = []
    for prev, cur in zip(rows, rows[1:]):
        if cur["new_meter"]:
            continue
        start, end = _d(prev["read_on"]), _d(cur["read_on"])
        days = (end - start).days
        if days <= 0:
            continue
        delta = round(cur["value"] - prev["value"], 4)
        out.append({
            "start": start.isoformat(), "end": end.isoformat(), "days": days,
            "delta": delta, "per_day": round(delta / days, 4),
            "ok": delta >= 0, "reading_id": cur["id"] if "id" in cur.keys() else None,
        })
    return out


def daily(ivs):
    """Verbrauch je Kalendertag. Der Ablesetag selbst zählt zum neuen Zeitraum."""
    days = {}
    for iv in ivs:
        if not iv["ok"]:
            continue
        day, end = _d(iv["start"]), _d(iv["end"])
        rate = iv["delta"] / iv["days"]
        while day < end:
            days[day] = rate
            day += timedelta(days=1)
    return days


def months(days):
    grouped = {}
    for day, rate in days.items():
        item = grouped.setdefault((day.year, day.month), [0.0, 0])
        item[0] += rate
        item[1] += 1
    out = []
    for (year, month), (total, covered) in sorted(grouped.items()):
        length = monthrange(year, month)[1]
        out.append({
            "month": f"{year}-{month:02d}", "year": year, "m": month,
            "value": round(total, 3), "days": covered, "days_in_month": length,
            "per_day": round(total / covered, 3), "full": covered == length,
        })
    return out


def years(days):
    grouped = {}
    for day, rate in days.items():
        item = grouped.setdefault(day.year, [0.0, 0])
        item[0] += rate
        item[1] += 1
    out = []
    for year, (total, covered) in sorted(grouped.items()):
        length = 366 if monthrange(year, 2)[1] == 29 else 365
        out.append({
            "year": year, "value": round(total, 3), "days": covered,
            "days_in_year": length, "per_day": round(total / covered, 3),
            "full": covered == length,
        })
    return out


def year_to_date(days):
    """Dieses Jahr bis zum letzten bekannten Tag gegen denselben Zeitraum im Vorjahr."""
    if not days:
        return None
    last = max(days)
    this_start = date(last.year, 1, 1)
    try:
        prev_last = last.replace(year=last.year - 1)
    except ValueError:  # 29. Februar
        prev_last = date(last.year - 1, 2, 28)
    prev_start = date(last.year - 1, 1, 1)

    def span(a, b):
        hit = [days[a + timedelta(n)] for n in range((b - a).days + 1) if a + timedelta(n) in days]
        return sum(hit), len(hit), (b - a).days + 1

    cur, cur_n, cur_len = span(this_start, last)
    prev, prev_n, prev_len = span(prev_start, prev_last)
    result = {
        "year": last.year, "until": last.isoformat(), "value": round(cur, 3),
        "complete": cur_n == cur_len, "prev_value": None, "pct": None,
    }
    if cur_n == cur_len and prev_n == prev_len:
        result["prev_value"] = round(prev, 3)
        if prev > 0:
            result["pct"] = round((cur - prev) / prev * 100, 1)
    return result


def compare_parent(sub_days, main_days):
    """Unterzähler gegen Hauptzähler, nur für Monate, die beide vollständig abdecken."""
    sub_m = {m["month"]: m for m in months(sub_days)}
    main_m = {m["month"]: m for m in months(main_days)}
    rows = []
    for key in sorted(set(sub_m) & set(main_m)):
        sub, main = sub_m[key], main_m[key]
        if not (sub["full"] and main["full"]):
            continue
        share = round(sub["value"] / main["value"] * 100, 1) if main["value"] > 0 else None
        rows.append({
            "month": key, "sub": sub["value"], "main": main["value"], "share": share,
            "stuck": sub["value"] == 0 and main["value"] > 0, "low": False,
        })
    shares = sorted(r["share"] for r in rows if r["share"] is not None)
    if len(shares) >= 4:
        usual = shares[len(shares) // 2]
        for row in rows:
            row["low"] = row["share"] is not None and not row["stuck"] and row["share"] < usual * 0.4
    return rows


def summary(readings):
    ivs = intervals(readings)
    days = daily(ivs)
    return {
        "intervals": ivs,
        "months": months(days),
        "years": years(days),
        "ytd": year_to_date(days),
        "per_day": round(sum(days.values()) / len(days), 3) if days else None,
        "bad_intervals": sum(1 for iv in ivs if not iv["ok"]),
    }


def plausibility(value, read_on, new_meter, previous, following, recent):
    """Hinweise vor dem Speichern. previous/following sind Nachbar-Ablesungen."""
    out = []
    if previous and not new_meter and value < previous["value"]:
        out.append({
            "code": "lower",
            "text": f"Der Stand ist kleiner als am {_de(previous['read_on'])}. "
                    "Tippfehler, oder wurde der Zähler getauscht?",
        })
    if following and not following["new_meter"] and value > following["value"]:
        out.append({
            "code": "higher_than_next",
            "text": f"Der Stand ist größer als die spätere Ablesung vom {_de(following['read_on'])}.",
        })
    if previous and not new_meter and value >= previous["value"]:
        days = (_d(read_on) - _d(previous["read_on"])).days
        rates = sorted(iv["per_day"] for iv in recent if iv["ok"])
        if days > 0 and len(rates) >= 3:
            usual = rates[len(rates) // 2]
            now = (value - previous["value"]) / days
            if usual > 0 and now > usual * 3:
                out.append({
                    "code": "high",
                    "text": f"Das wären {now:.2f} pro Tag, üblich sind etwa {usual:.2f}. "
                            "Bitte den Stand noch einmal prüfen.",
                })
    return out


def _de(iso):
    d = _d(iso)
    return f"{d.day:02d}.{d.month:02d}.{d.year}"
