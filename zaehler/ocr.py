"""Optionale Erkennung des Zählerstands aus dem Foto.

Standard ist aus. Das Ergebnis ist immer nur ein Vorschlag, den ein Mensch
bestätigt. Gespeichert wird nie automatisch.

OCR_PROVIDER=anthropic  ANTHROPIC_API_KEY=...  (Foto geht an die Claude API)
OCR_PROVIDER=ollama     OLLAMA_URL=http://...:11434  OLLAMA_MODEL=... (bleibt zu Hause)
"""
import base64
import io
import json
import os
import re
import urllib.error
import urllib.request

from PIL import Image, ImageOps

TIMEOUT = 60


def provider():
    name = os.environ.get("OCR_PROVIDER", "").strip().lower()
    if name == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return name
    if name == "ollama" and os.environ.get("OLLAMA_URL") and os.environ.get("OLLAMA_MODEL"):
        return name
    return None


def _jpeg(data):
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1400, 1400))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
    return base64.b64encode(out.getvalue()).decode()


def _prompt(meter, last_value):
    hint = f" Der letzte bekannte Stand war {last_value}." if last_value is not None else ""
    return (
        f"Auf dem Foto ist ein Zähler: {meter['name']}, Einheit {meter['unit']}, "
        f"{meter['decimals']} Nachkommastellen (oft rote Ziffern oder Rollen).{hint} "
        "Lies das Zählwerk Ziffer für Ziffer ab. Ignoriere Seriennummern und Typenschild. "
        'Antworte nur mit JSON: {"value": 12345.678}. '
        'Wenn das Zählwerk nicht sicher lesbar ist: {"value": null}.'
    )


def _post(url, payload, headers):
    req = urllib.request.Request(url, json.dumps(payload).encode(), headers, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
        return json.load(res)


def _value(text):
    match = re.search(r"\{.*?\}", text or "", re.S)
    if not match:
        return None
    try:
        value = json.loads(match.group(0)).get("value")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def recognize(data, meter, last_value=None):
    """Liefert eine Zahl oder None. Netzfehler dürfen das Erfassen nie blockieren."""
    name = provider()
    if not name:
        return None
    try:
        image, prompt = _jpeg(data), _prompt(meter, last_value)
        if name == "anthropic":
            res = _post(
                os.environ.get("ANTHROPIC_URL", "https://api.anthropic.com") + "/v1/messages",
                {
                    "model": os.environ.get("OCR_MODEL", "claude-haiku-5-5"),
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
                        {"type": "text", "text": prompt},
                    ]}],
                },
                {"content-type": "application/json", "x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01"},
            )
            return _value("".join(b.get("text", "") for b in res.get("content", [])))
        res = _post(
            os.environ["OLLAMA_URL"].rstrip("/") + "/api/generate",
            {"model": os.environ["OLLAMA_MODEL"], "prompt": prompt, "images": [image],
             "stream": False, "format": "json"},
            {"content-type": "application/json"},
        )
        return _value(res.get("response", ""))
    except (urllib.error.URLError, OSError, ValueError, KeyError, TimeoutError):
        return None
