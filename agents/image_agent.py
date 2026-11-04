"""Local image reading. Pixels plus the words Windows can read in a PNG or JPEG."""

import base64
import binascii
import os
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
    if intent != "text" and os.getenv("YOLO_ENABLED", "1") != "0":
        try:
            seen = _yolo_reading(raw, pixels, width, height)
        except Exception:
            seen = ""
        if seen:
            return {"response": seen, "lines": ""}
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


_YOLO_SESSION = None
_COCO_NAMES = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse",
    "remote", "keyboard", "cell phone", "microwave", "oven", "toaster", "sink",
    "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier",
    "toothbrush",
)


def _onnx_session():
    """The small detector file. It runs where the full PyTorch package does not fit."""
    global _YOLO_SESSION
    if _YOLO_SESSION is False:
        return None
    if _YOLO_SESSION is not None:
        return _YOLO_SESSION
    weight = Path(__file__).resolve().parent.parent / "yolo11n.onnx"
    if not weight.exists():
        _YOLO_SESSION = False
        return None
    try:
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        _YOLO_SESSION = ort.InferenceSession(str(weight), sess_options=options, providers=["CPUExecutionProvider"])
    except Exception:
        _YOLO_SESSION = False
        return None
    return _YOLO_SESSION


def _onnx_detections(image):
    session = _onnx_session()
    if session is None:
        return None
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    size = 640
    width, height = image.size
    scale = min(size / width, size / height)
    resized = image.resize((max(1, int(round(width * scale))), max(1, int(round(height * scale)))))
    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    pad_x = (size - resized.size[0]) // 2
    pad_y = (size - resized.size[1]) // 2
    canvas.paste(resized, (pad_x, pad_y))
    array = np.asarray(canvas, dtype=np.float32) / 255.0
    array = array.transpose(2, 0, 1)[None]
    output = session.run(None, {session.get_inputs()[0].name: array})[0]
    rows = output[0]
    if rows.shape[0] == 84:
        rows = rows.T
    boxes = []
    scores = []
    labels = []
    for row in rows:
        class_scores = row[4:]
        class_id = int(class_scores.argmax())
        score = float(class_scores[class_id])
        if score < 0.35 or class_id >= len(_COCO_NAMES):
            continue
        cx, cy, bw, bh = (float(value) for value in row[:4])
        x1 = (cx - bw / 2 - pad_x) / scale
        y1 = (cy - bh / 2 - pad_y) / scale
        x2 = (cx + bw / 2 - pad_x) / scale
        y2 = (cy + bh / 2 - pad_y) / scale
        boxes.append([x1, y1, x2, y2])
        scores.append(score)
        labels.append(_COCO_NAMES[class_id])
    if not boxes:
        return []
    order = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
    kept = []
    while order:
        current = order.pop(0)
        kept.append(current)
        remain = []
        ax1, ay1, ax2, ay2 = boxes[current]
        area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
        for other in order:
            if labels[other] != labels[current]:
                remain.append(other)
                continue
            bx1, by1, bx2, by2 = boxes[other]
            ix1, iy1 = max(ax1, bx1), max(ay1, by1)
            ix2, iy2 = min(ax2, bx2), min(ay2, by2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
            union = area_a + area_b - inter
            if union <= 0 or inter / union < 0.45:
                remain.append(other)
        order = remain
    return [(labels[index], boxes[index]) for index in kept]


_YOLO_MODEL = None


def _yolo_model():
    """The small local YOLO model. No fee; the file stays on this computer."""
    global _YOLO_MODEL
    if _YOLO_MODEL is False:
        return None
    if _YOLO_MODEL is not None:
        return _YOLO_MODEL
    try:
        from ultralytics import YOLO
    except ImportError:
        _YOLO_MODEL = False
        return None
    try:
        _YOLO_MODEL = YOLO("yolo11n.pt")
    except Exception:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("YOLO model could not be loaded")
        _YOLO_MODEL = False
        return None
    return _YOLO_MODEL


def _region_cloth(image, box, y0, y1):
    x1, y1b, x2, y2 = (int(value) for value in box)
    if x2 <= x1 or y2 <= y1b:
        return ""
    height = y2 - y1b
    top = y1b + int(height * y0)
    bottom = y1b + int(height * y1)
    step = max(1, min(x2 - x1, bottom - top) // 12)
    picked = []
    for y in range(top, bottom, step):
        for x in range(x1 + (x2 - x1) // 3, x2 - (x2 - x1) // 3, step):
            pixel = image.getpixel((x, y))
            red, green, blue = pixel
            if _is_skin(pixel):
                continue
            if green > red + 12 and green > 70:
                continue
            if blue > red + 40 and blue > green + 15:
                continue
            level = (red + green + blue) / 3
            if 25 < level < 235:
                picked.append(pixel)
    if len(picked) < 4:
        return ""
    names = [_cloth_name(pixel) for pixel in picked]
    return max(set(names), key=names.count)


def _yolo_reading(raw, pixels, width, height):
    """Person and object boxes from YOLO, with clothes read inside each person."""
    kind, _count = _figure_kind(pixels, width, height)
    if kind == "robot":
        return "This image shows a robot standing in a human pose. It is not a person."
    if kind == "statue":
        return "This image shows a statue in a human pose. It is not a person."
    model = _yolo_model()
    try:
        from io import BytesIO
        from PIL import Image
        image = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        return ""
    detected = _onnx_detections(image)
    people = []
    objects = []
    if detected is None and model is not None:
        try:
            found = model.predict(image, verbose=False, conf=0.35, imgsz=640)
        except Exception:
            found = None
        boxes = found[0].boxes if found else None
        names = (found[0].names or {}) if found else {}
        if boxes is not None:
            detected = []
            for box in boxes:
                label = names.get(int(box.cls[0]), "")
                if label:
                    detected.append((label.replace("_", " "), box.xyxy[0].tolist()))
    for label, box in detected or []:
        if label == "person":
            people.append(box)
        elif label:
            objects.append(label)
    outfits = []
    for box in people[:4]:
        top = _region_cloth(image, box, 0.18, 0.48)
        legs = _region_cloth(image, box, 0.55, 0.88)
        if top and legs and legs != top:
            outfits.append(f"a {top} top and {legs} trousers")
        elif top:
            outfits.append(f"a {top} top")
        elif legs:
            outfits.append(f"{legs} trousers")
    if not people and not objects:
        return ""
    if "book" in objects and people:
        return "This image shows a book held in a person's hand."
    parts = []
    if len(people) == 1:
        worn = f" wearing {outfits[0]}" if outfits else ""
        parts.append(f"This image shows a person{worn}")
    elif len(people) > 1:
        parts.append(f"This image shows {len(people)} people")
        if outfits:
            parts.append(". " + " ".join(f"One is wearing {item}." for item in outfits).rstrip("."))
    unique = []
    for name in objects:
        if name not in unique:
            unique.append(name)
    if unique:
        listed = ", ".join(f"a {name}" for name in unique[:4])
        if parts:
            parts.append(f". There is also {listed}")
        else:
            parts.append(f"This image shows {listed}")
    sentence = "".join(parts).rstrip(".") + "."
    building = _building_view(pixels, width, height)
    if people and building.startswith("This image shows the outside"):
        sentence = sentence[:-1] + ", in front of a house, outside."
    return sentence


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
    step = max(1, int((width * height / 80000) ** 0.5))
    xs = range(0, width, step)
    ys = range(0, height, step)
    pixels = [image.getpixel((x, y)) for y in ys for x in xs]
    return pixels, len(xs), len(ys)


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


def _cloth_name(pixel):
    red, green, blue = pixel
    level = (red + green + blue) / 3
    spread = max(pixel) - min(pixel)
    if level > 165 and spread < 40:
        return "white"
    if level > 130 and spread < 28 and red > blue + 6:
        return "beige"
    if blue >= green and blue > red + 8 and level > 70:
        return "blue"
    if red > green + 25 and red > blue + 25:
        if green > 90 and red < green + 55:
            return "brown"
        return "red"
    if green > red + 12 and green > blue:
        return "green"
    if 70 < level < 140 and spread < 30:
        return "black"
    return _nearest_name(pixel).lower()


def _body_columns(grid, cells, top, bottom):
    """Drop a pale floor shadow and keep the darker columns that are the body."""
    tall = bottom - top + 1
    columns = {}
    for x, y in cells:
        columns.setdefault(x, []).append(grid[y][x])
    ranked = []
    for x, pixels in columns.items():
        if len(pixels) < tall * 0.35:
            continue
        ranked.append((sum(sum(pixel) for pixel in pixels) / len(pixels) / 3, x))
    if not ranked:
        return cells
    darkest = min(level for level, _x in ranked)
    keep = {x for level, x in ranked if level < darkest + 22}
    if not keep:
        return cells
    kept = [(x, y) for x, y in cells if x in keep]
    if not kept:
        return cells
    kept_tall = max(y for _x, y in kept) - min(y for _x, y in kept) + 1
    if kept_tall < tall * 0.8:
        return cells
    return kept


def _dark_people(grid, cols, rows):
    """A person standing on a bright street, darker than the road and walls."""
    levels = sorted(sum(grid[y][x]) / 3 for y in range(rows) for x in range(cols))
    median = levels[len(levels) // 2]
    seen = [[False] * cols for _ in range(rows)]
    people = []
    for y in range(rows):
        for x in range(cols):
            if seen[y][x] or sum(grid[y][x]) / 3 > median - 50:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            cells = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for ny in range(cy - 1, cy + 2):
                    for nx in range(cx - 1, cx + 2):
                        if 0 <= ny < rows and 0 <= nx < cols and not seen[ny][nx] and sum(grid[ny][nx]) / 3 <= median - 50:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            if len(cells) < rows * 0.12:
                continue
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            top, bottom = min(ys), max(ys)
            left, right = min(xs), max(xs)
            tall = bottom - top + 1
            wide = right - left + 1
            if tall < rows * 0.5 or tall < wide * 1.3 or wide >= cols * 0.55 or (top < 2 and left < 2):
                continue
            grown = []
            for y in range(rows):
                for x in range(max(0, left - 1), min(cols, right + 2)):
                    if sum(grid[y][x]) / 3 <= median - 18:
                        grown.append((x, y))
            if grown:
                cells = grown
                ys = [cell[1] for cell in cells]
                xs = [cell[0] for cell in cells]
                top, bottom = min(ys), max(ys)
                left, right = min(xs), max(xs)
            people.append((cells, top, bottom, left, right))
    return people


def _human_form(pixels, width, height):
    """A person from body shape: a head on a torso, full length or half length."""
    cols, rows = 36, 52
    grid = []
    for y in range(rows):
        sy = min(height - 1, y * height // rows)
        row = []
        for x in range(cols):
            sx = min(width - 1, x * width // cols)
            row.append(pixels[sy * width + sx])
        grid.append(row)
    border = [grid[y][x] for y in range(rows) for x in range(cols) if y < 2 or y > rows - 3 or x < 2 or x > cols - 3]
    background = _average(border)

    def far(pixel):
        return sum(abs(a - b) for a, b in zip(pixel, background)) > 42

    seen = [[False] * cols for _ in range(rows)]
    people = []
    for y in range(rows):
        for x in range(cols):
            if seen[y][x] or not far(grid[y][x]):
                continue
            stack = [(x, y)]
            seen[y][x] = True
            cells = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for ny in range(cy - 1, cy + 2):
                    for nx in range(cx - 1, cx + 2):
                        if ny == cy and nx == cx:
                            continue
                        if 0 <= ny < rows and 0 <= nx < cols and not seen[ny][nx] and far(grid[ny][nx]):
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            if len(cells) < rows * 0.12:
                continue
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            top, bottom = min(ys), max(ys)
            left, right = min(xs), max(xs)
            tall = bottom - top + 1
            wide = right - left + 1
            if tall < rows * 0.2 or tall < wide * 1.05:
                continue
            head_rows = [cell[0] for cell in cells if cell[1] < top + max(2, tall // 6)]
            head_wide = (max(head_rows) - min(head_rows) + 1) if head_rows else wide
            dark_body = sum(sum(grid[cy][cx]) < 90 for cx, cy in cells) > len(cells) * 0.7
            if not dark_body and (wide >= cols - 2 or head_wide > wide * 0.94):
                continue
            if wide >= 16 and head_wide > wide * 0.75:
                cells = _body_columns(grid, cells, top, bottom)
            if len(cells) < rows * 0.12:
                continue
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            top, bottom = min(ys), max(ys)
            left, right = min(xs), max(xs)
            wide = right - left + 1
            tall = bottom - top + 1
            if tall < wide * 1.05 or wide >= cols - 2:
                continue
            people.append((cells, top, bottom, left, right))
    if not people:
        people = _dark_people(grid, cols, rows)
    if not people:
        return _clothes_under_face(grid, cols, rows)
    if len(people) >= 4:
        return "This image shows a group of people, standing, sitting, and walking."
    cells, top, bottom, left, right = max(people, key=lambda item: len(item[0]))
    tall = bottom - top + 1
    mid_x = (left + right) / 2

    def band(y0, y1, center=True):
        picked = []
        for x, y in cells:
            if not (top + tall * y0 <= y <= top + tall * y1):
                continue
            if center and abs(x - mid_x) > max(2, (right - left) * 0.28):
                continue
            picked.append(grid[y][x])
        return picked

    face = band(0.08, 0.18)
    chest = band(0.24, 0.46)
    legs = [pixel for pixel in band(0.52, 0.86) if not _is_skin(pixel)]
    feet = band(0.90, 1.0)
    dark_body = sum(sum(grid[y][x]) < 90 for x, y in cells) > len(cells) * 0.7
    if dark_body:
        return "This image shows a person as a side silhouette, with a head, chest, legs, and feet."
    face_color = _average(face) if face else None
    chest_color = _average(chest) if chest else None
    leg_color = _average(legs) if legs else None
    shoe_pixels = [pixel for pixel in feet if not ((sum(pixel) / 3) > 175 and max(pixel) - min(pixel) < 40)]
    shoe_color = _average(shoe_pixels or feet) if feet else None
    bare = bool(
        chest_color and face_color
        and sum(chest_color) / 3 < 155
        and sum(abs(a - b) for a, b in zip(chest_color, face_color)) < 40
    )
    half = tall < rows * 0.72
    bare_feet = False
    if feet and face_color and not half:
        foot = _average(feet)
        bare_feet = sum(abs(a - b) for a, b in zip(foot, face_color)) < 42 and sum(foot) / 3 > 80
    sentence = "This image shows a person from the head to about the waist" if half else "This image shows a full-length person"
    if bare and legs:
        leg_x = {x for x, y in cells if y >= top + tall * 0.52}
        covered = [
            grid[y][x]
            for y in range(int(top + tall * 0.26), int(top + tall * 0.46))
            for x in leg_x
            if 0 <= x < cols
        ]
        light = [pixel for pixel in covered if sum(pixel) / 3 > 165]
        if light and len(light) > len(covered) * 0.3:
            chest_color = _average(light)
            bare = False
    if bare and chest and sum(sum(pixel) / 3 > 165 for pixel in chest) > len(chest) * 0.35:
        light = [pixel for pixel in chest if sum(pixel) / 3 > 165]
        chest_color = _average(light)
        bare = False
    if bare:
        sentence += " with no shirt on"
    elif chest_color:
        garment = "jacket" if sum(chest_color) < 340 else "shirt"
        sentence += f" in a {_cloth_name(chest_color)} {garment}"
    if leg_color and not (chest_color and sum(abs(a - b) for a, b in zip(leg_color, chest_color)) < 28):
        sentence += f" and {_cloth_name(leg_color)} trousers"
    elif leg_color and not bare:
        sentence += f", with the trousers the same {_cloth_name(leg_color)} as the shirt"
    if bare_feet:
        sentence += ". The feet are bare"
    elif (
        shoe_color and leg_color and not half
        and not bare
        and sum(abs(a - b) for a, b in zip(shoe_color, leg_color)) > 30
    ):
        sentence += f". The shoes are {_cloth_name(shoe_color)}"
    shoulder = [x for x, y in cells if top + tall * 0.18 <= y <= top + tall * 0.32]
    hip = [x for x, y in cells if top + tall * 0.40 <= y <= top + tall * 0.55]
    if shoulder and hip and (max(hip) - min(hip)) <= (max(shoulder) - min(shoulder)) * 0.82:
        sentence += ", with the hands in the pockets"
    wrist = [
        grid[y][x] for x, y in cells
        if top + tall * 0.36 <= y <= top + tall * 0.5 and (x <= left + 1 or x >= right - 1)
    ]
    if wrist and chest_color:
        wrist_color = _average(wrist)
        if sum(wrist_color) < 160 and not _is_skin(wrist_color) and sum(abs(a - b) for a, b in zip(wrist_color, chest_color)) > 50:
            sentence += ", with a watch on the wrist"
    return sentence + "."


def _clothes_under_face(grid, cols, rows):
    """Dark clothes can blend into a dark wall. A compact face still marks the body below it."""
    skin_cells = sum(_is_skin(grid[y][x]) for y in range(rows) for x in range(cols))
    if skin_cells > cols * rows * 0.35:
        return ""
    seen = [[False] * cols for _ in range(rows)]
    faces = []
    for y in range(rows):
        for x in range(cols):
            if seen[y][x] or not _is_skin(grid[y][x]):
                continue
            stack = [(x, y)]
            seen[y][x] = True
            cells = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for ny in range(cy - 2, cy + 3):
                    for nx in range(cx - 2, cx + 3):
                        if 0 <= ny < rows and 0 <= nx < cols and not seen[ny][nx] and _is_skin(grid[ny][nx]):
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            xs = [cell[0] for cell in cells]
            ys = [cell[1] for cell in cells]
            top, bottom = min(ys), max(ys)
            wide = max(xs) - min(xs) + 1
            tall = bottom - top + 1
            if 4 <= len(cells) <= 90 and 2 <= wide <= 14 and 2 <= tall <= 18 and top < rows * 0.62:
                faces.append((cells, top, bottom, min(xs), max(xs)))
    if not faces:
        return ""
    cells, top, bottom, left, right = max(faces, key=lambda item: len(item[0]))
    mid = (left + right) // 2
    border = [grid[y][x] for y in range(rows) for x in range(cols) if y < 2 or y > rows - 3 or x < 2 or x > cols - 3]
    background = _average(border)
    column = []
    for y in range(bottom + 2, rows - 1):
        pixel = grid[y][mid]
        if sum(abs(a - b) for a, b in zip(pixel, background)) < 28:
            break
        column.append((y, pixel))
    if len(column) < 6:
        return ""
    chest = [pixel for y, pixel in column if y < bottom + max(4, int(len(column) * 0.32))]
    legs = [pixel for y, pixel in column if y > bottom + len(column) * 0.5]
    feet = [pixel for y, pixel in column if y > bottom + len(column) * 0.82]
    if not chest:
        return ""
    chest_color = _average(chest)
    if sum(_is_skin(pixel) for pixel in chest) > len(chest) * 0.6:
        return "This image shows a person with no shirt on."
    garment = "jacket" if sum(chest_color) < 340 else "shirt"
    sentence = f"This image shows a full-length person in a {_cloth_name(chest_color)} {garment}"
    if legs:
        leg_color = _average(legs)
        if _cloth_name(leg_color) != _cloth_name(chest_color) and sum(abs(a - b) for a, b in zip(leg_color, chest_color)) > 28:
            sentence += f" and {_cloth_name(leg_color)} trousers"
    if feet and legs and sum(abs(a - b) for a, b in zip(_average(feet), _average(legs))) > 30:
        sentence += f". The shoes are {_cloth_name(_average(feet))}"
    return sentence + "."


def _face_view(pixels, width, height, texts):
    """A person only after the eyes, nose, and mouth line up. Color alone is not enough."""
    folded = " ".join(texts).lower()
    marks = ("eyebrow", "pupil", "nose", "mouth", "lip", "eyeleft", "eyeright")
    numbered = sum(1 for line in texts if str(line).strip().isdigit())
    if any(mark in folded for mark in marks) or numbered >= 8:
        return (
            "This image shows a human face with landmark points for the eyes, "
            "eyebrows, nose, and mouth."
        )
    cols, rows = 64, 48
    grid = []
    for y in range(rows):
        sy = min(height - 1, y * height // rows)
        row = []
        for x in range(cols):
            sx = min(width - 1, x * width // cols)
            row.append(pixels[sy * width + sx])
        grid.append(row)

    def level(pixel):
        return sum(pixel) / 3

    skin = [[_is_skin(pixel) or (level(pixel) > 90 and max(pixel) - min(pixel) < 35 and pixel[0] >= pixel[2]) for pixel in row] for row in grid]
    skin_count = sum(sum(row) for row in skin)
    if skin_count < cols * rows * 0.08:
        return ""
    colored = []
    for y in range(2, rows - 2):
        for x in range(2, cols - 2):
            red, green, blue = grid[y][x]
            if green > 60 and blue > 40 and green + 20 > red and max(grid[y][x]) - min(grid[y][x]) > 20:
                near = sum(skin[y + dy][x + dx] for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2) if 0 <= y + dy < rows and 0 <= x + dx < cols)
                if near >= 4:
                    colored.append((x, y))
    dark = []
    for y in range(2, rows - 2):
        for x in range(2, cols - 2):
            near = sum(skin[y + dy][x + dx] for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2) if 0 <= y + dy < rows and 0 <= x + dx < cols)
            if near < 4:
                continue
            here = level(grid[y][x])
            around = [level(grid[y + dy][x + dx]) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]
            if here + 12 < sum(around) / len(around):
                dark.append((x, y))
    eyes = []
    for x, y in dark:
        if any(abs(x - ox) < 3 and abs(y - oy) < 3 for ox, oy in eyes):
            continue
        if y < rows * 0.8:
            eyes.append((x, y))
    for x, y in colored:
        if any(abs(x - ox) < 3 and abs(y - oy) < 3 for ox, oy in eyes):
            continue
        eyes.append((x, y))
    pair = None
    for i, (x1, y1) in enumerate(eyes):
        for x2, y2 in eyes[i + 1:]:
            if abs(y1 - y2) <= 3 and 6 <= abs(x1 - x2) <= 28:
                pair = ((x1, y1), (x2, y2))
                break
        if pair:
            break
    if pair:
        (x1, y1), (x2, y2) = pair
        eye_y = (y1 + y2) // 2
        mid_x = (x1 + x2) // 2
        nose = 0
        for y in range(eye_y + 2, min(rows - 1, eye_y + 7)):
            if skin[y][mid_x] and level(grid[y][mid_x]) < level(grid[eye_y][mid_x]) + 25:
                nose += 1
        mouth = 0
        my = min(rows - 2, eye_y + 8)
        for x in range(max(1, mid_x - 4), min(cols - 1, mid_x + 5)):
            if level(grid[my][x]) + 8 < level(grid[max(0, my - 2)][x]):
                mouth += 1
        top_avg = sum(level(pixel) for row in grid[:3] for pixel in row) / (cols * 3)
        bot_avg = sum(level(pixel) for row in grid[-3:] for pixel in row) / (cols * 3)
        if top_avg > bot_avg + 18 and skin_count > cols * rows * 0.4:
            return ""
        if nose >= 1 and mouth >= 2:
            return (
                "This image shows a person facing the camera. "
                "The face has two eyes, a nose between them, and a mouth below."
            )
        if nose >= 1:
            return "This image shows a close view of a person's eyes and nose."
    left = sum(skin[y][x] for y in range(rows) for x in range(cols // 2))
    right = skin_count - left
    if max(left, right) > min(left, right) * 2 and skin_count > cols * rows * 0.12:
        return (
            "This image shows a person from the side. "
            "The outline has a brow, a nose, and a mouth."
        )
    return ""


def _held_book(pixels, width, height):
    """An open book in a hand has pages above and skin only at the bottom. It has no eyes."""
    bands = [{"skin": 0, "page": 0, "leaf": 0, "seen": 0} for _ in range(3)]
    for y in range(0, height, max(1, height // 56)):
        band = 0 if y < height * 0.34 else 1 if y < height * 0.67 else 2
        for x in range(0, width, max(1, width // 56)):
            pixel = pixels[y * width + x]
            red, green, blue = pixel
            level = (red + green + blue) / 3
            spread = max(pixel) - min(pixel)
            bands[band]["seen"] += 1
            if level > 155 and spread < 90 and red > blue + 4 and red > 140 and green > 120:
                bands[band]["page"] += 1
            if green > red + 12 and green > 70:
                bands[band]["leaf"] = bands[band].get("leaf", 0) + 1
            if red > 70 and green > 35 and red >= green >= blue and red > blue + 12 and 12 < spread < 95 and level < 200:
                bands[band]["skin"] += 1
    def share(band, key):
        return bands[band][key] / bands[band]["seen"] if bands[band]["seen"] else 0
    upper_page = (share(0, "page") + share(1, "page")) / 2
    leafy = share(0, "leaf") > 0.08
    if share(2, "skin") > 0.32 and leafy and share(2, "skin") > share(0, "skin") + 0.1 and share(2, "page") < 0.08:
        return "This image shows a book held in a person's hand."
    return ""


def _book_sentence(texts, skin_share, edge_skin, center_skin):
    """A book is the subject. A hand is mentioned only when it is actually in frame."""
    words = [line for line in texts if len(str(line).strip()) > 2]
    if len(words) < 3:
        return ""
    hand = edge_skin > center_skin and skin_share > 0.02
    if hand:
        return "This image shows a book held in a person's hand."
    if skin_share < 0.08:
        return "This image shows a book."
    return ""


def _building_view(pixels, width, height):
    """A house from its shape: a roof, square windows, a door, a wall, or bricks. No eyes required."""
    cols, rows = 40, 28
    grid = []
    for y in range(rows):
        sy = min(height - 1, y * height // rows)
        row = []
        for x in range(cols):
            sx = min(width - 1, x * width // cols)
            row.append(pixels[sy * width + sx])
        grid.append(row)

    def level(pixel):
        return sum(pixel) / 3

    def is_sky(pixel):
        red, green, blue = pixel
        bright = level(pixel)
        return 140 < bright < 215 and max(pixel) - min(pixel) < 38 and blue >= red - 6 and red < blue + 18

    def is_brick(pixel):
        red, green, blue = pixel
        return red > 105 and red > green + 16 and red > blue + 22 and level(pixel) < 185

    sky_cells = sum(is_sky(grid[y][x]) for y in range(rows) for x in range(cols) if y < rows * 0.45)
    sky_share = sky_cells / (cols * rows)
    brick_share = sum(is_brick(grid[y][x]) for y in range(rows) for x in range(cols)) / (cols * rows)
    roofline = []
    for x in range(cols):
        edge = rows - 1
        for y in range(rows):
            if not is_sky(grid[y][x]):
                edge = y
                break
        roofline.append(edge)
    mid = roofline[cols // 2]
    sides = (sum(roofline[:6]) + sum(roofline[-6:])) / 12
    peak = (
        min(roofline) < rows * 0.45
        and max(roofline[0], roofline[-1]) < rows * 0.72
        and sides > mid + 1.5
    )
    roof_rows = 0
    for y in range(1, int(rows * 0.32)):
        darker = [
            level(grid[y][x])
            for x in range(cols)
            if level(grid[y][x]) < level(grid[y - 1][x]) - 22 and not is_sky(grid[y][x])
        ]
        if len(darker) > cols * 0.45 and max(darker) - min(darker) < 75:
            roof_rows += 1
    marks = []
    for y in range(2, rows - 2):
        for x in range(2, cols - 2):
            here = level(grid[y][x])
            left = level(grid[y][x - 2])
            right = level(grid[y][x + 2])
            if here > 150 and here > left + 26 and here > right + 26 and abs(left - right) < 36:
                marks.append((x, y))
    seen = set()
    windows = 0
    for x, y in marks:
        if (x, y) in seen:
            continue
        stack = [(x, y)]
        seen.add((x, y))
        size = 0
        while stack:
            cx, cy = stack.pop()
            size += 1
            for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                if (nx, ny) in marks and (nx, ny) not in seen:
                    seen.add((nx, ny))
                    stack.append((nx, ny))
        if 1 <= size <= 14:
            windows += 1
    door = False
    for x in range(2, cols - 2):
        run = 0
        for y in range(int(rows * 0.35), rows - 1):
            here = level(grid[y][x])
            side = (level(grid[y][x - 2]) + level(grid[y][x + 2])) / 2
            run = run + 1 if abs(here - side) > 28 else 0
            if run >= 5:
                door = True
                break
        if door:
            break
    row_level = [sum(level(grid[y][x]) for x in range(cols)) / cols for y in range(rows)]
    drop = row_level[0] - row_level[min(11, rows - 1)]
    drop_later = row_level[0] - row_level[min(15, rows - 1)]
    top = row_level[0]
    bottom = sum(row_level[int(rows * 0.8):]) / max(1, rows - int(rows * 0.8))
    outside = top > 185 and drop_later > 72 and drop >= 37
    inside = (top > 175 and drop <= 36 and top > bottom + 20) or (drop < 12 and 90 < top < 175 and windows >= 1)
    brick_wall = brick_share > 0.55 and sky_share < 0.12
    parts = []
    if outside:
        parts.append("a roof")
    if windows >= 2:
        parts.append("windows")
    if door and (outside or inside):
        parts.append("a door")
    if brick_share > 0.12 and outside:
        parts.append("brick walls")
    if outside:
        parts.append("a path or road in front")
    if brick_wall:
        return "This image shows a brick wall."
    if outside:
        listed = ", ".join(parts[:4]) or "a roof and windows"
        return f"This image shows the outside of a house, with {listed}."
    if inside:
        return "This image shows the inside of a house, with a light ceiling, windows, and a floor."
    return ""


def _house_sentence(seen, skin_share, top_n, top_level, bot_n, bot_level, sky, window, green_view, bed, wood, fixture):
    """A room or a building, kept apart from a person when the walls are skin-colored."""
    if not seen or not top_n:
        return ""
    ceiling = top_level / top_n
    floor = bot_level / bot_n if bot_n else 0
    outside = False
    inside = skin_share > 0.45 and ceiling > floor + 15 and sky / max(top_n, 1) < 0.35
    if not outside and not inside:
        return ""
    parts = []
    if outside:
        parts.append("a gray roof")
    else:
        parts.append("a light ceiling")
    if window / seen > 0.03:
        parts.append("windows")
    if green_view / seen > 0.02 and not outside:
        parts.append("plants outside the windows")
    if not outside and bed / seen > 0.005:
        parts.append("a bed")
    if not outside and wood / seen > 0.08:
        parts.append("wooden furniture such as a wardrobe or cabinets")
    if floor and not outside:
        parts.append("floor tiles")
    if fixture / seen > 0.04:
        parts.append("a light-colored bathroom fitting")
    if outside and floor:
        parts.append("a path or road in front")
    place = "the outside of a house" if outside else "the inside of a house"
    listed = ", ".join(parts[:5])
    return f"This image shows {place}, with {listed}."


def _grid(pixels, width, height, cols, rows):
    grid = []
    for y in range(rows):
        sy = min(height - 1, y * height // rows)
        row = []
        for x in range(cols):
            sx = min(width - 1, x * width // cols)
            row.append(pixels[sy * width + sx])
        grid.append(row)
    return grid


def _components(mask, cols, rows, minimum):
    seen = [[False] * cols for _ in range(rows)]
    found = []
    for y in range(rows):
        for x in range(cols):
            if seen[y][x] or not mask[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            cells = []
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for ny in range(cy - 1, cy + 2):
                    for nx in range(cx - 1, cx + 2):
                        if 0 <= ny < rows and 0 <= nx < cols and not seen[ny][nx] and mask[ny][nx]:
                            seen[ny][nx] = True
                            stack.append((nx, ny))
            if len(cells) >= minimum:
                found.append(cells)
    return found


def _real_eyes(grid, cells):
    """Two darker spots in a face, with color, the way a photograph shows eyes."""
    levels = [sum(grid[y][x]) / 3 for x, y in cells]
    if not levels:
        return False
    mean = sum(levels) / len(levels)
    dark = [(x, y) for x, y in cells if sum(grid[y][x]) / 3 < mean - 38 and max(grid[y][x]) - min(grid[y][x]) > 8]
    if len(dark) < 2:
        return False
    ys = [y for _x, y in cells]
    top, bottom = min(ys), max(ys)
    upper = [(x, y) for x, y in dark if y <= top + (bottom - top) * 0.65]
    if len(upper) < 2:
        return False
    xs = sorted(x for x, _y in upper)
    return xs[-1] - xs[0] >= 2


def _face_boxes(grid, cols, rows):
    skin_mask = [[_is_skin(grid[y][x]) for x in range(cols)] for y in range(rows)]
    faces = []
    for cells in _components(skin_mask, cols, rows, 6):
        xs = [cell[0] for cell in cells]
        ys = [cell[1] for cell in cells]
        wide = max(xs) - min(xs) + 1
        tall = max(ys) - min(ys) + 1
        if not (2 <= wide <= max(16, cols // 3) and 2 <= tall <= max(20, rows // 4) and len(cells) <= max(140, cols * 2)):
            continue
        if not _real_eyes(grid, cells):
            continue
        faces.append((min(xs), max(xs), min(ys), max(ys)))
    return faces


def _figure_kind(pixels, width, height):
    """A real face plus a body pose. A robot or a statue can copy the pose and still fail."""
    cols, rows = 42, 58
    grid = _grid(pixels, width, height, cols, rows)

    def level(pixel):
        return sum(pixel) / 3

    def spread(pixel):
        return max(pixel) - min(pixel)

    faces = _face_boxes(grid, cols, rows)
    if len(faces) >= 2:
        return "people", len(faces)
    if len(faces) == 1:
        left, right, top, bottom = faces[0]
        mid = (left + right) // 2
        body = 0
        for y in range(bottom + 1, min(rows, bottom + max(8, (bottom - top + 1) * 4))):
            if any(not _is_skin(grid[y][x]) and 25 < level(grid[y][x]) < 230 for x in range(max(0, mid - 3), min(cols, mid + 4))):
                body += 1
        if body >= 4:
            return "person", 1

    black_bg = sum(level(grid[y][x]) < 28 for y in range(rows) for x in range(cols)) / (cols * rows)
    white_bg = sum(level(grid[y][x]) > 228 for y in range(rows) for x in range(cols)) / (cols * rows)
    foreground = []
    for y in range(rows):
        for x in range(cols):
            pixel = grid[y][x]
            bright = level(pixel)
            if 18 < bright < 245:
                foreground.append(pixel)
    if len(foreground) < cols * rows * 0.08:
        return "", 0
    skin_count = sum(_is_skin(pixel) for pixel in foreground)
    skin_share = skin_count / len(foreground)
    green_share = sum(pixel[1] > pixel[0] + 8 and pixel[1] > 40 for pixel in foreground) / len(foreground)
    mean_spread = sum(spread(pixel) for pixel in foreground) / len(foreground)
    dark_head = 0
    head_cells = 0
    ys = []
    for y in range(rows):
        for x in range(cols):
            if 18 < level(grid[y][x]) < 245:
                ys.append(y)
    if not ys:
        return "", 0
    top, bottom = min(ys), max(ys)
    tall = bottom - top + 1
    for y in range(top, min(rows, top + max(3, tall // 7))):
        for x in range(cols):
            pixel = grid[y][x]
            if not (18 < level(pixel) < 245):
                continue
            head_cells += 1
            if level(pixel) < 55 and not _is_skin(pixel):
                dark_head += 1
    mechanical = (
        white_bg > 0.45
        and mean_spread < 16
        and tall > rows * 0.4
        and not faces
    )
    if mechanical:
        return "robot", 0
    stone_skin = [
        pixel for pixel in foreground
        if _is_skin(pixel) or (spread(pixel) < 36 and 120 < level(pixel) < 210)
    ]
    stone = (
        black_bg > 0.2
        and skin_share > 0.45
        and green_share < 0.04
        and mean_spread < 40
        and stone_skin
        and sum(spread(pixel) for pixel in stone_skin) / len(stone_skin) < 32
        and tall > rows * 0.5
        and not faces
    )
    if stone:
        return "statue", 0
    return "", 0


def _band_color(grid, cols, rows, box, y0, y1):
    left, right, top, bottom = box
    face_tall = max(2, bottom - top + 1)
    mid = (left + right) // 2
    span = max(4, cols // 8)
    picked = []
    y_start = min(rows - 1, bottom + int(face_tall * y0))
    y_end = min(rows, bottom + int(face_tall * y1))
    for y in range(y_start, y_end):
        for x in range(max(0, mid - span), min(cols, mid + span + 1)):
            pixel = grid[y][x]
            red, green, blue = pixel
            if _is_skin(pixel):
                continue
            level = sum(pixel) / 3
            if green > red + 12 and green > 70:
                continue
            if blue > red + 40 and blue > green + 15:
                continue
            if 25 < level < 235:
                picked.append(pixel)
    if len(picked) < 4:
        return ""
    names = [_cloth_name(pixel) for pixel in picked]
    return max(set(names), key=names.count)


def _outfit_phrase(pixels, width, height):
    """Clothes under a real face, only when the body continues down the frame."""
    cols, rows = 42, 58
    grid = _grid(pixels, width, height, cols, rows)
    phrases = []
    boxes = sorted(_face_boxes(grid, cols, rows), key=lambda box: (box[0] + box[1]) / 2)
    kept = []
    for box in boxes:
        center = (box[0] + box[1]) / 2
        if any(abs(center - (other[0] + other[1]) / 2) < 6 and box[2] > other[3] for other in kept):
            continue
        kept.append(box)
    for box in kept:
        left, right, top, bottom = box
        face_tall = max(2, bottom - top + 1)
        mid = (left + right) // 2
        below = 0
        for y in range(bottom + 1, min(rows, bottom + face_tall * 4)):
            if any(
                not _is_skin(grid[y][x]) and 25 < sum(grid[y][x]) / 3 < 235
                for x in range(max(0, mid - 3), min(cols, mid + 4))
            ):
                below += 1
        if below < face_tall:
            continue
        top_color = _band_color(grid, cols, rows, box, 0.15, 1.15)
        leg_color = _band_color(grid, cols, rows, box, 1.8, 3.4)
        if not top_color:
            continue
        if leg_color and leg_color != top_color:
            phrases.append(f"a {top_color} top and {leg_color} trousers")
        else:
            phrases.append(f"a {top_color} top")
    return phrases


def _photo_reading(pixels, width, height, texts):
    """A person, a group, or produce, instead of counting squares on a photograph."""
    if width < 8 or height < 8:
        return ""
    skin_rgb = [0, 0, 0]
    center_skin = [0, 0, 0]
    center_skin_count = 0
    skin = dark = colorful = edge_skin = 0
    hues = {"red": 0, "orange": 0, "yellow": 0, "green": 0, "purple": 0}
    quadrants = [0, 0, 0, 0]
    clothing = []
    lower = []
    gray = left_gray = right_gray = 0
    top_n = bot_n = 0
    top_level = bot_level = 0
    sky = window = green_view = 0
    bed = wood = fixture = 0
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
                if x < width * 0.28 or x > width * 0.72:
                    edge_skin += 1
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
            if y < height * 0.2:
                top_n += 1
                top_level += level
                if blue >= red - 4 and level > 170:
                    sky += 1
            if y > height * 0.75:
                bot_n += 1
                bot_level += level
            if y < height * 0.55 and level > 200 and spread < 45:
                window += 1
            if green > red + 12 and green > 70 and y < height * 0.55:
                green_view += 1
            if y > height * 0.4 and ((red > 140 and blue > 80 and green < 120) or (red > 150 and blue < 80 and green < 100)):
                bed += 1
            if 40 < level < 110 and red > blue + 15 and green > blue and y > height * 0.25:
                wood += 1
            if y > height * 0.45 and x > width * 0.55 and level > 185 and spread < 30:
                fixture += 1
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
    building = _building_view(pixels, width, height)
    kind, count = _figure_kind(pixels, width, height)
    if kind == "robot":
        return "This image shows a robot standing in a human pose. It is not a person."
    if kind == "statue":
        return "This image shows a statue in a human pose. It is not a person."
    if kind == "people":
        place = ", sitting outside in front of a building" if building else ""
        outfits = _outfit_phrase(pixels, width, height)
        worn = ""
        if outfits:
            worn = " " + " ".join(f"One is wearing {item}." for item in outfits[:4])
        return (
            f"This image shows {count} people{place}. "
            f"Each one has a head, a torso, and limbs in a human pose.{worn}"
        )
    held = "" if building else _held_book(pixels, width, height)
    if held:
        return held
    floor = bot_level / bot_n if bot_n else 0
    ceiling = top_level / top_n if top_n else 0
    interior = building.startswith("This image shows the inside") if building else False
    if not interior and skin_share > 0.5 and wood / seen > 0.12 and sky / seen < 0.02 and ceiling > floor + 30:
        interior = True
        building = building or "This image shows the inside of a house, with a light ceiling, windows, and a floor."
    figure = "" if interior else _human_form(pixels, width, height)
    if building and kind not in {"person", "people"}:
        figure = ""
    if kind == "person" and not figure:
        outfits = _outfit_phrase(pixels, width, height)
        worn = f" wearing {outfits[0]}" if outfits else ""
        figure = f"This image shows a person standing{worn}"
    if figure and (kind == "person" or building) and "standing" not in figure and "silhouette" not in figure:
        figure = figure.replace("This image shows a full-length person", "This image shows a person standing", 1)
        figure = figure.replace("This image shows a person from the head", "This image shows a person standing, seen from the head", 1)
    if figure and building:
        place = "inside a house" if interior else "in front of a house, outside"
        return figure[:-1] + f", {place}."
    if building and not figure:
        return building
    if figure:
        return figure
    face = "" if building else _face_view(pixels, width, height, texts)
    if face:
        return face
    book = _book_sentence(texts, skin_share, edge_skin, center_skin_count)
    if book:
        return book
    house = _house_sentence(
        seen, skin_share, top_n, top_level, bot_n, bot_level, sky, window, green_view, bed, wood, fixture
    )
    if house:
        return house
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
    if 0.04 < skin_share < 0.55 and False:
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
