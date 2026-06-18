import csv
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from io import StringIO


DEFAULT_SHEET_ID = "1zfw1C4a0PxP1zZFJY4fD4C8x-5_ONDq1CPuwszVDXDo"
DEFAULT_GID = "0"
_CACHE = {"loaded_at": 0, "records": [], "error": None}


FIELD_ALIASES = {
    "created_at": ["fecha", "timestamp", "marca temporal", "created_at", "fecha de envio"],
    "entry_id": ["numero formulario", "numero de formulario", "id", "entrada", "entry id"],
    "legal_name": ["razon social", "razon_social"],
    "representative": ["nombre representante", "representante", "nombre del representante"],
    "stand_name": ["nombre para el stand", "nombre stand", "nombre_para_el_stand", "marca"],
    "city": ["ciudad de origen", "ciudad", "origen"],
    "whatsapp": ["whatsapp", "telefono", "celular", "numero", "numero de whatsapp"],
    "email": ["correo", "correo electronico", "direccion de correo electronico", "email"],
    "socials": ["redes sociales", "redes sociales y/o pagina web", "pagina web", "web"],
    "category": ["categoria", "categoria a participar", "rubro"],
    "products": ["productos a participar", "productos", "producto"],
    "sample": ["muestra de productos", "catalogo", "catalogo o imagenes"],
    "comments": ["preguntas y/o comentarios", "comentarios", "preguntas"],
    "postdata": ["postdata", "posdata"],
    "status": ["estado"],
    "confirmed_stand": ["stand confirmado", "stand", "stand asignado"],
}


def get_form_records(force=False):
    if os.getenv("USE_FORM_SHEET", "true").lower() == "false":
        return []

    ttl = int(os.getenv("FORM_RESPONSES_CACHE_SECONDS", "120"))
    now = time.time()
    if not force and now - _CACHE["loaded_at"] < ttl:
        return list(_CACHE["records"])

    try:
        csv_text = fetch_sheet_csv()
        records = parse_records(csv_text)
        _CACHE.update({"loaded_at": now, "records": records, "error": None})
        return list(records)
    except Exception as error:
        _CACHE.update({"loaded_at": now, "records": [], "error": str(error)})
        print(f"No se pudo consultar Google Sheet de formularios: {error}", flush=True)
        return []


def last_form_error():
    return _CACHE.get("error")


def fetch_sheet_csv():
    timeout = int(os.getenv("FORM_RESPONSES_TIMEOUT", "8"))
    errors = []
    for url in sheet_csv_urls():
        request = urllib.request.Request(url, headers={"User-Agent": "Ori WhatsApp Bot"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                csv_text = response.read().decode("utf-8-sig", errors="replace")
                if looks_like_google_html(csv_text):
                    raise RuntimeError("Google devolvio una pagina HTML en vez del CSV")
                return csv_text
        except urllib.error.HTTPError as error:
            errors.append(f"{url}: Google Sheet respondio {error.code}")
        except urllib.error.URLError as error:
            errors.append(f"{url}: No hubo conexion con Google Sheet: {error}")
        except RuntimeError as error:
            errors.append(f"{url}: {error}")

    detail = errors[-1] if errors else "No hay URL de Google Sheet configurada"
    raise RuntimeError(detail)


def sheet_csv_urls():
    configured_url = os.getenv("FORM_RESPONSES_CSV_URL", "").strip()
    sheet_id = os.getenv("FORM_RESPONSES_SHEET_ID", DEFAULT_SHEET_ID).strip()
    gid = os.getenv("FORM_RESPONSES_GID", DEFAULT_GID).strip()

    if configured_url:
        sheet_id = extract_sheet_id(configured_url) or sheet_id
        gid = extract_gid(configured_url) or gid
        if "format=csv" in configured_url or "tqx=out:csv" in configured_url or "output=csv" in configured_url:
            return unique_urls([configured_url, export_csv_url(sheet_id, gid), gviz_csv_url(sheet_id, gid)])

    return unique_urls([export_csv_url(sheet_id, gid), gviz_csv_url(sheet_id, gid)])


def export_csv_url(sheet_id, gid):
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def gviz_csv_url(sheet_id, gid):
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&gid={gid}"


def extract_sheet_id(url):
    match = re.search(r"/spreadsheets/d/([^/]+)", str(url or ""))
    return match.group(1) if match else ""


def extract_gid(url):
    match = re.search(r"(?:[?&#]gid=)(\d+)", str(url or ""))
    return match.group(1) if match else ""


def unique_urls(urls):
    output = []
    for url in urls:
        if url and url not in output:
            output.append(url)
    return output


def looks_like_google_html(text):
    start = str(text or "").lstrip()[:500].lower()
    return start.startswith("<!doctype") or "<html" in start or "google sheets" in start and "<title" in start


def parse_records(csv_text):
    reader = csv.DictReader(StringIO(csv_text or ""))
    records = []
    for row in reader:
        record = normalize_record(row)
        if has_meaningful_data(record):
            records.append(record)
    return records


def normalize_record(row):
    output = {"raw": dict(row or {})}
    normalized_row = {normalize_key(key): value for key, value in (row or {}).items()}

    for field, aliases in FIELD_ALIASES.items():
        output[field] = ""
        for alias in aliases:
            value = normalized_row.get(normalize_key(alias))
            if value is not None and str(value).strip():
                output[field] = clean_value(value)
                break

    if not output["stand_name"]:
        output["stand_name"] = output["legal_name"]
    if not output["legal_name"]:
        output["legal_name"] = output["stand_name"]
    if output["whatsapp"]:
        output["phone_digits"] = normalize_phone(output["whatsapp"])
    else:
        output["phone_digits"] = ""
    return output


def has_meaningful_data(record):
    return any(record.get(field) for field in ["legal_name", "stand_name", "representative", "whatsapp", "email", "products"])


def find_form_record(query=None, phone=None):
    query_text = normalize(query or "")
    phone_digits = normalize_phone(phone)
    records = get_form_records()

    if phone_digits:
        for record in records:
            record_phone = record.get("phone_digits", "")
            if phones_match(phone_digits, record_phone):
                return record

    if not query_text:
        return None

    best_record = None
    best_score = 0
    for record in records:
        score = record_match_score(record, query_text)
        if score > best_score:
            best_record = record
            best_score = score

    return best_record if best_score >= 2 else None


def filter_form_records(category=None, today_only=False):
    records = get_form_records()
    if category:
        normalized_category = normalize(category)
        records = [
            record
            for record in records
            if normalized_category in normalize(record.get("category") or record.get("products") or "")
        ]
    if today_only:
        today = time.strftime("%Y-%m-%d")
        records = [record for record in records if today in normalize_date(record.get("created_at", ""))]
    return records


def record_match_score(record, query_text):
    haystacks = [
        (record.get("legal_name", ""), 3),
        (record.get("stand_name", ""), 2),
        (record.get("representative", ""), 1),
        (record.get("email", ""), 1),
        (record.get("socials", ""), 1),
    ]
    score = 0
    for value, weight in haystacks:
        text = normalize(value)
        if not text:
            continue
        if query_text == text:
            score += 5 * weight
        elif query_text in text or text in query_text:
            score += 3 * weight
        else:
            shared = set(query_text.split()) & set(text.split())
            if len(shared) >= 2:
                score += len(shared) * weight
    return score


def format_form_record(record):
    if not record:
        return "No encontre esa preinscripcion en la hoja conectada."

    lines = [
        f"Razon social: {record.get('legal_name') or 'sin dato'}",
        f"Representante: {record.get('representative') or 'sin dato'}",
        f"Nombre para stand: {record.get('stand_name') or 'sin dato'}",
        f"Ciudad: {record.get('city') or 'sin dato'}",
        f"WhatsApp: {record.get('whatsapp') or 'sin dato'}",
        f"Correo: {record.get('email') or 'sin dato'}",
        f"Productos: {record.get('products') or 'sin dato'}",
    ]
    if record.get("category"):
        lines.append(f"Categoria: {record['category']}")
    if record.get("sample"):
        lines.append(f"Muestra/catalogo: {record['sample']}")
    if record.get("comments"):
        lines.append(f"Comentarios: {record['comments']}")
    if record.get("confirmed_stand"):
        lines.append(f"Stand confirmado en hoja: {record['confirmed_stand']}")
    return "\n".join(lines)


def record_brand(record):
    return record.get("stand_name") or record.get("legal_name") or "sin marca"


def clean_value(value):
    return re.sub(r"\s+", " ", str(value or "").strip())


def normalize_key(value):
    return normalize(value).replace(" / ", " ").replace("/", " ").strip()


def normalize(value):
    normalized = unicodedata.normalize("NFD", str(value or "").lower())
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    cleaned = re.sub(r"[^a-z0-9@.]+", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_date(value):
    return normalize(value).replace(" ", "-")


def normalize_phone(value):
    return re.sub(r"\D+", "", str(value or ""))


def phones_match(left, right):
    if not left or not right:
        return False
    return left == right or left.endswith(right[-10:]) or right.endswith(left[-10:])
