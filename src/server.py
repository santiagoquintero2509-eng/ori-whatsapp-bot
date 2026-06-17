import json
import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from ori import get_ori_reply


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
            handle_whatsapp_payload(payload)
        except Exception as error:
            print(f"Error procesando webhook: {error}")
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

    def log_message(self, format_message, *args):
        print(format_message % args)


def handle_whatsapp_payload(payload):
    for message in extract_incoming_messages(payload):
        reply = get_ori_reply(message["text"])
        print(f"Mensaje de {message['from']}: {message['text']}")
        print(f"Respuesta de Ori: {reply}")
        send_whatsapp_text(message["from"], reply)


def extract_incoming_messages(payload):
    output = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                if message.get("type") != "text":
                    continue
                output.append(
                    {
                        "from": message.get("from", ""),
                        "text": message.get("text", {}).get("body", ""),
                    }
                )
    return output


def send_whatsapp_text(to, body):
    if DRY_RUN or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
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
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API respondio {error.code}: {detail}") from error


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
    server = HTTPServer(("0.0.0.0", PORT), OriHandler)
    print(f"Ori WhatsApp bot escuchando en http://localhost:{PORT}")
    print(f"Prueba local: http://localhost:{PORT}/test?message=stands%20disponibles")
    if DRY_RUN:
        print("DRY_RUN=true: las respuestas se muestran en consola y no se envian a WhatsApp.")
    server.serve_forever()


if __name__ == "__main__":
    main()
