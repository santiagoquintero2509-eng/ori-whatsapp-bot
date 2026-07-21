import io
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from form_responses import filter_form_records


PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
PLAN_BASE_PATH = PUBLIC_DIR / "plano_stands.png"
FALLBACK_PLAN_PATH = PUBLIC_DIR / "plano_stands.jpg"
MAX_STAND_NUMBER = 64

PLAN_COORDINATES = {
    45: (188, 280),
    44: (233, 280),
    43: (277, 280),
    42: (320, 280),
    41: (364, 280),
    40: (407, 280),
    39: (450, 280),
    38: (529, 281),
    37: (572, 281),
    46: (97, 311),
    47: (97, 357),
    48: (97, 405),
    49: (97, 452),
    50: (97, 498),
    51: (97, 545),
    52: (97, 591),
    53: (97, 638),
    54: (97, 685),
    55: (97, 732),
    36: (600, 352),
    35: (600, 396),
    34: (600, 440),
    33: (600, 483),
    32: (600, 527),
    31: (600, 614),
    30: (600, 657),
    29: (600, 701),
    56: (168, 786),
    57: (211, 786),
    58: (255, 786),
    59: (298, 786),
    60: (342, 786),
    61: (385, 786),
    62: (428, 786),
    63: (471, 786),
    64: (515, 786),
    12: (663, 270),
    11: (801, 270),
    13: (663, 324),
    10: (800, 324),
    22: (652, 429),
    23: (652, 483),
    24: (652, 527),
    25: (652, 614),
    26: (652, 658),
    27: (652, 718),
    21: (722, 486),
    14: (752, 486),
    20: (722, 548),
    15: (752, 548),
    19: (722, 665),
    16: (752, 665),
    18: (722, 718),
    17: (752, 718),
    9: (812, 429),
    8: (812, 483),
    7: (812, 527),
    6: (812, 571),
    5: (812, 614),
    4: (812, 658),
    3: (812, 701),
    2: (812, 762),
    28: (687, 833),
    1: (795, 878),
}


def dynamic_plan_media():
    base_path = PLAN_BASE_PATH if PLAN_BASE_PATH.exists() else FALLBACK_PLAN_PATH
    if not base_path.exists():
        return None

    image = Image.open(base_path).convert("RGBA")
    draw_available_stand_numbers(image, occupied_stands_from_sheet())
    output = io.BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=95)
    return {
        "filename": "plano_stands_disponibles.jpg",
        "mime_type": "image/jpeg",
        "content": output.getvalue(),
    }


def occupied_stands_from_sheet():
    occupied = set()
    for record in filter_form_records(force=True):
        for stand in stand_numbers_from_value(record.get("confirmed_stand")):
            occupied.add(stand)
    return occupied


def stand_numbers_from_value(value):
    numbers = []
    for match in re.findall(r"\d{1,3}", str(value or "")):
        stand = int(match)
        if 1 <= stand <= MAX_STAND_NUMBER and stand not in numbers:
            numbers.append(stand)
    return numbers


def draw_available_stand_numbers(image, occupied):
    draw = ImageDraw.Draw(image)
    font = load_font(19)
    small_font = load_font(17)

    for stand, (x, y) in PLAN_COORDINATES.items():
        if stand in occupied:
            continue
        label = f"{stand:02d}" if stand < 10 else str(stand)
        selected_font = small_font if len(label) >= 2 else font
        bbox = draw.textbbox((0, 0), label, font=selected_font)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        draw.text(
            (x - width / 2, y - height / 2 - 1),
            label,
            font=selected_font,
            fill=(255, 255, 255, 255),
        )


@lru_cache(maxsize=8)
def load_font(size):
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/Arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()
