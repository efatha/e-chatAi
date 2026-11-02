"""Local image reading. Pixels plus the words Windows can read in a PNG or JPEG."""

import base64
import binascii
import re
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

_IMAGE_TYPES = {
    "image/png": "PNG",
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/gif": "GIF",
    "image/webp": "WebP",
    "image/bmp": "BMP",
}


def interpret_image(file, question=""):
    """Describe an uploaded image from its pixels, tied to the user's question."""
    if not isinstance(file, dict) or not file.get("data"):
        return None
    mime = str(file.get("mime_type") or "").lower()
    if mime and not mime.startswith("image/"):
        return None
    try:
        raw = base64.b64decode(file["data"], validate=False)
    except (binascii.Error, ValueError):
        return None
    if not raw:
        return None
    decoded = _pixels(raw)
    if not decoded:
        return (
            "I received an image, but this local reader could not open that file. "
            "PNG and JPEG are the formats I can measure."
        )
    pixels, width, height = decoded
    intent = _intent(question)
    lines = []
    if intent == "meaning":
        lines = _read_text(_smaller_png(pixels, width, height), "image/png")
    return _describe(
        pixels, width, height, _IMAGE_TYPES.get(mime, "image"), question, lines, intent
    )


def _intent(question):
    """Meaning questions need the writing. Describe questions need the colors."""
    lowered = (question or "").lower()
    if re.search(r"\b(describe|talk about|talk|color|colour|looks|adjective)\b", lowered):
        return "describe"
    return "meaning"


def _smaller_png(pixels, width, height):
    """A shorter PNG so text reading does not scan every original pixel."""
    step = max(1, max(width, height) // 720)
    new_width = max(1, width // step)
    new_height = max(1, height // step)
    raw_rows = bytearray()
    for y in range(new_height):
        raw_rows.append(0)
        source = (y * step) * width
        for x in range(new_width):
            red, green, blue = pixels[source + x * step]
            raw_rows.extend((red, green, blue))
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", new_width, new_height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw_rows), level=1))
    png += chunk(b"IEND", b"")
    return png


def image_question(text):
    """A follow-up that still refers to the uploaded picture."""
    lowered = (text or "").lower()
    return bool(re.search(
        r"\b(image|picture|photo|screenshot|slide|written|writing|text|words|read|say|says)\b",
        lowered,
    ))


def explain_saved_image(question, saved_text):
    """Answer a later question from the words already read on the image."""
    lines = [line.strip() for line in str(saved_text or "").splitlines() if line.strip()]
    if not lines:
        return (
            "I don't still have the words from an uploaded image. "
            "Upload the PNG or JPEG again and ask me what is written."
        )
    if _intent(question) == "describe":
        return (
            "Ask me to describe this image with the picture attached. "
            "That reply names the colors and does not wait to read the writing."
        )
    quoted = "\n".join(f"• {line}" for line in lines)
    heading = lines[0]
    rest = lines[1:]
    extra = ""
    if rest:
        extra = " The other important lines are " + "; ".join(rest) + "."
    return (
        f"This image is a title card. The main writing says “{heading}”. "
        f"In plain words, that line is the subject of the picture.{extra}\n"
        f"The words I read are:\n{quoted}"
    )


def _pixels(raw):
    via_pillow = _pillow_pixels(raw)
    if via_pillow:
        return via_pillow
    return _png_pixels(raw)


def _pillow_pixels(raw):
    try:
        from io import BytesIO
        from PIL import Image
    except ImportError:
        return None
    try:
        image = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        return None
    width, height = image.size
    if width < 1 or height < 1:
        return None
    step = max(1, int((width * height / 4000) ** 0.5))
    pixels = [
        image.getpixel((x, y))
        for y in range(0, height, step)
        for x in range(0, width, step)
    ]
    return pixels, width, height


def _png_pixels(raw):
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos = 8
    width = height = bit_depth = color_type = None
    compressed = bytearray()
    while pos + 8 <= len(raw):
        length = int.from_bytes(raw[pos:pos + 4], "big")
        kind = raw[pos + 4:pos + 8]
        chunk = raw[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", chunk[:10])
        elif kind == b"IDAT":
            compressed.extend(chunk)
        elif kind == b"IEND":
            break
    if not width or not height or bit_depth != 8 or color_type not in (0, 2, 6):
        return None
    channels = {0: 1, 2: 3, 6: 4}[color_type]
    try:
        inflated = zlib.decompress(bytes(compressed))
    except zlib.error:
        return None
    stride = width * channels
    if len(inflated) < height * (stride + 1):
        return None
    rows = []
    cursor = 0
    previous = bytearray(stride)
    for _ in range(height):
        filter_type = inflated[cursor]
        cursor += 1
        row = bytearray(inflated[cursor:cursor + stride])
        cursor += stride
        for index in range(stride):
            left = row[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                row[index] = (row[index] + left) & 255
            elif filter_type == 2:
                row[index] = (row[index] + up) & 255
            elif filter_type == 3:
                row[index] = (row[index] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                row[index] = (row[index] + _paeth(left, up, upper_left)) & 255
        previous = row
        rows.append(row)
    pixels = []
    for row in rows:
        for index in range(0, stride, channels):
            if channels == 1:
                value = row[index]
                pixels.append((value, value, value))
            else:
                pixels.append((row[index], row[index + 1], row[index + 2]))
    return pixels, width, height


def _paeth(left, up, upper_left):
    estimate = left + up - upper_left
    distances = (
        abs(estimate - left),
        abs(estimate - up),
        abs(estimate - upper_left),
    )
    return (left, up, upper_left)[distances.index(min(distances))]


def _read_text(raw, mime):
    suffix = ".png" if "png" in mime or raw[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
    script = Path(__file__).with_name("ocr_windows.ps1")
    if not script.exists():
        return []
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(raw)
            temp_path = handle.name
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Path",
                temp_path,
            ],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
    lines = []
    for line in (completed.stdout or "").splitlines():
        clean = " ".join(line.split())
        if clean and clean not in lines:
            lines.append(clean)
    return lines[:12]


def _describe(pixels, width, height, kind, question, lines, intent="meaning"):
    count = len(pixels) or 1
    brightness = sum(sum(pixel) / 3 for pixel in pixels) / count
    colorful = sum(
        max(pixel) - min(pixel) for pixel in pixels
    ) / count
    changes = 0
    compared = 0
    columns = max(1, int(len(pixels) / max(height, 1)) or 1)
    for index, pixel in enumerate(pixels[:-1]):
        if (index + 1) % columns == 0:
            continue
        compared += 1
        neighbor = pixels[index + 1]
        if sum(abs(pixel[channel] - neighbor[channel]) for channel in range(3)) > 40:
            changes += 1
    busy = changes / compared if compared else 0
    sample = pixels[::max(1, len(pixels) // 2500)]
    fields = _color_fields(sample)
    main_name = fields[0][0]
    adjective = _adjective(main_name, brightness, colorful)
    field_line = _field_sentence(fields)
    asked = " ".join((question or "").split())
    if intent == "describe":
        return (
            f"The local image reader sees a {adjective} graphic. "
            f"{field_line} "
            f"It is a {width} by {height} {kind}."
        )
    if lines:
        quoted = "\n".join(f"• {line}" for line in lines)
        heading = lines[0]
        rest = lines[1:]
        extra = ""
        if rest:
            extra = " The other important lines are " + "; ".join(rest) + "."
        return (
            f"This image is a title card. The main writing says “{heading}”. "
            f"In plain words, that line is the subject of the picture.{extra}\n"
            f"The words I read are:\n{quoted}"
        )
    if asked:
        opening = f"I looked at the image for “{asked[:160]}”, but I could not read any words in it."
    else:
        opening = "I looked at the image, but I could not read any words in it."
    return (
        f"{opening} "
        f"The local image reader sees a {adjective} graphic. "
        f"{field_line} "
        f"It is a {width} by {height} {kind}."
    )


def _color_fields(pixels):
    """Name each large color region from the fixed palette, largest first."""
    totals = {}
    counts = {}
    for red, green, blue in pixels:
        name = _nearest_name((red, green, blue))
        totals[name] = totals.get(name, 0) + 1
        bucket = counts.setdefault(name, [0, 0, 0, 0])
        bucket[0] += red
        bucket[1] += green
        bucket[2] += blue
        bucket[3] += 1
    ranked = sorted(totals, key=totals.get, reverse=True)
    fields = []
    total = len(pixels) or 1
    for name in ranked:
        share = totals[name] / total
        if share < 0.04 and fields:
            continue
        fields.append((name, share))
        if len(fields) == 4:
            break
    return fields or [("Charcoal Gray", 1.0)]


def _field_sentence(fields):
    main, share = fields[0]
    percent = round(share * 100)
    extras = [name for name, _share in fields[1:]]
    sentence = f"The main field is {main}, about {percent}% of the picture."
    if extras:
        sentence += " Also present: " + ", ".join(extras) + "."
    return sentence


def _adjective(name, brightness, colorful):
    lowered = name.lower()
    if any(word in lowered for word in ("navy", "midnight", "charcoal", "obsidian", "jet", "black")):
        tone = "dark"
    elif brightness > 185:
        tone = "light"
    elif colorful > 80:
        tone = "vivid"
    else:
        tone = "quiet"
    return f"{tone} {name.lower()}"


def _nearest_name(color):
    red, green, blue = color
    return min(
        _COLOR_CATALOG,
        key=lambda name: sum(
            (channel - target) ** 2
            for channel, target in zip((red, green, blue), _COLOR_CATALOG[name])
        ),
    )


# Names are fixed. A measured pixel may only be called one of these.
_COLOR_CATALOG = {
    "Red": (210, 35, 35),
    "Blue": (35, 80, 210),
    "Yellow": (240, 220, 40),
    "Green": (40, 160, 55),
    "Orange": (230, 120, 25),
    "Purple": (130, 45, 175),
    "Pink": (235, 145, 175),
    "Brown": (120, 72, 40),
    "Black": (12, 12, 12),
    "White": (248, 248, 248),
    "Gray": (128, 128, 128),
    "Light Blue": (165, 205, 240),
    "Sky Blue": (120, 185, 230),
    "Baby Blue": (185, 220, 245),
    "Powder Blue": (175, 215, 230),
    "Light Green": (150, 220, 160),
    "Mint Green": (150, 230, 195),
    "Pale Yellow": (250, 240, 170),
    "Lavender": (200, 175, 230),
    "Peach": (250, 190, 155),
    "Cream": (250, 240, 215),
    "Ivory": (250, 245, 230),
    "Beige": (225, 205, 170),
    "Navy Blue": (20, 35, 95),
    "Midnight Blue": (15, 22, 55),
    "Forest Green": (25, 85, 40),
    "Dark Green": (15, 70, 35),
    "Maroon": (110, 20, 35),
    "Burgundy": (125, 25, 50),
    "Dark Purple": (70, 20, 95),
    "Charcoal": (45, 45, 48),
    "Jet Black": (5, 5, 8),
    "Chocolate Brown": (85, 42, 22),
    "Scarlet": (200, 20, 30),
    "Crimson": (165, 15, 40),
    "Vermilion": (225, 55, 30),
    "Coral": (245, 110, 95),
    "Salmon": (245, 145, 125),
    "Amber": (230, 155, 30),
    "Gold": (210, 170, 45),
    "Mustard": (190, 155, 40),
    "Copper": (175, 95, 45),
    "Rust": (165, 70, 35),
    "Terracotta": (190, 90, 60),
    "Turquoise": (40, 190, 185),
    "Cyan": (30, 200, 220),
    "Teal": (20, 130, 135),
    "Aqua": (70, 210, 210),
    "Seafoam Green": (120, 200, 170),
    "Emerald": (20, 145, 80),
    "Sapphire": (15, 70, 170),
    "Indigo": (55, 40, 140),
    "Periwinkle": (140, 145, 220),
    "Olive": (110, 115, 40),
    "Moss Green": (80, 110, 50),
    "Sage": (150, 165, 130),
    "Sand": (205, 180, 130),
    "Tan": (190, 155, 110),
    "Khaki": (175, 160, 110),
    "Camel": (185, 145, 90),
    "Stone Gray": (150, 145, 135),
    "Earth Brown": (110, 75, 45),
    "Clay": (175, 100, 70),
    "Silver": (185, 190, 195),
    "Bronze": (150, 100, 45),
    "Platinum": (210, 212, 215),
    "Rose Gold": (183, 110, 121),
    "Gunmetal": (55, 62, 68),
    "Titanium": (140, 145, 150),
    "Amethyst Purple": (145, 80, 180),
    "Garnet": (140, 25, 40),
    "Topaz": (210, 160, 50),
    "Jade": (70, 150, 100),
    "Aquamarine": (120, 220, 200),
    "Pastel Pink": (250, 200, 215),
    "Pastel Blue": (175, 205, 240),
    "Pastel Green": (180, 225, 185),
    "Pastel Yellow": (250, 240, 170),
    "Pastel Purple": (210, 185, 230),
    "Pastel Peach": (250, 210, 185),
    "Pastel Mint": (185, 235, 210),
    "Pastel Lavender": (220, 200, 235),
    "Neon Green": (70, 255, 40),
    "Neon Yellow": (245, 255, 30),
    "Neon Pink": (255, 40, 160),
    "Neon Orange": (255, 90, 20),
    "Neon Blue": (40, 80, 255),
    "Electric Purple": (170, 40, 255),
    "Fluorescent Cyan": (20, 255, 245),
    "Snow White": (255, 255, 255),
    "Pearl White": (240, 236, 230),
    "Creamy Ivory": (248, 236, 210),
    "Champagne Gold": (225, 200, 145),
    "Metallic Silver": (190, 195, 200),
    "Matte Black": (25, 25, 25),
    "Obsidian Black": (8, 10, 16),
    "Ruby Red": (185, 15, 40),
    "Cherry Red": (200, 25, 45),
    "Rose Red": (195, 40, 70),
    "Coral Pink": (245, 130, 140),
    "Blush Pink": (240, 180, 185),
    "Fuchsia": (210, 30, 140),
    "Hot Pink": (255, 50, 140),
    "Lavender Purple": (175, 140, 210),
    "Royal Purple": (95, 30, 160),
    "Violet": (140, 50, 200),
    "Cobalt Blue": (20, 55, 175),
    "Azure Blue": (30, 130, 220),
    "Sapphire Blue": (15, 60, 160),
    "Turquoise Blue": (30, 175, 195),
    "Emerald Green": (15, 140, 75),
    "Lime Green": (140, 210, 40),
    "Olive Green": (100, 110, 40),
    "Golden Yellow": (240, 200, 40),
    "Amber Yellow": (235, 175, 40),
    "Honey Gold": (200, 150, 50),
    "Mocha Brown": (100, 65, 45),
    "Coffee Brown": (75, 48, 32),
    "Sand Beige": (215, 190, 145),
    "Slate Gray": (90, 100, 110),
    "Charcoal Gray": (55, 55, 58),
    "Mauve": (175, 120, 140),
    "Taupe": (145, 125, 110),
    "Aubergine": (75, 25, 70),
    "Ochre": (190, 140, 40),
    "Sepia": (140, 100, 60),
    "Cerulean": (30, 140, 200),
    "Viridian": (40, 130, 100),
    "Magenta": (200, 30, 120),
    "Wisteria": (175, 155, 200),
    "Lilac": (200, 165, 210),
    "Plum": (95, 40, 80),
    "Champagne": (235, 215, 175),
    "Pewter": (140, 140, 145),
}
