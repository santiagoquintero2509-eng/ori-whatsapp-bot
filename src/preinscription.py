import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DRIVE_FOLDER_ID = "1-R2LEdh_m8bregAIy-uTOXRJRNlNyVEm"
QUEUE_PATH = Path(os.getenv("ORI_PREINSCRIPTION_QUEUE_PATH", "memoria_revisable/preinscripciones_pendientes.jsonl"))


def submit_preinscription(data):
    payload = {
        "action": "submit_preinscription",
        "secret": webhook_secret(),
        "drive_folder_id": drive_folder_id(),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }
    return post_to_webhook_or_queue(payload)


def update_confirmed_stand(query, stand, representative=""):
    payload = {
        "action": "update_confirmed_stand",
        "secret": webhook_secret(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "representative": representative,
        "stand": str(stand),
        "status": "stand confirmado",
        "confirmed_by": "Ori admin",
    }
    return post_to_webhook_or_queue(payload)


def delete_preinscription_by_chat_phone(phone):
    payload = {
        "action": "delete_preinscription_by_chat_phone",
        "secret": webhook_secret(),
        "deleted_at": datetime.now(timezone.utc).isoformat(),
        "phone": normalize_phone(phone),
    }
    return post_to_webhook_or_queue(payload)


def upload_product_media(legal_name, media, whatsapp_token, graph_version):
    if not media:
        return {"ok": False, "queued": False, "error": "No llego archivo para subir."}

    if not webhook_url():
        payload = {
            "action": "upload_file",
            "secret": webhook_secret(),
            "drive_folder_id": drive_folder_id(),
            "legal_name": legal_name,
            "media": media,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "note": "Falta configurar PREINSCRIPTION_WEBHOOK_URL para subir este archivo a Drive.",
        }
        queue_payload(payload)
        return {"ok": False, "queued": True, "error": "Falta configurar el enlace de Google Apps Script."}

    if not whatsapp_token:
        payload = {
            "action": "upload_file",
            "secret": webhook_secret(),
            "drive_folder_id": drive_folder_id(),
            "legal_name": legal_name,
            "media": media,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "note": "Falta WHATSAPP_TOKEN para descargar el archivo desde Meta.",
        }
        queue_payload(payload)
        return {"ok": False, "queued": True, "error": "Falta token de WhatsApp para descargar el archivo."}

    try:
        content, mime_type, filename = download_whatsapp_media(media, whatsapp_token, graph_version)
    except Exception as error:
        payload = {
            "action": "upload_file",
            "secret": webhook_secret(),
            "drive_folder_id": drive_folder_id(),
            "legal_name": legal_name,
            "media": media,
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "error": str(error),
        }
        queue_payload(payload)
        return {"ok": False, "queued": True, "error": str(error)}

    payload = {
        "action": "upload_file",
        "secret": webhook_secret(),
        "drive_folder_id": drive_folder_id(),
        "legal_name": legal_name,
        "filename": filename,
        "mime_type": mime_type,
        "base64": base64.b64encode(content).decode("ascii"),
    }
    result = post_to_webhook_or_queue(payload)
    if result.get("ok") and result.get("folder_url"):
        return {
            "ok": True,
            "queued": False,
            "file_url": result.get("file_url"),
            "folder_url": result.get("folder_url"),
            "filename": filename,
        }
    return result


def post_to_webhook_or_queue(payload):
    url = webhook_url()
    if not url:
        queue_payload(payload)
        return {"ok": False, "queued": True, "error": "Falta configurar PREINSCRIPTION_WEBHOOK_URL."}

    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
        parsed = json.loads(body or "{}")
        if not parsed.get("ok"):
            raise RuntimeError(parsed.get("error") or body or "Apps Script no confirmo la operacion.")
        return parsed
    except Exception as error:
        payload = dict(payload)
        payload["queued_at"] = datetime.now(timezone.utc).isoformat()
        payload["error"] = str(error)
        queue_payload(payload)
        return {"ok": False, "queued": True, "error": str(error)}


def pending_queue_items():
    if not QUEUE_PATH.exists():
        return []

    items = []
    try:
        with QUEUE_PATH.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    items.append(payload)
    except OSError as error:
        print(f"No se pudo leer cola de preinscripcion: {error}", flush=True)
    return items


def retry_pending_queue():
    items = pending_queue_items()
    if not items:
        return {"ok": True, "total": 0, "sent": 0, "failed": 0, "remaining": 0, "failures": []}

    sent = 0
    remaining = []
    failures = []

    for payload in items:
        if payload.get("action") == "upload_file" and not payload.get("base64"):
            remaining.append(payload)
            failures.append(queue_item_label(payload) + ": archivo sin contenido descargable")
            continue

        try:
            result = post_payload_once(payload)
            if result.get("ok"):
                sent += 1
            else:
                raise RuntimeError(result.get("error") or "Apps Script no confirmo la operacion.")
        except Exception as error:
            payload = dict(payload)
            payload["last_retry_at"] = datetime.now(timezone.utc).isoformat()
            payload["error"] = str(error)
            remaining.append(payload)
            failures.append(queue_item_label(payload) + f": {error}")

    rewrite_queue(remaining)
    return {
        "ok": not remaining,
        "total": len(items),
        "sent": sent,
        "failed": len(remaining),
        "remaining": len(remaining),
        "failures": failures[:5],
    }


def remove_pending_preinscriptions_for_phone(phone):
    target = normalize_phone(phone)
    if not target:
        return 0

    items = pending_queue_items()
    if not items:
        return 0

    kept = []
    removed = 0
    for payload in items:
        if queued_payload_matches_phone(payload, target):
            removed += 1
            continue
        kept.append(payload)

    if removed:
        rewrite_queue(kept)
    return removed


def queued_payload_matches_phone(payload, target_phone):
    data = payload.get("data") or {}
    candidates = [
        payload.get("phone"),
        data.get("whatsapp"),
        data.get("telefono_chat"),
    ]
    return any(phones_match(normalize_phone(candidate), target_phone) for candidate in candidates)


def post_payload_once(payload):
    url = webhook_url()
    if not url:
        raise RuntimeError("Falta configurar PREINSCRIPTION_WEBHOOK_URL.")

    clean_payload = dict(payload)
    clean_payload["secret"] = webhook_secret()
    clean_payload.setdefault("drive_folder_id", drive_folder_id())
    clean_payload.pop("queued_at", None)
    clean_payload.pop("last_retry_at", None)
    clean_payload.pop("error", None)
    clean_payload.pop("note", None)

    data = json.dumps(clean_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", errors="replace")
    parsed = json.loads(body or "{}")
    if not parsed.get("ok"):
        raise RuntimeError(parsed.get("error") or body or "Apps Script no confirmo la operacion.")
    return parsed


def rewrite_queue(items):
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not items:
            if QUEUE_PATH.exists():
                QUEUE_PATH.unlink()
            return
        with QUEUE_PATH.open("w", encoding="utf-8") as file:
            for payload in items:
                file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"No se pudo reescribir cola de preinscripcion: {error}", flush=True)


def queue_item_label(payload):
    action = payload.get("action") or "accion"
    data = payload.get("data") or {}
    if action == "submit_preinscription":
        return data.get("razon_social") or data.get("nombre_para_stand") or "preinscripcion sin nombre"
    if action == "upload_file":
        return payload.get("legal_name") or payload.get("filename") or "archivo pendiente"
    return action


def download_whatsapp_media(media, whatsapp_token, graph_version):
    media_id = media.get("id")
    if not media_id:
        raise RuntimeError("El archivo no trae media_id de WhatsApp.")

    info_url = f"https://graph.facebook.com/{graph_version}/{media_id}"
    info = json_request(info_url, whatsapp_token)
    media_url = info.get("url")
    if not media_url:
        raise RuntimeError("Meta no devolvio la URL del archivo.")

    request = urllib.request.Request(media_url, headers={"Authorization": f"Bearer {whatsapp_token}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read()

    mime_type = media.get("mime_type") or info.get("mime_type") or "application/octet-stream"
    filename = clean_filename(media.get("filename") or default_media_filename(media, mime_type))
    return content, mime_type, filename


def json_request(url, token):
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8", errors="replace") or "{}")


def clean_filename(value):
    name = re.sub(r"[^\w.\- ]+", "_", str(value or "").strip())
    name = re.sub(r"\s+", "_", name)
    return name[:120] or f"archivo_{int(time.time())}"


def default_media_filename(media, mime_type):
    clean_mime_type = str(mime_type or "").split(";", 1)[0].strip().lower()
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/webm": ".webm",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
    }.get(clean_mime_type, "")
    media_type = media.get("type") or "archivo"
    return f"{media_type}_{int(time.time())}{extension}"


def queue_payload(payload):
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"No se pudo guardar cola de preinscripcion: {error}", flush=True)


def normalize_phone(value):
    return re.sub(r"\D+", "", str(value or ""))


def phones_match(left, right):
    if not left or not right:
        return False
    return left == right or left.endswith(right[-10:]) or right.endswith(left[-10:])


def webhook_url():
    return os.getenv("PREINSCRIPTION_WEBHOOK_URL", "").strip()


def webhook_secret():
    return os.getenv("PREINSCRIPTION_WEBHOOK_SECRET", "").strip()


def drive_folder_id():
    return os.getenv("PREINSCRIPTION_DRIVE_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID).strip()
