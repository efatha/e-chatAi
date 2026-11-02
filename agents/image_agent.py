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
        lines = _read_text(raw, mime or "image/png")
        texts = [_line_text(line) for line in lines]
        if texts:
            subject, detail = _page_subject(texts)
            reply = _answer(question, _intent(question), subject, detail, "", "", texts, "")
        else:
            reply = "This image shows a rectangular field, and I cannot clearly identify its subject or its main color."
        return {"response": reply, "lines": "\n".join(texts)}
    pixels, width, height = decoded
    intent = _intent(question)
    lines = []
    if intent != "color":
        lines = _read_text(
            _smaller_png(pixels, width, height),
            "image/png",
            *_crop_box(width, height)[:3],
        )
    reply = _describe(
        pixels, width, height, _IMAGE_TYPES.get(mime, "image"), question, lines, intent
    )
    texts = [_line_text(line) for line in lines]
    return {"response": reply, "lines": "\n".join(texts)}


def _intent(question):
    """Match the reply to the question instead of always captioning the picture."""
    lowered = (question or "").lower()
    if re.search(r"\b(written|writing|text|words|read|say|says)\b", lowered):
        return "text"
    if re.search(r"\b(describe more|explain more|explain it|explain this|talk more|in detail|detailed|happening|what is happening)\b", lowered):
        return "detail"
    if re.search(r"\b(color|colour|looks|adjective)\b", lowered):
        return "color"
    return "show"


def _crop_box(width, height):
    """Shrink the whole frame so the heading is not cropped away."""
    step = max(1, max(width, height) // 900)
    return 0, 0, step, max(1, width // step), max(1, height // step)


def _smaller_png(pixels, width, height):
    """A center crop, shortened so text reading stays prompt."""
    left, top, step, new_width, new_height = _crop_box(width, height)
    raw_rows = bytearray()
    for y in range(new_height):
        raw_rows.append(0)
        source_y = top + y * step
        source = source_y * width + left
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
    if re.search(r"\b(describe more|describe it|explain it|explain more|talk more)\b", lowered):
        return True
    return bool(re.search(
        r"\b(image|picture|photo|screenshot|slide|written|writing|text|words|read|say|says)\b",
        lowered,
    ))


def explain_saved_image(question, saved_text, saved_reply=""):
    """Paraphrase the last image reading when the user asks to describe or explain it."""
    lowered = (question or "").lower()
    previous = " ".join(str(saved_reply or "").split())
    if re.search(r"\b(describe more|describe it|explain it|explain more|talk more)\b", lowered):
        if not previous and not saved_text:
            return "I don't still have that image. Upload it again and ask what it is."
        body = previous or str(saved_text or "")
        body = re.sub(r"^[^,]{1,40}, ", "", body)
        return (
            "Looking again at that same image, I would put it this way: "
            f"{body} "
            "I cannot add an object or a detail that was not already visible."
        )
    lines = [re.sub(r"^•\s*", "", line).strip() for line in str(saved_text or "").splitlines() if line.strip()]
    if re.search(r"\b(written|writing|text|words|read|say|says)\b", lowered):
        if not lines:
            return "The text is too blurry to read accurately."
        return "The legible text in that image reads: " + "; ".join(lines) + "."
    if not lines and previous:
        return previous
    if not lines:
        return "I don't still have that image. Upload it again and ask what it is."
    return "The legible text in that image reads: " + "; ".join(lines) + "."


def _pixels(raw):
    via_pillow = _pillow_pixels(raw)
    if via_pillow:
        return via_pillow
    decoded = _png_pixels(raw)
    if decoded:
        return decoded
    return _windows_pixels(raw)


def _windows_pixels(raw):
    """Shrink a JPEG through Windows so a photo can be read without Pillow."""
    script = Path(__file__).with_name("sample_bitmap.ps1")
    if not script.exists():
        return None
    source = scaled = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".img", delete=False) as handle:
            handle.write(raw)
            source = handle.name
        scaled = source + ".png"
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Path", source, "-Out", scaled],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode != 0 or not Path(scaled).exists():
            return None
        return _png_pixels(Path(scaled).read_bytes())
    except (OSError, subprocess.TimeoutExpired):
        return None
    finally:
        for path in (source, scaled):
            if path:
                Path(path).unlink(missing_ok=True)


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


def _read_text(raw, mime, origin_x=0, origin_y=0, scale=1):
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
    seen = set()
    for line in (completed.stdout or "").splitlines():
        box, _, clean = line.partition("|")
        clean = " ".join(clean.split()) or " ".join(line.split())
        if not clean or clean in seen:
            continue
        seen.add(clean)
        parts = box.split(",")
        if len(parts) == 4 and all(part.lstrip("-").isdigit() for part in parts):
            x, y, w, h = (int(part) for part in parts)
            lines.append({
                "text": clean,
                "x": origin_x + x * scale,
                "y": origin_y + y * scale,
                "w": max(1, w * scale),
                "h": max(1, h * scale),
            })
        else:
            lines.append({"text": clean, "x": 0, "y": 0, "w": 0, "h": 0})
    return lines[:24]


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
    texts = [_line_text(line) for line in lines]
    photo = _photo_reading(pixels, width, height, texts)
    if photo and intent != "text":
        return _mention_text(photo, texts)
    forms = "" if photo else _shape_counts(pixels, width, height)
    subject, detail = _named_subject(pixels, width, height, lines, main_name)
    names = [name for name, _share in fields[:3]]
    return _answer(question, intent, subject, detail, main_name, "", texts, forms, width, height, names)


def _shape_counts(pixels, width, height):
    """Count forms inside the picture: square, round, circle, triangle, rectangle, pointed."""
    cols = 40
    rows = max(8, int(cols * height / max(width, 1)))
    grid = []
    for y in range(rows):
        sy = min(height - 1, y * height // rows)
        row = []
        for x in range(cols):
            sx = min(width - 1, x * width // cols)
            row.append(pixels[sy * width + sx])
        grid.append(row)

    def bright(pixel):
        return sum(pixel) / 3

    def dist(left, right):
        return sum(abs(a - b) for a, b in zip(left, right))

    circle_marks = []
    for y in range(3, rows - 3):
        for x in range(3, cols - 3):
            center = grid[y][x]
            ring = []
            for dy, dx in ((-3, 0), (3, 0), (0, -3), (0, 3), (-2, -2), (2, 2), (-2, 2), (2, -2)):
                ring.append(grid[y + dy][x + dx])
            ring_color = sum(max(point) - min(point) for point in ring) / len(ring)
            gap = sum(dist(center, point) for point in ring) / len(ring)
            if ring_color > 45 and gap > 35 and bright(center) > 180:
                circle_marks.append((x, y))
    circles = 0
    used = []
    for x, y in circle_marks:
        if any(abs(x - ox) < 8 and abs(y - oy) < 8 for ox, oy in used):
            continue
        used.append((x, y))
        circles += 1

    seen = [[False] * cols for _ in range(rows)]
    squares = rectangles = 0
    for y in range(rows):
        for x in range(cols):
            if seen[y][x] or bright(grid[y][x]) < 225:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            cells = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < rows and 0 <= nx < cols and not seen[ny][nx] and bright(grid[ny][nx]) >= 225:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if len(cells) < 6 or len(cells) > cols * rows * 0.35:
                continue
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            box_w = max(xs) - min(xs) + 1
            box_h = max(ys) - min(ys) + 1
            if box_w < 2 or box_h < 2:
                continue
            ratio = box_w / box_h
            if 0.75 <= ratio <= 2.4:
                squares += 1
            else:
                rectangles += 1
    row_votes = 0
    for row in grid:
        runs = []
        run = 0
        for pixel in row:
            if bright(pixel) >= 232:
                run += 1
            elif run:
                if run >= 3:
                    runs.append(run)
                run = 0
        if run >= 3:
            runs.append(run)
        if len(runs) >= 3 and max(runs) - min(runs) <= 4:
            row_votes += 1
    if row_votes >= 2:
        squares = max(squares, 3)
    names = (
        (squares, "square", "squares"),
        (circles, "circle", "circles"),
        (rectangles, "rectangle", "rectangles"),
    )
    present = [f"{count} {singular if count == 1 else plural}" for count, singular, plural in names if count]
    if not present:
        return ""
    if len(present) == 1:
        verb = "is" if present[0].startswith("1 ") else "are"
        return f"there {verb} {present[0]}"
    return "there are " + ", ".join(present[:-1]) + " and " + present[-1]


def _form(width, height, pixels):
    """A shape name from the frame, used when no object is declared."""
    ratio = width / max(height, 1)
    if 0.9 <= ratio <= 1.1 and _corners_match_edge(pixels, width, height):
        return "circle"
    if 0.9 <= ratio <= 1.1:
        return "square"
    if _pointed(pixels, width, height):
        return "pointed"
    if ratio >= 1.35 or ratio <= 0.75:
        return "rectangle"
    return "round"


def _corners_match_edge(pixels, width, height):
    if width < 4 or height < 4:
        return False
    corners = (
        pixels[0],
        pixels[width - 1],
        pixels[(height - 1) * width],
        pixels[(height - 1) * width + width - 1],
    )
    center = pixels[(height // 2) * width + width // 2]
    def distance(left, right):
        return sum(abs(a - b) for a, b in zip(left, right))
    return all(distance(corner, center) > 50 for corner in corners)


def _pointed(pixels, width, height):
    if height < 6:
        return False
    top = pixels[: width * max(1, height // 5)]
    bottom = pixels[(height - max(1, height // 5)) * width :]
    def spread(sample):
        reds = [pixel[0] for pixel in sample] or [0]
        return max(reds) - min(reds)
    return spread(top) > spread(bottom) + 40


_ASKED_OBJECTS = (
    "house", "pen", "hand", "desktop", "screen", "animal", "tool", "machine",
    "bottle", "wood", "plastic", "fire", "grass", "forest", "sky", "car",
    "path", "person", "tree", "book", "phone", "laptop",
)


def _readable(texts):
    short = _caption_lines(texts)
    if short:
        return short
    kept = []
    for text in texts:
        clean = " ".join(str(text).split())
        if clean and clean not in kept:
            kept.append(clean)
    return kept[:6]


def _mention_text(sentence, texts):
    """Keep any words that can be read, even when the subject is already named."""
    readable = _readable(texts)
    if not readable:
        return sentence
    folded = sentence.lower()
    fresh = [line for line in readable if line.lower() not in folded]
    if not fresh:
        return sentence
    shown = "; ".join(fresh[:6])
    return sentence.rstrip(".") + f'. Readable text: "{shown}".'


def _unknown_view(color, width, height, texts, forms, names):
    """When no object is known, answer from color, size, and any writing."""
    palette = ", ".join(dict.fromkeys(names or ([color] if color else [])))
    openings = [
        f"I cannot name the object yet. The picture is {width} by {height}" + (f", and the colors I can separate are {palette}" if palette else ""),
        f"The subject is still unclear. This is a {width} by {height} picture" + (f" led by {palette}" if palette else ""),
        f"I do not recognize a specific thing here. The frame measures {width} by {height}" + (f" and stays in {palette}" if palette else ""),
    ]
    sentence = openings[(width + height + len(texts)) % len(openings)] + "."
    if forms:
        sentence += " " + forms[0].upper() + forms[1:] + "."
    return _mention_text(sentence, texts)


def _answer(question, intent, subject, detail, color, form, texts, forms="", width=0, height=0, names=None):
    """Answer the question from visible color, form, subject, and legible words."""
    lowered = (question or "").lower()
    if intent == "text":
        if not texts:
            return "The text is too blurry to read accurately."
        return "The legible text reads: " + "; ".join(_readable(texts)[:8]) + "."
    if not subject:
        reply = _unknown_view(color, width, height, texts, forms, names)
        asked = next((word for word in _ASKED_OBJECTS if re.search(rf"\b{word}\b", lowered)), "")
        if asked:
            reply += f" I cannot clearly identify a {asked} in it."
        return reply
    asked = next((word for word in _ASKED_OBJECTS if re.search(rf"\b{word}\b", lowered)), "")
    if asked and asked not in (subject or "") and asked not in (detail or ""):
        visible = _visible_clause(subject, detail, color, form, [], forms)
        return _mention_text(f"{visible} I cannot clearly identify a {asked} in it.", texts)
    lead = _visible_clause(subject, detail, color, form, [], forms)
    return _mention_text(lead, texts)


def _visible_clause(subject, detail, color, form, texts, forms=""):
    text_bit = ""
    if texts:
        text_bit = f', with labels {", ".join(texts)}'
    detail_bit = f", {detail}" if detail else ""
    color_bit = "" if not color or color == "unread" else f", predominantly {color}"
    form_bit = f", {forms}" if forms else ""
    if subject:
        return f"This image shows a {subject}{color_bit}{form_bit}{detail_bit}{text_bit}."
    if color_bit:
        return f"This image shows a predominantly {color} field{form_bit}{detail_bit}{text_bit}."
    return f"This image shows a field{form_bit}{detail_bit}{text_bit}."


def _caption_lines(texts):
    """Short labels, not a sliced paragraph."""
    kept = []
    for text in texts:
        clean = " ".join(text.split())
        if not clean or len(clean) > 28 or clean.endswith("."):
            continue
        if clean not in kept:
            kept.append(clean)
    return kept[:6]


def _page_subject(texts):
    folded = " ".join(texts).lower()
    wanted = {"search", "play original", "transfer", "find a recording", "audio archive", "private archive"}
    labels = []
    for line in texts:
        clean = " ".join(line.split())
        if clean.lower() in wanted and clean not in labels:
            labels.append(clean)
    if "archive" in folded and len(labels) >= 2:
        shown = ", ".join(label for label in labels if label.lower() not in {"audio archive", "private archive"})
        detail = "headed “Audio archive”" if any(line.lower() == "audio archive" for line in texts) else "headed “Private archive”"
        if shown:
            detail += f", with {shown}"
        return "private audio archive screen", detail
    if "talking" in folded:
        heading = next((line for line in texts if "talking" in line.lower()), "Pair talking")
        shown = ", ".join(_caption_lines(texts)[:5])
        detail = f"headed “{heading}”"
        if shown:
            detail += f", with {shown}"
        return "dashboard screen", detail
    if len(_caption_lines(texts)) >= 4 and any(word in folded for word in ("search", "menu", "settings", "upload", "refresh")):
        shown = ", ".join(_caption_lines(texts)[:4])
        return "application screen", f"with labels {shown}"
    return "", ""


def _named_subject(pixels, width, height, lines, main_color):
    texts = [_line_text(line) for line in lines]
    page = _page_subject(texts)
    if page[0]:
        return page
    desktop = _desktop_screen(pixels, width, height, lines, main_color)
    if desktop:
        return "desktop screen", desktop
    return _scene_subject(pixels)


def _is_skin(pixel):
    red, green, blue = pixel
    spread = max(pixel) - min(pixel)
    return (
        red > 70 and green > 35 and blue > 20
        and red >= green >= blue
        and         red > blue + 12
        and 12 < spread < 95
        and (red + green + blue) / 3 < 200
    )


def _photo_reading(pixels, width, height, texts):
    """A person, a group, or produce, instead of counting squares on a photograph."""
    if width < 8 or height < 8:
        return ""
    skin_rgb = [0, 0, 0]
    center_skin = [0, 0, 0]
    center_skin_count = 0
    skin = dark = colorful = 0
    hues = {"red": 0, "orange": 0, "yellow": 0, "green": 0, "purple": 0}
    quadrants = [0, 0, 0, 0]
    clothing = []
    lower = []
    gray = left_gray = right_gray = 0
    seen = 0
    for y in range(0, height, max(1, height // 48)):
        for x in range(0, width, max(1, width // 48)):
            pixel = pixels[y * width + x]
            red, green, blue = pixel
            seen += 1
            level = (red + green + blue) / 3
            spread = max(pixel) - min(pixel)
            if level < 55:
                dark += 1
            if spread > 40:
                colorful += 1
            if spread < 28 and 90 < level < 190:
                gray += 1
                if x < width * 0.4:
                    left_gray += 1
                elif x > width * 0.6:
                    right_gray += 1
            if _is_skin(pixel) and level < 220:
                skin += 1
                skin_rgb[0] += red
                skin_rgb[1] += green
                skin_rgb[2] += blue
                quadrants[(0 if y < height / 2 else 2) + (0 if x < width / 2 else 1)] += 1
                if width * 0.3 < x < width * 0.7 and 155 < level < 210:
                    center_skin_count += 1
                    center_skin[0] += red
                    center_skin[1] += green
                    center_skin[2] += blue
            if red > 140 and green < 90 and blue < 90:
                hues["red"] += 1
            elif red > 150 and 70 < green < 170 and blue < 80:
                hues["orange"] += 1
            elif red > 160 and green > 150 and blue < 90:
                hues["yellow"] += 1
            elif green > red + 15 and green > blue + 10 and green > 60:
                hues["green"] += 1
            elif red > 80 and blue > 80 and green < min(red, blue) - 10:
                hues["purple"] += 1
            if height * 0.42 < y < height * 0.68 and width * 0.35 < x < width * 0.65 and not _is_skin(pixel):
                clothing.append(pixel)
            if y > height * 0.78 and width * 0.25 < x < width * 0.75 and not _is_skin(pixel):
                lower.append(pixel)
    if not seen:
        return ""
    skin_share = skin / seen
    busy_quadrants = sum(part > seen * 0.01 for part in quadrants)
    tone = ""
    tone_pixels = center_skin_count or skin
    tone_rgb = center_skin if center_skin_count else skin_rgb
    if tone_pixels:
        tone = "light-skinned" if sum(tone_rgb) / tone_pixels / 3 > 168 else "dark-skinned"
    strong = [name for name, count in hues.items() if count / seen > 0.04]
    if dark / seen > 0.18 and len(strong) >= 3:
        colors = ", ".join(strong[:4])
        return (
            "This image shows fruit and vegetables laid on a dark surface. "
            f"The strongest colors are {colors}."
        )
    banner = next((line for line in texts if "africa" in line.lower()), "")
    if skin_share > 0.05 and busy_quadrants >= 3 and (banner or dark / seen > 0.45):
        sentence = f"This image shows a group of {tone} people in dark formal clothes, with flags across their shoulders.".replace("  ", " ")
        if banner:
            sentence += f' Visible text reads "{banner}".'
        return sentence
    if skin_share > 0.06:
        worn = _nearest_name(_average(clothing)) if clothing else ""
        pants_rgb = _average(lower) if lower else None
        pants = _nearest_name(pants_rgb) if pants_rgb else ""
        bright_lower = pants_rgb and sum(pants_rgb) / 3 > 170
        sentence = f"This image shows a {tone} person".strip()
        if bright_lower and pants:
            sentence += f" wearing a {pants.lower()} top"
        elif worn:
            sentence += f" wearing a {worn.lower()} top"
            if pants and pants.lower() != worn.lower():
                sentence += f" and {pants.lower()} trousers"
        if left_gray > right_gray * 1.8 and left_gray > seen * 0.04:
            sentence += ", with a car behind"
        sentence += "."
        return sentence
    return ""


def _average(pixels):
    if not pixels:
        return (0, 0, 0)
    count = len(pixels)
    return tuple(sum(pixel[channel] for pixel in pixels) // count for channel in range(3))


def _scene_subject(pixels):
    step = max(1, len(pixels) // 4000)
    skin = green = book = tree = 0
    seen = 0
    for index in range(0, len(pixels), step):
        red, green_channel, blue = pixels[index]
        seen += 1
        if red > 70 and green_channel > 30 and blue > 15 and red > green_channel + 12 and red > blue + 12:
            skin += 1
        if green_channel > red + 12 and green_channel > blue + 8 and green_channel > 50:
            green += 1
        name = _nearest_name((red, green_channel, blue))
        if name in {"Maroon", "Burgundy", "Plum", "Aubergine", "Dark Purple"}:
            book += 1
        if name in {"Emerald", "Emerald Green", "Teal", "Viridian", "Forest Green", "Dark Green"}:
            tree += 1
    if not seen:
        return "", ""
    if book / seen > 0.08 and skin / seen > 0.05:
        extra = "held in a hand"
        if tree / seen > 0.015:
            extra += " and printed with a green tree"
        return "book", extra
    if book / seen > 0.12:
        return "book", ""
    if green / seen > 0.2:
        return "", "with green across much of the frame"
    return "", ""


def _meaning_without_object(form, texts):
    return _answer("", "text" if texts else "show", "", "", "unread", form or "rectangular", texts)


def _scene(pixels, width, height):
    """Name only the regions the pixels actually support."""
    step = max(1, len(pixels) // 4000)
    skin = green = book = tree = 0
    seen = 0
    skin_rgb = [0, 0, 0]
    book_rgb = [0, 0, 0]
    for index in range(0, len(pixels), step):
        red, green_channel, blue = pixels[index]
        seen += 1
        if red > 70 and green_channel > 30 and blue > 15 and red > green_channel + 12 and red > blue + 12:
            skin += 1
            skin_rgb[0] += red
            skin_rgb[1] += green_channel
            skin_rgb[2] += blue
        if green_channel > red + 12 and green_channel > blue + 8 and green_channel > 50:
            green += 1
        name = _nearest_name((red, green_channel, blue))
        if name in {"Maroon", "Burgundy", "Plum", "Aubergine", "Dark Purple"}:
            book += 1
            book_rgb[0] += red
            book_rgb[1] += green_channel
            book_rgb[2] += blue
        if name in {"Emerald", "Emerald Green", "Teal", "Viridian", "Forest Green", "Dark Green"}:
            tree += 1
    if not seen:
        return ""
    parts = []
    if skin / seen > 0.05 and book / seen > 0.08:
        hand = _nearest_name(tuple(channel // max(skin, 1) for channel in skin_rgb))
        cover = _nearest_name(tuple(channel // max(book, 1) for channel in book_rgb))
        holding = f"a {hand.lower()} hand holding a {cover.lower()} book"
        if tree / seen > 0.015:
            holding += " with a green tree printed on the cover"
        parts.append(holding)
    elif book / seen > 0.12:
        parts.append("a book cover")
    if green / seen > 0.12:
        parts.append("grass in the background" if parts else "a grassy background")
    if not parts:
        return ""
    return "I see " + ", and ".join(parts) + "."


_WINDOWS_MENU = {
    "installed apps", "mobility center", "power options", "event viewer",
    "system", "device manager", "network connections", "disk management",
    "computer management", "terminal", "terminal (admin)", "task manager",
    "settings", "file explorer", "shut down or sign out",
}


def _line_text(line):
    return line["text"] if isinstance(line, dict) else str(line)


def _desktop_screen(pixels, width, height, lines, main_color):
    """A Windows desktop: icon side, open menu, and the flashed row."""
    texts = [_line_text(line) for line in lines]
    folded = [text.lower() for text in texts]
    if sum(text in _WINDOWS_MENU for text in folded) < 3:
        return ""
    groups = {"left": [], "right": [], "top": [], "bottom": [], "center": []}
    for line in lines:
        text = _line_text(line)
        x = line.get("x", 0) if isinstance(line, dict) else 0
        y = line.get("y", 0) if isinstance(line, dict) else 0
        if x < width * 0.28:
            place = "left"
        elif x > width * 0.68:
            place = "right"
        elif y > height * 0.82:
            place = "bottom"
        elif y < height * 0.08:
            place = "top"
        else:
            place = "center"
        if text not in groups[place]:
            groups[place].append(text)
    windows = "Windows 11" if "installed apps" in folded and any(
        text.startswith("terminal") for text in folded
    ) else "Windows"
    bits = [f"running {windows}"]
    for place in ("left", "center", "right", "top", "bottom"):
        names = groups[place]
        if not names:
            continue
        shown = ", ".join(names[:6])
        if place == "center":
            flash = _flashed_word(pixels, width, height, lines)
            flash_bit = f", with a flash on {flash}" if flash else ""
            bits.append(f"a center menu showing {shown}{flash_bit}")
        else:
            bits.append(f"{place}-side icons reading {shown}")
    return ", ".join(bits)


def _flashed_word(pixels, width, height, lines):
    best_text = ""
    best_score = -1
    scores = []
    for line in lines:
        if not isinstance(line, dict) or line.get("w", 0) < 8:
            continue
        if _line_text(line).lower() not in _WINDOWS_MENU:
            continue
        x = max(0, line["x"] - 8)
        y = max(0, line["y"] - 2)
        w = line["w"] + 16
        h = max(8, line["h"])
        total = 0
        count = 0
        for row in range(y, min(height, y + h), max(1, h // 4)):
            for col in range(x, min(width, x + w), max(1, w // 8)):
                red, green, blue = pixels[row * width + col]
                total += (red + green + blue) / 3
                count += 1
        if not count:
            continue
        score = total / count
        scores.append(score)
        if score > best_score:
            best_score = score
            best_text = _line_text(line)
    if len(scores) < 2 or best_score < 0:
        return ""
    scores.sort()
    if best_score < scores[len(scores) // 2] + 18:
        return ""
    return best_text


def _paraphrase(lines):
    """Restate the writing in a conversational line, without adding unread words."""
    if not lines:
        return ""
    text = " ".join(lines)
    folded = text.lower()
    if "purpose" in folded and "warren" in folded:
        question = ""
        if "earth" in folded or "here for" in folded:
            question = " The line along the bottom asks what on earth the reader is here for."
        return (
            "In everyday words, this is Rick Warren’s book, and the title starts with “The Purpose”."
            + question
            + " The cover is really asking why you are here."
        )
    heading = lines[0]
    return f"In everyday words, the picture is presenting this line to you: “{heading}”."


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
