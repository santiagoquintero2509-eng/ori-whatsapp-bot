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
    extension = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }.get(mime_type, "")
    media_type = media.get("type") or "archivo"
    return f"{media_type}_{int(time.time())}{extension}"


def queue_payload(payload):
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with QUEUE_PATH.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"No se pudo guardar cola de preinscripcion: {error}", flush=True)


def webhook_url():
    return os.getenv("PREINSCRIPTION_WEBHOOK_URL", "").strip()


def webhook_secret():
    return os.getenv("PREINSCRIPTION_WEBHOOK_SECRET", "").strip()


def drive_folder_id():
    return os.getenv("PREINSCRIPTION_DRIVE_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID).strip()
