import base64
import json
import os
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ori import get_ori_reply

try:
    from plano_image import PLANO_STANDS_JPG_BASE64
except ImportError:
    PLANO_STANDS_JPG_BASE64 = ""

try:
    from welcome_images import WELCOME_IMAGES_BASE64
except ImportError:
    WELCOME_IMAGES_BASE64 = {}


def load_env():
    env_path = Path.cwd() / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


load_env()

PORT = int(os.getenv("PORT", "3000"))
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "ori-feria-origen-2027")
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v20.0")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID", "")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "https://ori-whatsapp-bot.onrender.com").rstrip("/")
PLANO_STANDS_URL = os.getenv("PLANO_STANDS_URL", f"{PUBLIC_BASE_URL}/plano_stands.jpg?v=20260619")
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
PREVIOUS_FAIRS_DIR = PUBLIC_DIR / "ferias_anteriores"
WELCOME_IMAGES_DIR = PUBLIC_DIR / "bienvenida"
LAST_PLAN_IMAGE_SENT = {}
LAST_PREVIOUS_FAIR_IMAGES_SENT = {}
PLAN_IMAGE_COOLDOWN_SECONDS = 600
PREVIOUS_FAIR_IMAGES_COOLDOWN_SECONDS = 900
MAX_PREVIOUS_FAIR_IMAGES = 3


class OriHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path == "/":
            self.send_html(home_page())
            return

        if parsed_url.path == "/test":
            params = urllib.parse.parse_qs(parsed_url.query)
            message = params.get("message", ["hola"])[0]
            self.send_json({"message": message, "reply": get_ori_reply(message)})
            return

        if parsed_url.path == "/health":
            self.send_json({"ok": True, "service": "Ori WhatsApp Bot"})
            return

        if parsed_url.path == "/plano_stands.jpg":
            self.send_static_file(PUBLIC_DIR / "plano_stands.jpg", "image/jpeg")
            return

        if parsed_url.path.startswith("/ferias_anteriores/"):
            filename = Path(urllib.parse.unquote(parsed_url.path)).name
            file_path = PREVIOUS_FAIRS_DIR / filename
            content_type = image_content_type(file_path)
            if content_type:
                self.send_static_file(file_path, content_type)
                return
            self.send_json({"error": "Archivo no encontrado"}, status=404)
            return

        if parsed_url.path.startswith("/bienvenida/"):
            filename = Path(urllib.parse.unquote(parsed_url.path)).name
            file_path = WELCOME_IMAGES_DIR / filename
            content_type = image_content_type(file_path)
            if content_type:
                self.send_static_file(file_path, content_type, fallback_base64=WELCOME_IMAGES_BASE64.get(filename, ""))
                return
            self.send_json({"error": "Archivo no encontrado"}, status=404)
            return

        if parsed_url.path == "/webhook":
            self.verify_webhook(parsed_url)
            return

        self.send_json({"error": "Ruta no encontrada"}, status=404)

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)

        if parsed_url.path != "/webhook":
            self.send_json({"error": "Ruta no encontrada"}, status=404)
            return

        payload = self.read_json_body()
        try:
            print("Webhook recibido desde Meta", flush=True)
            handle_whatsapp_payload(payload)
        except Exception as error:
            print(f"Error procesando webhook: {error}", flush=True)
        self.send_json({"ok": True})

    def verify_webhook(self, parsed_url):
        params = urllib.parse.parse_qs(parsed_url.query)
        mode = params.get("hub.mode", [""])[0]
        token = params.get("hub.verify_token", [""])[0]
        challenge = params.get("hub.challenge", [""])[0]

        if mode == "subscribe" and token == VERIFY_TOKEN:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(challenge.encode("utf-8"))
            return

        self.send_response(403)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Token de verificacion invalido".encode("utf-8"))

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length).decode("utf-8")
        return json.loads(raw_body or "{}")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static_file(self, path, content_type, fallback_base64=""):
        if path.name == "plano_stands.jpg" and PLANO_STANDS_JPG_BASE64:
            body = base64.b64decode(PLANO_STANDS_JPG_BASE64)
        elif path.exists() and path.is_file():
            body = path.read_bytes()
        elif fallback_base64:
            body = base64.b64decode(fallback_base64)
        else:
            self.send_json({"error": "Archivo no encontrado"}, status=404)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_message, *args):
        print(format_message % args)


def handle_whatsapp_payload(payload):
    messages = extract_incoming_messages(payload)
    print(f"Mensajes extraidos: {len(messages)}", flush=True)
    for message in messages:
        reply = get_ori_reply(message["text"], user_id=message["from"], incoming_media=message.get("media"))
        print(f"Mensaje de {message['from']}: {message['text'] or message.get('type')}", flush=True)
        print(f"Respuesta de Ori: {reply}", flush=True)
        send_whatsapp_text(message["from"], reply)
        if should_send_plan_image(message["text"], reply) and should_send_plan_image_now(message["from"]):
            send_whatsapp_image(
                message["from"],
                PLANO_STANDS_URL,
                "Plano de stands Feria Origen Colombia 2027.",
            )
        if should_send_previous_fair_images(message["text"]) and should_send_previous_fair_images_now(message["from"]):
            for image_url, caption in fair_gallery_image_urls()[:MAX_PREVIOUS_FAIR_IMAGES]:
                send_whatsapp_image(
                    message["from"],
                    image_url,
                    caption,
                )


def extract_incoming_messages(payload):
    output = []

    if payload.get("field") == "messages" and isinstance(payload.get("value"), dict):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": payload["value"],
                        }
                    ]
                }
            ]
        }

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                message_type = message.get("type")
                if message_type not in {"text", "image", "document"}:
                    continue
                text = message.get("text", {}).get("body", "")
                media = None
                if message_type in {"image", "document"}:
                    media_payload = message.get(message_type, {})
                    text = media_payload.get("caption", "")
                    media = {
                        "type": message_type,
                        "id": media_payload.get("id", ""),
                        "mime_type": media_payload.get("mime_type", ""),
                        "filename": media_payload.get("filename", ""),
                        "sha256": media_payload.get("sha256", ""),
                    }
                output.append(
                    {
                        "from": message.get("from", ""),
                        "text": text,
                        "type": message_type,
                        "media": media,
                    }
                )
    return output


def send_whatsapp_text(to, body):
    if DRY_RUN or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("Envio omitido: DRY_RUN activo o faltan credenciales.", flush=True)
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
            print(f"Respuesta enviada a WhatsApp para {to}", flush=True)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API respondio {error.code}: {detail}") from error


def subscribe_app_to_whatsapp():
    if not WHATSAPP_TOKEN:
        print("Suscripcion omitida: falta WHATSAPP_TOKEN.", flush=True)
        return

    waba_id = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()
    if not waba_id:
        print("Suscripcion omitida: falta WHATSAPP_BUSINESS_ACCOUNT_ID.", flush=True)
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{waba_id}/subscribed_apps"
    data = urllib.parse.urlencode({"subscribed_fields": "messages"}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"App suscrita a mensajes de WhatsApp: {body}", flush=True)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"No se pudo suscribir la app a WhatsApp ({error.code}): {detail}", flush=True)
    except urllib.error.URLError as error:
        print(f"No se pudo conectar para suscribir la app a WhatsApp: {error}", flush=True)


def send_whatsapp_image(to, image_url, caption=""):
    if DRY_RUN or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(f"Envio de imagen omitido. URL del plano: {image_url}", flush=True)
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    image_payload = {"link": image_url}
    if caption:
        image_payload["caption"] = caption

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "image",
        "image": image_payload,
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
            print(f"Plano enviado a WhatsApp para {to}", flush=True)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API respondio {error.code} al enviar imagen: {detail}") from error


def should_send_plan_image(message, reply=""):
    text = normalize_for_match(message)
    reply_text = normalize_for_match(reply)
    triggers = [
        "compartir el plano",
        "comparteme el plano",
        "compartirme el plano",
        "enviar el plano",
        "enviame el plano",
        "enviarme el plano",
        "mandame el plano",
        "mandarme el plano",
        "mostrar el plano",
        "muestrame el plano",
        "mostrarme el plano",
        "ver el plano",
        "plano de la feria",
        "plano del evento",
        "plano del envento",
        "plano de stands",
        "plano evento",
        "plano envento",
        "mapa de stands",
        "ubicacion de stands",
        "ver stands",
        "que stands tienes",
        "que stand tienes",
        "que stands hay",
        "que stand hay",
        "cuales stands tienes",
        "cuales stand tienes",
        "cuales stands hay",
        "opciones de stands",
        "opciones disponibles",
        "stands disponibles",
        "stand disponibles",
        "puestos disponibles",
    ]
    if any(trigger in text for trigger in triggers):
        return True
    return "estos son los stands disponibles cargados" in reply_text or "te comparto el plano actual" in reply_text


def should_send_plan_image_now(user_id):
    now = time.time()
    last_sent = LAST_PLAN_IMAGE_SENT.get(user_id, 0)
    if now - last_sent < PLAN_IMAGE_COOLDOWN_SECONDS:
        return False
    LAST_PLAN_IMAGE_SENT[user_id] = now
    return True


def should_send_previous_fair_images(message):
    text = normalize_for_match(message)
    if not fair_gallery_image_urls():
        return False

    explicit_photo_triggers = [
        "fotos",
        "imagenes",
        "imagen",
        "galeria",
        "imagenes de la feria",
        "fotos de la feria",
        "ferias anteriores",
        "ediciones anteriores",
        "versiones anteriores",
        "ver fotos",
        "ver imagenes",
        "mostrar fotos",
        "mostrar imagenes",
        "compartir fotos",
        "compartir imagenes",
        "mandame fotos",
        "mandame imagenes",
        "enviame fotos",
        "enviame imagenes",
        "como se ve la feria",
        "como ha sido la feria",
    ]

    return any(trigger in text for trigger in explicit_photo_triggers)


def should_send_previous_fair_images_now(user_id):
    now = time.time()
    last_sent = LAST_PREVIOUS_FAIR_IMAGES_SENT.get(user_id, 0)
    if now - last_sent < PREVIOUS_FAIR_IMAGES_COOLDOWN_SECONDS:
        return False
    LAST_PREVIOUS_FAIR_IMAGES_SENT[user_id] = now
    return True


def previous_fair_image_urls():
    if not PREVIOUS_FAIRS_DIR.exists():
        return []

    urls = []
    for path in sorted(PREVIOUS_FAIRS_DIR.iterdir()):
        if path.is_file() and image_content_type(path):
            urls.append(f"{PUBLIC_BASE_URL}/ferias_anteriores/{urllib.parse.quote(path.name)}")
    return urls


def fair_gallery_image_urls():
    previous_urls = [
        (url, "Asi se ha vivido Feria Origen Colombia en ediciones anteriores.")
        for url in previous_fair_image_urls()
    ]
    if previous_urls:
        return previous_urls
    return welcome_image_urls()


def welcome_image_urls():
    return [
        (
            f"{PUBLIC_BASE_URL}/bienvenida/patio_de_las_artes.jpg",
            "Patio de las Artes - Feria Origen Colombia 2027.",
        ),
        (
            f"{PUBLIC_BASE_URL}/bienvenida/patio_de_las_artes_pasillos.jpg",
            "Patio de las Artes, pasillos cubiertos - Feria Origen Colombia 2027.",
        ),
        (
            f"{PUBLIC_BASE_URL}/bienvenida/salon_pierre_daguet.jpg",
            "Salon Pierre Daguet - Feria Origen Colombia 2027.",
        ),
    ]


def image_content_type(path):
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return ""


def normalize_for_match(value):
    normalized = unicodedata.normalize("NFD", str(value or "").lower())
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(without_accents.split())


def home_page():
    return """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ori WhatsApp Bot</title>
  <style>
    body{font-family:Arial,sans-serif;background:#faf7ef;color:#2c2b28;margin:0;padding:32px}
    main{max-width:760px;margin:auto;background:#fffdf8;border:1px solid #ddd3bd;border-radius:8px;padding:24px}
    h1{margin-top:0;font-family:Georgia,serif;font-size:42px}
    form{display:grid;gap:10px;margin-top:18px}
    input,button{font:inherit;border-radius:8px;min-height:44px}
    input{border:1px solid #ddd3bd;padding:0 12px}
    button{border:0;background:#34684d;color:white;font-weight:800;cursor:pointer}
    pre{white-space:pre-wrap;background:#f4ecdc;border-radius:8px;padding:14px}
  </style>
</head>
<body>
  <main>
    <h1>Ori esta lista</h1>
    <p>Prueba preguntas antes de conectar WhatsApp.</p>
    <form onsubmit="event.preventDefault(); testOri();">
      <input id="message" placeholder="Ej: stands disponibles" />
      <button>Preguntar</button>
    </form>
    <pre id="answer">Escribe una pregunta para Ori.</pre>
  </main>
  <script>
    async function testOri(){
      const message = document.getElementById('message').value || 'hola';
      const response = await fetch('/test?message=' + encodeURIComponent(message));
      const data = await response.json();
      document.getElementById('answer').textContent = data.reply;
    }
  </script>
</body>
</html>"""


def main():
    subscribe_app_to_whatsapp()
    server = HTTPServer(("0.0.0.0", PORT), OriHandler)
    print(f"Ori WhatsApp bot escuchando en http://localhost:{PORT}", flush=True)
    print(f"Prueba local: http://localhost:{PORT}/test?message=stands%20disponibles", flush=True)
    if DRY_RUN:
        print("DRY_RUN=true: las respuestas se muestran en consola y no se envian a WhatsApp.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
