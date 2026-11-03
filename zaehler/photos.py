"""Fotos ablegen: Original bleibt byte-genau erhalten, Vorschauen werden abgeleitet."""
import hashlib
import io
import os
import uuid
from datetime import datetime

from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

MAX_BYTES = 30 * 1024 * 1024
SIZES = {"thumb": 420, "view": 1800}
EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "HEIF": "heic", "MPO": "jpg"}


class PhotoError(ValueError):
    pass


def inspect(data):
    """Prüft, ob es ein Bild ist, und liefert (Format, Aufnahmezeit)."""
    if len(data) > MAX_BYTES:
        raise PhotoError("Das Foto ist größer als 30 MB.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            return img.format, _taken_at(img)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise PhotoError("Die Datei ist kein lesbares Bild.") from exc


def _taken_at(img):
    try:
        exif = img.getexif()
        sub = exif.get_ifd(ExifTags.IFD.Exif)
        raw = sub.get(ExifTags.Base.DateTimeOriginal) or exif.get(ExifTags.Base.DateTime)
        if raw:
            return datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S").isoformat()
    except (ValueError, KeyError, AttributeError, TypeError):
        pass
    return None


def store(data_dir, data, original_name=""):
    fmt, taken_at = inspect(data)
    ext = EXTENSIONS.get(fmt)
    if not ext:
        raise PhotoError("Dieses Bildformat wird nicht unterstützt.")
    now = datetime.now()
    rel = os.path.join(f"{now.year}", f"{uuid.uuid4().hex}.{ext}")
    full = os.path.join(data_dir, "photos", rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data)
    os.chmod(full, 0o440)
    return {
        "path": rel, "original_name": os.path.basename(original_name or "")[:200],
        "mime": Image.MIME.get(fmt, "image/jpeg") if fmt != "HEIF" else "image/heic",
        "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "taken_at": taken_at,
    }


def derived(data_dir, photo_id, rel_path, size):
    """Vorschau als JPEG, wird beim ersten Abruf erzeugt."""
    target = os.path.join(data_dir, "derived", f"{photo_id}_{size}.jpg")
    if os.path.exists(target):
        return target
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with Image.open(os.path.join(data_dir, "photos", rel_path)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((SIZES[size], SIZES[size]))
        tmp = f"{target}.{uuid.uuid4().hex}.tmp"
        img.save(tmp, "JPEG", quality=84, optimize=True)
    os.replace(tmp, target)
    return target
