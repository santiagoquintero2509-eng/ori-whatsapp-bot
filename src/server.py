import atexit
import base64
import json
import os
import queue
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from groq_client import GroqClientError, transcribe_audio_with_groq
from ori import (
    admin_guided_confirmed_rows,
    admin_guided_menu_text,
    admin_guided_preinscribed_rows,
    admin_guided_record_detail,
    admin_confirmed_records_text,
    admin_prepare_guided_assignment,
    admin_prepare_guided_release,
    available_stands_text,
    admin_chat_phone_list_reply,
    get_memory,
    get_ori_reply,
    is_admin_entry_message,
    is_admin_exit_message,
    is_admin_session_active,
    remember_turn,
    save_persistent_state,
    select_preinscription_category,
    start_preinscription_flow,
)
from preinscription import download_whatsapp_media, log_conversation_event
from form_responses import filter_form_records, last_form_error

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
PLANO_STANDS_URL = os.getenv("PLANO_STANDS_URL", f"{PUBLIC_BASE_URL}/plano_stands.jpg?v=20260703")
CODE_VERSION = "visitor-consistent-menu-20260714"
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
PREVIOUS_FAIRS_DIR = PUBLIC_DIR / "ferias_anteriores"
WELCOME_IMAGES_DIR = PUBLIC_DIR / "bienvenida"
FIRST_FAIRS_DIR = PUBLIC_DIR / "primera_feria"
ORI_WELCOME_IMAGE_URL = f"{PUBLIC_BASE_URL}/bienvenida/ori_colombia.png"
LAST_PLAN_IMAGE_SENT = {}
LAST_PREVIOUS_FAIR_IMAGES_SENT = {}
PLAN_IMAGE_COOLDOWN_SECONDS = 600
PREVIOUS_FAIR_IMAGES_COOLDOWN_SECONDS = 900
MAX_PREVIOUS_FAIR_IMAGES = 3
MEDIA_DELIVERY_DELAY_SECONDS = float(os.getenv("MEDIA_DELIVERY_DELAY_SECONDS", "8"))
HISTORY_LOG_ASYNC = os.getenv("HISTORY_LOG_ASYNC", "true").lower() == "true"
HISTORY_LOG_QUEUE_MAX = int(os.getenv("HISTORY_LOG_QUEUE_MAX", "500"))
HISTORY_LOG_QUEUE = queue.Queue(maxsize=max(HISTORY_LOG_QUEUE_MAX, 0))
HISTORY_LOG_WORKER_LOCK = threading.Lock()
HISTORY_LOG_WORKER_STARTED = False
WELCOME_BUTTON_TEXT = (
    "Hola, soy Ori Colombia, tu asistente virtual de Feria Origen Colombia.\n\n"
    "¡Me alegra saludarte! Origen Colombia es una feria para descubrir y conectar con el talento colombiano: "
    "arte, diseño, moda, joyería, gastronomía, artesanías, bienestar, cultura, expositores internacionales "
    "y emprendimientos con identidad.\n\n"
    "Puedo ayudarte con información del evento y el proceso para participar como expositor.\n\n"
    "¿Qué te gustaría hacer primero?"
)
WELCOME_BUTTONS = [
    {"id": "ORI_EXPOSITOR", "title": "Quiero exponer"},
    {"id": "ORI_VISITANTE", "title": "Quiero visitar"},
]
MAIN_MENU_TEXT = "Elige una opción para que pueda ayudarte mejor:"
MAIN_MENU_BUTTONS = WELCOME_BUTTONS
WELCOME_BUTTON_TEXT = (
    "Hola, soy Ori Colombia, tu asistente virtual de Feria Origen Colombia.\n\n"
    "¡Me alegra saludarte! Origen Colombia es una feria para descubrir y conectar con el talento colombiano: "
    "arte, diseño, moda, joyería, gastronomía, artesanías, bienestar, cultura, expositores internacionales "
    "y emprendimientos con identidad.\n\n"
    "Puedo ayudarte con información del evento y el proceso para participar como expositor.\n\n"
    "¿Qué te gustaría hacer primero?"
)
WELCOME_BUTTONS = [
    {"id": "ORI_EXPOSITOR", "title": "Expositor"},
    {"id": "ORI_VISITANTE", "title": "Visitante"},
]
MAIN_MENU_BUTTONS = WELCOME_BUTTONS
EXHIBITOR_MENU_TEXT = (
    "¡Qué buena noticia que estés pensando en participar como expositor!\n\n"
    "Los stands tienen valores entre $3.300.000 y $6.000.000 COP, según zona, medida y tipo de stand.\n\n"
    "Todos los stands incluyen:\n"
    "- 3 muros blancos en stands generales.\n"
    "- 2 muros blancos en stands esquineros.\n"
    "- 1 mesa de 120 x 60 cm.\n"
    "- 1 estante con 2 puestos de 180 cm.\n\n"
    "También puedes hablar con un asesor aquí:\n"
    "https://wa.me/573160282537\n\n"
    "¿Qué te gustaría hacer primero?"
)
EXHIBITOR_MENU_BUTTONS = [
    {"id": "ORI_EXP_PREINSCRIPCION", "title": "Preinscripción"},
    {"id": "ORI_EXP_PLANO", "title": "Plano de venta"},
    {"id": "ORI_EXP_IMAGENES", "title": "Imágenes"},
]
EXHIBITOR_MENU_TEXT = (
    "¡Qué bueno que estés pensando en participar como expositor!\n\n"
    "La próxima Feria Origen Colombia será del 02 al 14 de enero de 2027 en el convento San Diego sede UNIBAC, "
    "centro histórico Cartagena de Indias.\n\n"
    "Las categorías participantes son: arte, artesanía típica, joyería, calzado y vestuario, decoración, "
    "anticuarios, salud, belleza y gastronomía.\n\n"
    "Hay dos espacios de exposición durante los 13 días de feria:\n\n"
    "Patio de las Artes: stands ubicados en los pasillos, alrededor del claustro colonial. "
    "La zona cuenta con ventiladores de gran formato.\n\n"
    "Salón Pierre Daguet: antigua capilla del convento San Diego, salón climatizado con aire acondicionado.\n\n"
    "¿Qué te gustaría revisar ahora?"
)
EXHIBITOR_MENU_BUTTONS = [
    {"id": "ORI_EXP_TRAYECTORIA", "title": "Trayectoria"},
    {"id": "ORI_EXP_PLANO", "title": "Plano de venta"},
    {"id": "ORI_EXP_PREINSCRIPCION", "title": "Preinscripción"},
    {"id": "ORI_EXP_IMAGENES", "title": "Imágenes"},
]
EXHIBITOR_MENU_ROWS = [
    {"id": "ORI_EXP_TRAYECTORIA", "title": "Trayectoria", "description": "Historia y recorrido de la feria."},
    {"id": "ORI_EXP_IMAGENES", "title": "Imágenes", "description": "Ver fotos de los espacios."},
    {"id": "ORI_EXP_PLANO", "title": "Plano de venta", "description": "Ver ubicaciones y valores."},
    {"id": "ORI_EXP_STANDS_DISPONIBLES", "title": "Stands disponibles", "description": "Ver stands libres por zona."},
    {"id": "ORI_EXP_PREINSCRIPCION", "title": "Preinscripción", "description": "Iniciar el formulario por WhatsApp."},
    {"id": "ORI_MENU", "title": "Volver al menú", "description": "Regresar al inicio."},
]
EXHIBITOR_TRAJECTORY_TEXT = (
    "¡Claro! Te cuento un poco sobre la trayectoria de Feria Origen Colombia.\n\n"
    "Feria Origen Colombia nace como un espacio comercial y cultural creado para visibilizar el talento colombiano.\n\n"
    "Es una plataforma que conecta marcas con visitantes y genera experiencias alrededor del arte, el diseño, "
    "la moda, la joyería, la gastronomía, la artesanía, el bienestar y los emprendimientos con identidad colombiana, "
    "integrando saberes y oficios ancestrales con propuestas de vanguardia y una selección de participantes internacionales.\n\n"
    "A lo largo de su trayectoria, la feria ha consolidado una comunidad de expositores, creadores y visitantes "
    "que cada año se reúnen en Cartagena de Indias para celebrar y exponer lo hecho en Colombia.\n\n"
    "La feria cuenta con el apoyo de la Institución Universitaria Bellas Artes y Ciencias de Bolívar, UNIBAC, "
    "en cuyas instalaciones se realiza el evento. Este espacio está ubicado en un magnífico convento colonial, "
    "declarado Monumento Nacional, actualmente restaurado y adecuado con todas las facilidades para funcionar "
    "como centro académico y de exposiciones.\n\n"
    "Su ubicación estratégica en la Plaza de San Diego lo convierte en un referente importante dentro del Centro "
    "Histórico de Cartagena, rodeado de atractivos culturales y turísticos como el Hotel Sofitel Legend Santa Clara, "
    "el mercado artesanal de Las Bóvedas, galerías, restaurantes y espacios históricos de talla internacional.\n\n"
    "Gracias a este entorno, la experiencia de Feria Origen Colombia trasciende lo comercial y se convierte también "
    "en una vivencia cultural, turística y patrimonial.\n\n"
    "Con 22 años de experiencia, 28 ferias realizadas, más de 1.000 expositores participantes y una asistencia anual "
    "superior a 8.000 visitantes, Feria Origen Colombia se ha consolidado como una plataforma de encuentro, promoción "
    "y comercialización para el talento creativo colombiano, con entrada libre para el público visitante.\n\n"
    "Te comparto algunas imágenes de las primeras ferias."
)
EXHIBITOR_AFTER_TRAJECTORY_ROWS = EXHIBITOR_MENU_ROWS
VISITOR_MENU_TEXT = (
    "¡Qué alegría que quieras visitar la feria!\n\n"
    "La entrada para visitantes es 100% gratuita. Puedo ayudarte con información del evento, "
    "cómo llegar o los productos que encontrarás."
)
VISITOR_MENU_BUTTONS = [
    {"id": "ORI_VIS_INFO", "title": "Info feria"},
    {"id": "ORI_VIS_LLEGAR", "title": "Cómo llegar"},
    {"id": "ORI_VIS_PRODUCTOS", "title": "Productos"},
]
VISITOR_MENU_ROWS = [
    {"id": "ORI_VIS_INFO", "title": "Info feria", "description": "Fechas, acceso y datos generales."},
    {"id": "ORI_VIS_TRAYECTORIA", "title": "Trayectoria", "description": "Historia y recorrido de la feria."},
    {"id": "ORI_VIS_LLEGAR", "title": "Cómo llegar", "description": "Ubicación y ruta en Google Maps."},
    {"id": "ORI_VIS_PRODUCTOS", "title": "Productos", "description": "Lo que encontrarás en la feria."},
    {"id": "ORI_VIS_IMAGENES", "title": "Imágenes", "description": "Fotos de la feria y espacios."},
    {"id": "ORI_MENU", "title": "Volver al menú", "description": "Regresar al inicio."},
]
VISITOR_AFTER_TRAJECTORY_ROWS = VISITOR_MENU_ROWS
VISITOR_INFO_LIST_ROWS = [
    {"id": "ORI_VIS_PRODUCTOS", "title": "Productos", "description": "Productos que encontrarás."},
    {"id": "ORI_VIS_TRAYECTORIA", "title": "Trayectoria", "description": "Historia y recorrido de la feria."},
    {"id": "ORI_VIS_PROMOCIONES", "title": "Promociones", "description": "Ofertas o novedades disponibles."},
    {"id": "ORI_VIS_IMAGENES", "title": "Imágenes", "description": "Fotos de la feria y espacios."},
    {"id": "ORI_MENU", "title": "Volver al menú", "description": "Regresar al inicio."},
]
VISITOR_PRODUCT_CATEGORY_ROWS = [
    {"id": "ORI_VIS_CAT_ARTE", "title": "Arte", "description": "Obras, piezas y propuestas creativas."},
    {"id": "ORI_VIS_CAT_ARTESANIA", "title": "Artesanía", "description": "Técnicas tradicionales y hechas a mano."},
    {"id": "ORI_VIS_CAT_JOYERIA", "title": "Joyería", "description": "Piezas de autor y accesorios especiales."},
    {"id": "ORI_VIS_CAT_CALZADO", "title": "Calzado y vestuario", "description": "Moda, prendas, cuero y complementos."},
    {"id": "ORI_VIS_CAT_DECORACION", "title": "Decoración", "description": "Objetos para hogar y espacios con identidad."},
    {"id": "ORI_VIS_CAT_ANTICUARIOS", "title": "Anticuarios", "description": "Piezas con historia, colección y memoria."},
    {"id": "ORI_VIS_CAT_SALUD", "title": "Salud y belleza", "description": "Bienestar, cuidado personal y belleza."},
    {"id": "ORI_VIS_CAT_GASTRONOMIA", "title": "Gastronomía", "description": "Sabores, productos y experiencias locales."},
    {"id": "ORI_VIS_CAT_OTRO", "title": "Otro", "description": "Ver otras propuestas participantes."},
    {"id": "ORI_MENU", "title": "Volver al menú", "description": "Regresar al inicio."},
]
VISITOR_CATEGORY_BY_BUTTON = {
    "ORI_VIS_CAT_ARTE": "Arte",
    "ORI_VIS_CAT_ARTESANIA": "Artesanía típica",
    "ORI_VIS_CAT_JOYERIA": "Joyería",
    "ORI_VIS_CAT_CALZADO": "Calzado y vestuario",
    "ORI_VIS_CAT_DECORACION": "Decoración",
    "ORI_VIS_CAT_ANTICUARIOS": "Anticuarios",
    "ORI_VIS_CAT_SALUD": "Salud y belleza",
    "ORI_VIS_CAT_GASTRONOMIA": "Gastronomía",
    "ORI_VIS_CAT_OTRO": "",
}
VISITOR_CATEGORY_DESCRIPTIONS = {
    "Arte": "Arte reúne obras, piezas visuales y propuestas creativas con sello colombiano.",
    "Artesanía típica": "Artesanía es ideal para descubrir técnicas tradicionales, trabajo hecho a mano y objetos con identidad cultural.",
    "Joyería": "Joyería incluye piezas de autor, accesorios y detalles creados por marcas y talleres colombianos.",
    "Calzado y vestuario": "Calzado y vestuario presenta moda, prendas, cuero, complementos y propuestas de diseño colombiano.",
    "Decoración": "Decoración trae objetos para el hogar, detalles para espacios y piezas con carácter artesanal o de diseño.",
    "Anticuarios": "Anticuarios es para quienes disfrutan piezas con historia, colección, memoria y encanto clásico.",
    "Salud y belleza": "Salud y belleza conecta con bienestar, cuidado personal, cosmética, aromas y productos para sentirse bien.",
    "Gastronomía": "Gastronomía reúne sabores, productos locales, alimentos especiales y experiencias para probar en la feria.",
    "": "Aquí reunimos otras propuestas especiales que también hacen parte de la feria.",
}
EXHIBITOR_AFTER_REPLY_BUTTONS = EXHIBITOR_MENU_ROWS
EXHIBITOR_AFTER_PLAN_ROWS = EXHIBITOR_MENU_ROWS
EXHIBITOR_CATEGORY_ROWS = [
    {"id": "ORI_PRE_CAT_ARTE", "title": "Arte", "description": "Obras, piezas y propuestas creativas."},
    {"id": "ORI_PRE_CAT_ARTESANIA", "title": "Artesanía típica", "description": "Técnicas tradicionales y hechas a mano."},
    {"id": "ORI_PRE_CAT_JOYERIA", "title": "Joyería", "description": "Piezas de autor y accesorios."},
    {"id": "ORI_PRE_CAT_CALZADO", "title": "Calzado y vestuario", "description": "Moda, prendas, cuero y complementos."},
    {"id": "ORI_PRE_CAT_DECORACION", "title": "Decoración", "description": "Objetos para hogar y espacios."},
    {"id": "ORI_PRE_CAT_ANTICUARIOS", "title": "Anticuarios", "description": "Piezas con historia y colección."},
    {"id": "ORI_PRE_CAT_SALUD", "title": "Salud y belleza", "description": "Bienestar, cuidado personal y belleza."},
    {"id": "ORI_PRE_CAT_GASTRONOMIA", "title": "Gastronomía", "description": "Sabores, productos y experiencias."},
]
EXHIBITOR_CATEGORY_BY_BUTTON = {
    "ORI_PRE_CAT_ARTE": "Arte",
    "ORI_PRE_CAT_ARTESANIA": "Artesanía típica",
    "ORI_PRE_CAT_JOYERIA": "Joyería",
    "ORI_PRE_CAT_CALZADO": "Calzado y vestuario",
    "ORI_PRE_CAT_DECORACION": "Decoración",
    "ORI_PRE_CAT_ANTICUARIOS": "Anticuarios",
    "ORI_PRE_CAT_SALUD": "Salud y belleza",
    "ORI_PRE_CAT_GASTRONOMIA": "Gastronomía",
}
EXHIBITOR_AFTER_IMAGES_BUTTONS = EXHIBITOR_MENU_ROWS
EXHIBITOR_AFTER_PREINSCRIPTION_BUTTONS = EXHIBITOR_MENU_ROWS
PREINSCRIPTION_CONFIRM_BUTTONS = [
    {"id": "ORI_PRE_CONFIRM", "title": "Sí, confirmar"},
    {"id": "ORI_PRE_EDIT", "title": "Cambiar un dato"},
    {"id": "ORI_PRE_CANCEL", "title": "Cancelar"},
]
VISITOR_AFTER_REPLY_BUTTONS = VISITOR_MENU_ROWS
VISITOR_AFTER_ARRIVAL_BUTTONS = [
    {"id": "ORI_VIS_CERCA", "title": "Lugares cerca", "description": "Sitios de interés alrededor."},
    {"id": "ORI_VIS_INFO", "title": "Info feria", "description": "Fechas, acceso y datos generales."},
    {"id": "ORI_VIS_TRAYECTORIA", "title": "Trayectoria", "description": "Historia y recorrido de la feria."},
    {"id": "ORI_VIS_PRODUCTOS", "title": "Productos", "description": "Lo que encontrarás en la feria."},
    {"id": "ORI_VIS_IMAGENES", "title": "Imágenes", "description": "Fotos de la feria y espacios."},
    {"id": "ORI_MENU", "title": "Volver al menú", "description": "Regresar al inicio."},
]
VISITOR_AFTER_NEARBY_BUTTONS = VISITOR_MENU_ROWS
VISITOR_AFTER_IMAGES_BUTTONS = VISITOR_MENU_ROWS
ADMIN_MENU_BUTTONS = [
    {"id": "ORI_ADM_PREINSCRITOS", "title": "Preinscritos"},
    {"id": "ORI_ADM_CONFIRMADOS", "title": "Confirmados"},
    {"id": "ORI_ADM_EXIT", "title": "Cerrar interno"},
]
ADMIN_MENU_ROWS = [
    {"id": "ORI_ADM_PREINSCRITOS", "title": "Preinscritos", "description": "Marcas pendientes por confirmar stand."},
    {"id": "ORI_ADM_CONFIRMADOS", "title": "Confirmados", "description": "Expositores con stand confirmado."},
    {"id": "ORI_ADM_PDF_EXCEL", "title": "PDF Excel", "description": "Descargar reporte de la hoja."},
    {"id": "ORI_ADM_CONTACTS", "title": "Quiénes han escrito", "description": "Lista solo de números de WhatsApp."},
    {"id": "ORI_ADM_EXIT", "title": "Cerrar interno", "description": "Salir del acceso interno."},
]
ADMIN_RECORD_PRE_BUTTONS = [
    {"id": "ORI_ADM_ASSIGN", "title": "Asignar stand"},
    {"id": "ORI_ADM_PREINSCRITOS", "title": "Preinscritos"},
    {"id": "ORI_ADM_MENU", "title": "Menú principal"},
]
ADMIN_RECORD_CONF_BUTTONS = [
    {"id": "ORI_ADM_ASSIGN", "title": "Cambiar stand"},
    {"id": "ORI_ADM_RELEASE", "title": "Liberar stand"},
    {"id": "ORI_ADM_MENU", "title": "Menú principal"},
]
ADMIN_AFTER_ACTION_BUTTONS = [
    {"id": "ORI_ADM_PREINSCRITOS", "title": "Preinscritos"},
    {"id": "ORI_ADM_CONFIRMADOS", "title": "Confirmados"},
    {"id": "ORI_ADM_MENU", "title": "Menú principal"},
]
ADMIN_CONFIRM_ACTION_BUTTONS = [
    {"id": "ORI_ADM_APPLY", "title": "Sí, confirmar"},
    {"id": "ORI_ADM_CANCEL", "title": "Cancelar"},
    {"id": "ORI_ADM_MENU", "title": "Menú principal"},
]


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
            self.send_json({"ok": True, "service": "Ori WhatsApp Bot", "version": CODE_VERSION})
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

        if parsed_url.path.startswith("/primera_feria/"):
            filename = Path(urllib.parse.unquote(parsed_url.path)).name
            file_path = FIRST_FAIRS_DIR / filename
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
        if not is_message_for_configured_phone_number(message):
            print(
                "Mensaje ignorado porque llegó a otro número de WhatsApp. "
                f"Recibido en {message.get('display_phone_number') or 'sin número visible'} "
                f"({message.get('phone_number_id') or 'sin phone_number_id'}). "
                f"Configurado: {PHONE_NUMBER_ID or 'sin PHONE_NUMBER_ID'}.",
                flush=True,
            )
            continue

        log_incoming_message(message)

        if is_guided_button_message(message):
            if handle_guided_button_message(message):
                continue

        if should_send_initial_welcome_buttons(message):
            mark_welcome_buttons_sent(message["from"], message["text"])
            send_initial_welcome(message["from"])
            continue

        if should_block_free_text(message):
            send_guided_menu_for_free_text(message)
            continue

        if message.get("type") == "audio":
            transcription = transcribe_incoming_audio(message)
            if not transcription:
                send_whatsapp_text(
                    message["from"],
                    "Recibi tu audio, pero no pude escucharlo bien en este momento. "
                    "¿Me lo puedes escribir en texto para ayudarte mejor?",
                )
                continue
            message["text"] = transcription
            message["media"] = None
            print(f"Audio transcrito de {message['from']}: {transcription}", flush=True)

        if is_admin_session_active(message["from"]) and is_admin_pdf_request(message.get("text", "")):
            send_admin_sheet_pdf(message["from"])
            send_admin_menu(message["from"], "Puedes elegir otra opcion:")
            continue

        reply = get_ori_reply(message["text"], user_id=message["from"], incoming_media=message.get("media"))
        print(f"Mensaje de {message['from']}: {message['text'] or message.get('type')}", flush=True)
        print(f"Respuesta de Ori: {reply}", flush=True)
        send_whatsapp_text(message["from"], reply)
        if is_admin_entry_message(message.get("text", "")):
            send_admin_menu(message["from"])
            continue
        if is_admin_exit_message(message.get("text", "")):
            if is_admin_session_active(message["from"]):
                send_admin_menu(message["from"], "Puedes elegir otra opción:")
            continue
        if is_admin_session_active(message["from"]):
            if "Para aplicar el cambio" in reply:
                send_whatsapp_buttons(message["from"], "Confirma esta acción:", ADMIN_CONFIRM_ACTION_BUTTONS)
            else:
                send_admin_menu(message["from"], "Puedes elegir otra opción:")
            continue
        send_preinscription_category_list_if_needed(message["from"])
        send_preinscription_confirmation_buttons_if_needed(message["from"])
        if should_send_plan_image(message["text"], reply):
            send_whatsapp_image(
                message["from"],
                PLANO_STANDS_URL,
                "Plano de stands Feria Origen Colombia 2027.",
            )
        if should_send_previous_fair_images(message["text"]):
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
            metadata = value.get("metadata", {}) if isinstance(value.get("metadata"), dict) else {}
            inbound_phone_number_id = str(metadata.get("phone_number_id", "")).strip()
            inbound_display_phone_number = str(metadata.get("display_phone_number", "")).strip()
            for message in value.get("messages", []):
                message_type = message.get("type")
                if message_type not in {"text", "image", "document", "audio", "interactive"}:
                    continue
                text = message.get("text", {}).get("body", "")
                media = None
                button_id = ""
                if message_type in {"image", "document", "audio"}:
                    media_payload = message.get(message_type, {})
                    text = media_payload.get("caption", "")
                    media = {
                        "type": message_type,
                        "id": media_payload.get("id", ""),
                        "mime_type": media_payload.get("mime_type", ""),
                        "filename": media_payload.get("filename", ""),
                        "sha256": media_payload.get("sha256", ""),
                    }
                elif message_type == "interactive":
                    interactive_payload = message.get("interactive", {})
                    text = interactive_message_text(interactive_payload)
                    button_id = interactive_button_id(interactive_payload)
                output.append(
                    {
                        "from": message.get("from", ""),
                        "text": text,
                        "type": message_type,
                        "media": media,
                        "button_id": button_id,
                        "phone_number_id": inbound_phone_number_id,
                        "display_phone_number": inbound_display_phone_number,
                    }
                )
    return output


def is_message_for_configured_phone_number(message):
    configured = str(PHONE_NUMBER_ID or "").strip()
    received = str(message.get("phone_number_id") or "").strip()
    if not configured:
        print("Advertencia: PHONE_NUMBER_ID no está configurado; no se puede filtrar por número receptor.", flush=True)
        return True
    if not received:
        return False
    return configured == received


def interactive_button_id(interactive):
    interactive_type = (interactive or {}).get("type", "")
    if interactive_type == "button_reply":
        reply = interactive.get("button_reply") or {}
        return str(reply.get("id", "")).strip()
    if interactive_type == "list_reply":
        reply = interactive.get("list_reply") or {}
        return str(reply.get("id", "")).strip()
    return ""


def start_history_log_worker():
    global HISTORY_LOG_WORKER_STARTED
    if not HISTORY_LOG_ASYNC:
        return
    with HISTORY_LOG_WORKER_LOCK:
        if HISTORY_LOG_WORKER_STARTED:
            return
        worker = threading.Thread(target=history_log_worker, name="ori-history-log", daemon=True)
        worker.start()
        HISTORY_LOG_WORKER_STARTED = True


def history_log_worker():
    while True:
        event = HISTORY_LOG_QUEUE.get()
        try:
            result = log_conversation_event(event)
            if result.get("queued"):
                phone = (event or {}).get("telefono_chat") or (event or {}).get("phone") or ""
                print(f"Historial en cola externa para {phone}: {result.get('error')}", flush=True)
        except Exception as error:
            print(f"No se pudo guardar historial en segundo plano: {error}", flush=True)
        finally:
            HISTORY_LOG_QUEUE.task_done()


def enqueue_conversation_log(event):
    if not HISTORY_LOG_ASYNC:
        return log_conversation_event(event)
    start_history_log_worker()
    try:
        HISTORY_LOG_QUEUE.put_nowait(event)
        return {"ok": True, "queued": True, "async": True}
    except queue.Full:
        print("Cola local de historial llena; guardando este evento de forma directa.", flush=True)
        return log_conversation_event(event)


def flush_history_log_queue(timeout_seconds=2):
    deadline = time.time() + timeout_seconds
    while not HISTORY_LOG_QUEUE.empty() and time.time() < deadline:
        time.sleep(0.05)


atexit.register(flush_history_log_queue)


def log_incoming_message(message):
    body = message.get("text") or message.get("type") or ""
    event = build_conversation_event(
        message.get("from", ""),
        "entrada",
        message.get("type", "text"),
        body,
        button_id=message.get("button_id", ""),
        media=message.get("media"),
        phone_number_id=message.get("phone_number_id", ""),
        display_phone_number=message.get("display_phone_number", ""),
    )
    result = enqueue_conversation_log(event)
    if result.get("queued") and not result.get("async"):
        print(f"Historial de entrada en cola para {message.get('from', '')}: {result.get('error')}", flush=True)


def log_outgoing_message(to, message_type, body, extra=None):
    event = build_conversation_event(to, "salida", message_type, body, extra=extra)
    result = enqueue_conversation_log(event)
    if result.get("queued") and not result.get("async"):
        print(f"Historial de salida en cola para {to}: {result.get('error')}", flush=True)


def build_conversation_event(
    phone,
    direction,
    message_type,
    body,
    button_id="",
    media=None,
    phone_number_id="",
    display_phone_number="",
    extra=None,
):
    memory = get_memory(phone) if phone else {}
    return {
        "phone": normalize_phone(phone),
        "direction": direction,
        "message_type": message_type,
        "body": shorten_log_text(body),
        "button_id": button_id,
        "media_type": (media or {}).get("type", "") if isinstance(media, dict) else "",
        "media_id": (media or {}).get("id", "") if isinstance(media, dict) else "",
        "phone_number_id": phone_number_id or PHONE_NUMBER_ID,
        "display_phone_number": display_phone_number,
        "role": memory.get("role", ""),
        "brand": memory.get("brand", ""),
        "category": memory.get("category", ""),
        "product": memory.get("product", ""),
        "city": memory.get("city", ""),
        "lead_stage": memory.get("lead_stage", ""),
        "selected_stand": memory.get("selected_stand", ""),
        "confirmed_stand": memory.get("confirmed_stand", ""),
        "form_submitted": bool(memory.get("form_submitted")),
        "internal": bool(is_admin_session_active(phone)),
        "extra": json.dumps(extra or {}, ensure_ascii=False)[:1000],
    }


def normalize_phone(value):
    return "".join(character for character in str(value or "") if character.isdigit())


def shorten_log_text(value, limit=1800):
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def interactive_message_text(interactive):
    interactive_type = (interactive or {}).get("type", "")
    if interactive_type == "button_reply":
        reply = interactive.get("button_reply") or {}
        return button_reply_text(reply.get("id", ""), reply.get("title", ""))
    if interactive_type == "list_reply":
        reply = interactive.get("list_reply") or {}
        return reply.get("title", "") or reply.get("description", "") or reply.get("id", "")
    return ""


def button_reply_text(button_id, title):
    button_map = {
        "ORI_EXPOSITOR": "Quiero exponer",
        "ORI_VISITANTE": "Quiero visitar",
        "ORI_EXP_PRECIOS": "Precios",
        "ORI_EXP_TRAYECTORIA": "Trayectoria",
        "ORI_EXP_PLANO": "Plano de venta",
        "ORI_EXP_PREINSCRIPCION": "Preinscripción",
        "ORI_EXP_IMAGENES": "Imágenes",
        "ORI_ADVISOR": "Hablar con un asesor",
        "ORI_PRE_CAT_ARTE": "Arte",
        "ORI_PRE_CAT_ARTESANIA": "Artesanía típica",
        "ORI_PRE_CAT_JOYERIA": "Joyería",
        "ORI_PRE_CAT_CALZADO": "Calzado y vestuario",
        "ORI_PRE_CAT_DECORACION": "Decoración",
        "ORI_PRE_CAT_ANTICUARIOS": "Anticuarios",
        "ORI_PRE_CAT_SALUD": "Salud y belleza",
        "ORI_PRE_CAT_GASTRONOMIA": "Gastronomía",
        "ORI_PRE_CONFIRM": "Sí, confirmar",
        "ORI_PRE_EDIT": "Cambiar un dato",
        "ORI_PRE_CANCEL": "Cancelar",
        "ORI_VIS_INFO": "Información de la feria",
        "ORI_VIS_LLEGAR": "Cómo llegar",
        "ORI_VIS_PRODUCTOS": "Productos",
        "ORI_VIS_PROMOCIONES": "Promociones",
        "ORI_VIS_IMAGENES": "Imágenes de la feria",
        "ORI_VIS_TRAYECTORIA": "Trayectoria",
        "ORI_VIS_CERCA": "Lugares cerca",
        "ORI_VIS_CAT_ARTE": "Arte",
        "ORI_VIS_CAT_ARTESANIA": "Artesanía",
        "ORI_VIS_CAT_JOYERIA": "Joyería",
        "ORI_VIS_CAT_CALZADO": "Calzado y vestuario",
        "ORI_VIS_CAT_DECORACION": "Decoración",
        "ORI_VIS_CAT_ANTICUARIOS": "Anticuarios",
        "ORI_VIS_CAT_SALUD": "Salud y belleza",
        "ORI_VIS_CAT_GASTRONOMIA": "Gastronomía",
        "ORI_VIS_CAT_OTRO": "Otro",
        "ORI_MENU": "Volver al menú",
        "ORI_ADM_MENU": "Menú interno",
        "ORI_ADM_PREINSCRITOS": "Preinscritos",
        "ORI_ADM_CONFIRMADOS": "Confirmados",
        "ORI_ADM_CONTACTS": "Quiénes han escrito",
        "ORI_ADM_ASSIGN": "Asignar stand",
        "ORI_ADM_RELEASE": "Liberar stand",
        "ORI_ADM_EXIT": "Cerrar interno",
        "ORI_ADM_APPLY": "Confirmar",
        "ORI_ADM_CANCEL": "Cancelar",
    }
    return button_map.get(str(button_id or "").strip(), str(title or "").strip())


def is_guided_button_message(message):
    return message.get("type") == "interactive" and str(message.get("button_id") or "").startswith("ORI_")


def handle_guided_button_message(message):
    button_id = str(message.get("button_id") or "").strip()
    user_id = message["from"]

    if button_id.startswith("ORI_ADM_"):
        return handle_admin_guided_button_message(user_id, button_id)

    if button_id == "ORI_MENU":
        send_whatsapp_buttons(user_id, MAIN_MENU_TEXT, MAIN_MENU_BUTTONS)
        remember_menu_turn(user_id, "Menú", MAIN_MENU_TEXT)
        return True

    if button_id == "ORI_EXPOSITOR":
        memory = get_memory(user_id)
        memory["role"] = "expositor"
        memory["last_intent"] = "exhibitor_menu"
        memory["guided_mode"] = "expositor"
        save_persistent_state()
        send_exhibitor_menu(user_id, EXHIBITOR_MENU_TEXT)
        remember_menu_turn(user_id, "Quiero exponer", EXHIBITOR_MENU_TEXT)
        return True

    if button_id == "ORI_VISITANTE":
        memory = get_memory(user_id)
        memory["role"] = "visitante"
        memory["last_intent"] = "visitor_menu"
        memory["guided_mode"] = "visitante"
        save_persistent_state()
        send_whatsapp_list(
            user_id,
            VISITOR_MENU_TEXT,
            "Opciones visitante",
            "Elegir opción",
            VISITOR_MENU_ROWS,
        )
        remember_menu_turn(user_id, "Quiero visitar", VISITOR_MENU_TEXT)
        return True

    if button_id == "ORI_ADVISOR":
        reply = (
            "Claro, puedes hablar con un asesor aquí:\n"
            "https://wa.me/573160282537"
        )
        send_whatsapp_text(user_id, reply)
        send_whatsapp_buttons(user_id, "También puedes volver al menú:", MAIN_MENU_BUTTONS)
        remember_menu_turn(user_id, "Hablar con un asesor", reply)
        return True

    if button_id in EXHIBITOR_CATEGORY_BY_BUTTON:
        memory = get_memory(user_id)
        reply = select_preinscription_category(memory, EXHIBITOR_CATEGORY_BY_BUTTON[button_id])
        save_persistent_state()
        send_whatsapp_text(user_id, reply)
        send_preinscription_confirmation_buttons_if_needed(user_id)
        return True

    if button_id in {"ORI_PRE_CONFIRM", "ORI_PRE_EDIT", "ORI_PRE_CANCEL"}:
        text_by_button = {
            "ORI_PRE_CONFIRM": "si confirmo",
            "ORI_PRE_EDIT": "cambiar un dato",
            "ORI_PRE_CANCEL": "cancelar",
        }
        reply = get_ori_reply(text_by_button[button_id], user_id=user_id)
        send_whatsapp_text(user_id, reply)
        send_preinscription_category_list_if_needed(user_id)
        send_preinscription_confirmation_buttons_if_needed(user_id)
        if not is_questionnaire_active(user_id):
            send_whatsapp_buttons(user_id, "Puedes volver al menú cuando quieras:", [{"id": "ORI_MENU", "title": "Menú principal"}])
        return True

    if button_id == "ORI_VIS_INFO":
        reply = get_ori_reply("información de la feria", user_id=user_id)
        send_whatsapp_text(user_id, reply)
        send_whatsapp_list(
            user_id,
            "¿Qué te gustaría revisar ahora?",
            "Opciones visitante",
            "Elegir opción",
            VISITOR_INFO_LIST_ROWS,
        )
        remember_menu_turn(user_id, "Info feria", reply)
        return True

    if button_id == "ORI_VIS_PRODUCTOS":
        reply = (
            "Pronto encontrarás Productos Origen, una revista donde podrás ver los productos destacados "
            "de cada categoría de la feria."
        )
        send_whatsapp_text(user_id, reply)
        send_whatsapp_list(
            user_id,
            "¿Qué te gustaría revisar ahora?",
            "Opciones visitante",
            "Elegir opción",
            VISITOR_MENU_ROWS,
        )
        remember_menu_turn(user_id, "Productos", reply)
        return True

    if button_id in VISITOR_CATEGORY_BY_BUTTON:
        category = VISITOR_CATEGORY_BY_BUTTON[button_id]
        reply = visitor_category_participants_reply(category)
        send_whatsapp_text(user_id, reply)
        send_whatsapp_list(
            user_id,
            "Puedes revisar otra categoría o volver al menú.",
            "Categorías",
            "Ver categorías",
            VISITOR_PRODUCT_CATEGORY_ROWS,
        )
        remember_menu_turn(user_id, button_reply_text(button_id, ""), reply)
        return True

    if button_id == "ORI_EXP_STANDS_DISPONIBLES":
        reply = available_stands_text()
        send_whatsapp_text(user_id, reply)
        send_whatsapp_image(
            user_id,
            PLANO_STANDS_URL,
            "Plano de venta Feria Origen Colombia.",
        )
        time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
        second_reply = (
            "Los valores de participación van desde $3.300.000 COP hasta $6.000.000 COP, "
            "según la zona, ubicación y tipo de stand.\n\n"
            "Cuando tengas una opción en mente, puedes iniciar la preinscripción e indicar 1 o 2 stands de interés. "
            "La disponibilidad queda sujeta a confirmación del equipo organizador.\n\n"
            "¿Qué quieres hacer ahora?"
        )
        send_whatsapp_list(
            user_id,
            second_reply,
            "Opciones expositor",
            "Elegir opción",
            EXHIBITOR_AFTER_PLAN_ROWS,
        )
        remember_menu_turn(user_id, "Stands disponibles", reply + "\n\n" + second_reply)
        return True

    if button_id == "ORI_VIS_PROMOCIONES":
        reply = (
            "Por ahora no hay promociones oficiales anunciadas para visitantes.\n\n"
            "Lo que sí puedo confirmarte es que la entrada a la feria es 100% gratuita. "
            "Si el equipo anuncia promociones, descuentos o novedades especiales, las podremos mostrar aquí."
        )
        send_whatsapp_text(user_id, reply)
        send_whatsapp_list(
            user_id,
            "¿Quieres revisar otra cosa?",
            "Opciones visitante",
            "Elegir opción",
            VISITOR_INFO_LIST_ROWS,
        )
        remember_menu_turn(user_id, "Promociones", reply)
        return True

    if button_id == "ORI_EXP_PREINSCRIPCION":
        memory = get_memory(user_id)
        reply = start_preinscription_flow(memory)
        remember_turn(memory, "Preinscripción", reply)
        save_persistent_state()
        send_whatsapp_text(user_id, reply)
        send_preinscription_category_list_if_needed(user_id)
        if not is_questionnaire_active(user_id):
            send_whatsapp_list(
                user_id,
                "Puedes elegir otra opción:",
                "Opciones expositor",
                "Elegir opción",
                EXHIBITOR_AFTER_PREINSCRIPTION_BUTTONS,
            )
        return True

    if button_id == "ORI_EXP_TRAYECTORIA":
        send_whatsapp_text(user_id, EXHIBITOR_TRAJECTORY_TEXT)
        send_first_fair_images(user_id)
        time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
        send_whatsapp_list(
            user_id,
            "¿Qué te gustaría revisar ahora?",
            "Opciones expositor",
            "Elegir opción",
            EXHIBITOR_AFTER_TRAJECTORY_ROWS,
        )
        remember_menu_turn(user_id, "Trayectoria", EXHIBITOR_TRAJECTORY_TEXT)
        return True

    if button_id == "ORI_VIS_TRAYECTORIA":
        send_whatsapp_text(user_id, EXHIBITOR_TRAJECTORY_TEXT)
        send_first_fair_images(user_id)
        time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
        send_whatsapp_list(
            user_id,
            "¿Qué te gustaría revisar ahora?",
            "Opciones visitante",
            "Elegir opción",
            VISITOR_AFTER_TRAJECTORY_ROWS,
        )
        remember_menu_turn(user_id, "Trayectoria", EXHIBITOR_TRAJECTORY_TEXT)
        return True

    if button_id == "ORI_EXP_PLANO":
        first_reply = "Claro, en unos segundos te comparto el plano de venta de Feria Origen Colombia."
        send_whatsapp_text(user_id, first_reply)
        send_whatsapp_image(
            user_id,
            PLANO_STANDS_URL,
            "Plano de venta Feria Origen Colombia.",
        )
        time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
        second_reply = (
            "Después de revisar el plano, elige 1 o 2 stands de interés y tenlos presentes "
            "para indicarlos durante el proceso de preinscripción.\n\n"
            "¿Qué quieres hacer ahora?"
        )
        send_whatsapp_list(
            user_id,
            second_reply,
            "Opciones expositor",
            "Elegir opción",
            EXHIBITOR_AFTER_PLAN_ROWS,
        )
        remember_menu_turn(user_id, "Plano de venta", first_reply + "\n\n" + second_reply)
        return True

    if button_id == "ORI_EXP_IMAGENES":
        first_reply = (
            "¡Claro! Te comparto algunas imágenes de Feria Origen Colombia 2026 "
            "para que puedas conocer mejor el ambiente, los espacios y la experiencia de la feria."
        )
        send_whatsapp_text(user_id, first_reply)
        send_fair_gallery_images(user_id)
        time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
        second_reply = (
            "Estas imágenes son de la edición 2026 y te dan una idea del tipo de experiencia "
            "que se vive en Feria Origen Colombia.\n\n"
            "¿Qué te gustaría hacer ahora?"
        )
        send_whatsapp_list(
            user_id,
            second_reply,
            "Opciones expositor",
            "Elegir opción",
            EXHIBITOR_AFTER_IMAGES_BUTTONS,
        )
        remember_menu_turn(user_id, "Imágenes", first_reply + "\n\n" + second_reply)
        return True

    if button_id == "ORI_VIS_IMAGENES":
        first_reply = (
            "¡Claro! Te comparto algunas imágenes para que puedas hacerte una idea del ambiente de la feria.\n\n"
            "Vas a ver espacios pensados para recorrer, descubrir marcas colombianas y vivir una experiencia "
            "cercana con el talento local."
        )
        send_whatsapp_text(user_id, first_reply)
        media_sent = send_fair_gallery_images(user_id)
        if media_sent:
            time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
        send_whatsapp_list(
            user_id,
            "Puedes elegir otra opción:",
            "Opciones visitante",
            "Elegir opción",
            VISITOR_AFTER_IMAGES_BUTTONS,
        )
        remember_menu_turn(user_id, "Imágenes de la feria", first_reply)
        return True

    guided_actions = {
        "ORI_EXP_PRECIOS": ("precios de stands", EXHIBITOR_AFTER_REPLY_BUTTONS),
        "ORI_VIS_LLEGAR": ("como llegar", VISITOR_AFTER_ARRIVAL_BUTTONS),
        "ORI_VIS_CERCA": ("lugares cercanos a la feria", VISITOR_AFTER_NEARBY_BUTTONS),
    }
    if button_id not in guided_actions:
        return False

    guided_text, next_buttons = guided_actions[button_id]
    reply = get_ori_reply(guided_text, user_id=user_id)
    send_whatsapp_text(user_id, reply)
    media_sent = send_context_media_if_needed(user_id, guided_text, reply)
    if media_sent:
        time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
    if not is_questionnaire_active(user_id):
        if next_buttons is EXHIBITOR_AFTER_REPLY_BUTTONS:
            send_whatsapp_list(
                user_id,
                "Puedes elegir otra opción:",
                "Opciones expositor",
                "Elegir opción",
                next_buttons,
            )
        else:
            send_whatsapp_list(
                user_id,
                "Puedes elegir otra opción:",
                "Opciones visitante",
                "Elegir opción",
                next_buttons,
            )
    return True


def send_admin_menu(user_id, body=None):
    send_whatsapp_list(
        user_id,
        body or admin_guided_menu_text(),
        "Menú interno",
        "Elegir opción",
        ADMIN_MENU_ROWS,
    )


def handle_admin_guided_button_message(user_id, button_id):
    if not is_admin_session_active(user_id):
        send_whatsapp_text(user_id, "Puedo ayudarte con información de la feria, ubicación, stands, productos y participación.")
        return True

    if button_id == "ORI_ADM_MENU":
        send_admin_menu(user_id)
        remember_menu_turn(user_id, "Menú interno", admin_guided_menu_text())
        return True

    if button_id == "ORI_ADM_EXIT":
        reply = get_ori_reply("Out_adm1n", user_id=user_id)
        send_whatsapp_text(user_id, reply)
        return True

    if button_id == "ORI_ADM_APPLY":
        reply = get_ori_reply("si confirmo", user_id=user_id)
        send_whatsapp_text(user_id, reply)
        if is_admin_session_active(user_id):
            send_whatsapp_buttons(user_id, "Puedes seguir revisando:", ADMIN_AFTER_ACTION_BUTTONS)
        return True

    if button_id == "ORI_ADM_CANCEL":
        reply = get_ori_reply("cancelar", user_id=user_id)
        send_whatsapp_text(user_id, reply)
        if is_admin_session_active(user_id):
            send_whatsapp_buttons(user_id, "Puedes seguir revisando:", ADMIN_AFTER_ACTION_BUTTONS)
        return True

    if button_id == "ORI_ADM_PREINSCRITOS":
        body, rows = admin_guided_preinscribed_rows(user_id)
        if rows:
            send_whatsapp_list(user_id, body, "Preinscritos", "Ver lista", rows)
        else:
            send_whatsapp_text(user_id, body)
            send_admin_menu(user_id, "Puedes elegir otra opcion:")
        remember_menu_turn(user_id, "Preinscritos", body)
        return True

    if button_id == "ORI_ADM_CONFIRMADOS":
        body, rows = admin_guided_confirmed_rows(user_id)
        if rows:
            send_whatsapp_text(user_id, admin_confirmed_records_text())
            send_whatsapp_list(user_id, body, "Confirmados", "Ver lista", rows)
        else:
            send_whatsapp_text(user_id, body)
            send_admin_menu(user_id, "Puedes elegir otra opcion:")
        remember_menu_turn(user_id, "Confirmados", body)
        return True

    if button_id == "ORI_ADM_CONTACTS":
        reply = admin_chat_phone_list_reply("all", admin_key=user_id)
        send_whatsapp_text(user_id, reply)
        send_admin_menu(user_id, "Puedes elegir otra opcion:")
        remember_menu_turn(user_id, "Quienes han escrito", reply)
        return True

    if button_id == "ORI_ADM_PDF_EXCEL":
        send_admin_sheet_pdf(user_id)
        remember_menu_turn(user_id, "PDF Excel", "Reporte PDF enviado.")
        send_admin_menu(user_id, "Puedes elegir otra opcion:")
        return True

    if button_id.startswith("ORI_ADM_PRE_") or button_id.startswith("ORI_ADM_CON_"):
        reply, kind = admin_guided_record_detail(user_id, button_id)
        send_whatsapp_text(user_id, reply)
        if kind == "preinscrito":
            send_whatsapp_buttons(user_id, "¿Qué quieres hacer con esta marca?", ADMIN_RECORD_PRE_BUTTONS)
        elif kind == "confirmado":
            send_whatsapp_buttons(user_id, "¿Qué quieres hacer con este expositor?", ADMIN_RECORD_CONF_BUTTONS)
        else:
            send_admin_menu(user_id, "Volvemos al menu interno?")
        remember_menu_turn(user_id, button_reply_text(button_id, ""), reply)
        return True

    if button_id == "ORI_ADM_ASSIGN":
        reply = admin_prepare_guided_assignment(user_id)
        send_whatsapp_text(user_id, reply)
        send_whatsapp_buttons(user_id, "También puedes volver:", ADMIN_AFTER_ACTION_BUTTONS)
        remember_menu_turn(user_id, "Asignar stand", reply)
        return True

    if button_id == "ORI_ADM_RELEASE":
        reply = admin_prepare_guided_release(user_id)
        send_whatsapp_text(user_id, reply)
        if "Para aplicar el cambio" in reply:
            send_whatsapp_buttons(user_id, "Confirma esta acción:", ADMIN_CONFIRM_ACTION_BUTTONS)
        else:
            send_whatsapp_buttons(user_id, "También puedes volver:", ADMIN_AFTER_ACTION_BUTTONS)
        remember_menu_turn(user_id, "Liberar stand", reply)
        return True

    return False


def remember_menu_turn(user_id, user_message, reply):
    memory = get_memory(user_id)
    remember_turn(memory, user_message, reply)
    save_persistent_state()


def should_send_initial_welcome_buttons(message):
    if message.get("type") != "text":
        return False
    if is_admin_entry_message(message.get("text", "")):
        return False
    if is_admin_session_active(message.get("from")):
        return False
    if is_questionnaire_active(message.get("from")):
        return False
    memory = get_memory(message.get("from"))
    if memory.get("welcome_buttons_sent"):
        return False
    return not memory.get("history") or is_welcome_greeting_message(message.get("text", ""))


def is_welcome_greeting_message(text):
    normalized = normalize_for_match(text)
    return normalized in {"hola", "hola ori", "buenas", "buenos dias", "buenas tardes", "buenas noches", "inicio"}


def mark_welcome_buttons_sent(user_id, user_message):
    memory = get_memory(user_id)
    memory["welcome_buttons_sent"] = True
    memory["guided_mode"] = "main"
    remember_turn(memory, user_message or "[inicio]", WELCOME_BUTTON_TEXT)
    save_persistent_state()


def send_initial_welcome(user_id):
    send_whatsapp_image(user_id, ORI_WELCOME_IMAGE_URL, "Ori Colombia.")
    time.sleep(MEDIA_DELIVERY_DELAY_SECONDS)
    send_whatsapp_buttons(user_id, WELCOME_BUTTON_TEXT, WELCOME_BUTTONS)


def should_block_free_text(message):
    if message.get("type") not in {"text", "audio"}:
        return False
    user_id = message.get("from")
    if is_admin_entry_message(message.get("text", "")) or is_admin_session_active(user_id):
        return False
    return not is_questionnaire_active(user_id)


def send_guided_menu_for_free_text(message):
    user_id = message["from"]
    memory = get_memory(user_id)
    mode = memory.get("guided_mode") or memory.get("role") or "main"
    text = (
        "¡Hola de nuevo! Me alegra leerte.\n\n"
        "Para ayudarte mejor, elige por dónde quieres seguir y continuamos desde ahí.\n\n"
        "Si quieres participar como expositor, toca Expositor. Si vienes a visitar la feria, toca Visitante.\n\n"
        "Cuando iniciemos la preinscripción, podrás escribirme tus datos tranquilamente."
    )
    if mode == "expositor":
        send_exhibitor_menu(user_id, text)
    elif mode == "visitante":
        send_whatsapp_list(user_id, text, "Opciones visitante", "Elegir opción", VISITOR_MENU_ROWS)
    else:
        send_whatsapp_buttons(user_id, text, MAIN_MENU_BUTTONS)
    remember_menu_turn(user_id, message.get("text") or "[mensaje libre]", text)


def send_exhibitor_menu(user_id, body):
    send_whatsapp_list(
        user_id,
        body,
        "Opciones expositor",
        "Elegir opción",
        EXHIBITOR_MENU_ROWS,
    )


def is_questionnaire_active(user_id):
    memory = get_memory(user_id)
    pre = memory.get("preinscription") or {}
    if pre.get("active"):
        return True
    return memory.get("pending_field") in {"post_submission_correction", "preinscription"}


def send_preinscription_category_list_if_needed(user_id):
    memory = get_memory(user_id)
    pre = memory.get("preinscription") or {}
    if not pre.get("active") or pre.get("step") != "category":
        return False
    send_whatsapp_list(
        user_id,
        "Elige la categoría de tu marca:",
        "Categoría",
        "Ver categorías",
        EXHIBITOR_CATEGORY_ROWS,
    )
    return True


def send_preinscription_confirmation_buttons_if_needed(user_id):
    memory = get_memory(user_id)
    pre = memory.get("preinscription") or {}
    if not pre.get("active") or pre.get("step") != "confirmation":
        return False
    send_whatsapp_buttons(
        user_id,
        "Elige una opción:",
        PREINSCRIPTION_CONFIRM_BUTTONS,
    )
    return True


def send_fair_gallery_images(user_id):
    sent = False
    for image_url, caption in fair_gallery_image_urls()[:MAX_PREVIOUS_FAIR_IMAGES]:
        send_whatsapp_image(user_id, image_url, caption)
        sent = True
    return sent


def send_first_fair_images(user_id):
    sent = False
    for image_url, caption in first_fair_image_urls():
        send_whatsapp_image(user_id, image_url, caption)
        sent = True
    return sent


def send_context_media_if_needed(user_id, message_text, reply):
    media_sent = False
    if should_send_plan_image(message_text, reply):
        send_whatsapp_image(
            user_id,
            PLANO_STANDS_URL,
            "Plano de stands Feria Origen Colombia 2027.",
        )
        media_sent = True
    if should_send_previous_fair_images(message_text):
        media_sent = send_fair_gallery_images(user_id) or media_sent
    return media_sent


def visitor_category_participants_reply(category):
    title = (category or "otras categorías").replace("Artesanía típica", "Artesanía")
    description = VISITOR_CATEGORY_DESCRIPTIONS.get(category, VISITOR_CATEGORY_DESCRIPTIONS[""])
    return (
        f"{description}\n\n"
        f"En {title} podrás encontrar propuestas pensadas para recorrer con calma, descubrir detalles "
        "y conectar con marcas que trabajan con identidad colombiana.\n\n"
        "Puedes revisar otra categoría o volver al menú cuando quieras."
    )


def transcribe_incoming_audio(message):
    media = message.get("media") or {}
    if not WHATSAPP_TOKEN:
        print("No se puede transcribir audio: falta WHATSAPP_TOKEN.", flush=True)
        return ""

    try:
        content, mime_type, filename = download_whatsapp_media(media, WHATSAPP_TOKEN, GRAPH_API_VERSION)
        return transcribe_audio_with_groq(content, filename, mime_type)
    except GroqClientError as error:
        print(f"No se pudo transcribir audio con Groq: {error}", flush=True)
    except Exception as error:
        print(f"No se pudo descargar/transcribir audio de WhatsApp: {error}", flush=True)
    return ""


def send_admin_sheet_pdf(user_id):
    records = filter_form_records(force=True)
    if not records:
        error = last_form_error()
        if error:
            send_whatsapp_text(
                user_id,
                "No pude consultar la hoja en este momento, así que no generé el PDF. "
                "Intenta nuevamente en unos segundos.",
            )
        else:
            send_whatsapp_text(user_id, "La hoja no tiene registros para generar el PDF.")
        return

    generated_at = time.strftime("%Y-%m-%d %H:%M")
    filename = f"reporte_preinscripciones_ori_{time.strftime('%Y%m%d_%H%M')}.pdf"
    pdf_content = build_preinscription_pdf(records, generated_at)
    try:
        send_whatsapp_document_bytes(
            user_id,
            filename,
            pdf_content,
            f"Reporte de preinscripciones Ori Colombia - {generated_at}",
        )
    except Exception as error:
        print(f"No se pudo enviar el PDF administrativo: {error}", flush=True)
        send_whatsapp_text(user_id, "Generé el PDF, pero no pude enviarlo por WhatsApp en este momento. Intenta nuevamente.")


def is_admin_pdf_request(text):
    normalized = normalize_for_match(text)
    return any(
        phrase in normalized
        for phrase in [
            "pdf excel",
            "excel pdf",
            "reporte pdf",
            "reporte excel",
            "descargar pdf",
            "extraer pdf",
            "genera pdf",
            "generar pdf",
            "mandame el pdf",
            "enviame el pdf",
            "pdf de la hoja",
            "pdf del excel",
            "pdf formulario",
            "pdf formularios",
            "pdf preinscritos",
            "exportar pdf",
        ]
    )


def build_preinscription_pdf(records, generated_at):
    lines = [
        "Reporte de preinscripciones - Ori Colombia",
        f"Generado: {generated_at}",
        f"Registros: {len(records)}",
        "",
    ]
    for index, record in enumerate(records, start=1):
        raw = record.get("raw") or {}
        lines.extend(
            [
                f"{index}. {record.get('legal_name') or record.get('stand_name') or 'Sin razón social'}",
                f"   Representante: {record.get('representative') or 'sin dato'}",
                f"   Nombre para el stand: {record.get('stand_name') or 'sin dato'}",
                f"   Ciudad: {record.get('city') or 'sin dato'}",
                f"   WhatsApp: {record.get('whatsapp') or 'sin dato'}",
                f"   Correo: {record.get('email') or 'sin dato'}",
                f"   Redes/web: {record.get('socials') or 'No registra'}",
                f"   Categoría: {record.get('category') or 'sin categoría'}",
                f"   Productos: {record.get('products') or 'sin dato'}",
                f"   Stands de interés: {raw.get('Stands de interes') or raw.get('Stands de interés') or record.get('comments') or 'sin dato'}",
                f"   Stand confirmado: {record.get('confirmed_stand') or 'pendiente'}",
                f"   Archivos de productos: {record.get('sample') or 'No enviados'}",
                f"   Carpeta Drive: {raw.get('Carpeta Drive') or 'sin dato'}",
                "",
            ]
        )
    return build_text_pdf(lines)


def build_text_pdf(lines):
    wrapped_lines = []
    for line in lines:
        wrapped_lines.extend(wrap_pdf_line(line, 92))

    lines_per_page = 56
    pages = [wrapped_lines[index:index + lines_per_page] for index in range(0, len(wrapped_lines), lines_per_page)]
    if not pages:
        pages = [["Sin información."]]

    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    page_ids = []
    next_object_id = 4
    for page_lines in pages:
        page_id = next_object_id
        content_id = next_object_id + 1
        next_object_id += 2
        page_ids.append(page_id)
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("ascii")
        content = build_pdf_page_content(page_lines)
        objects[content_id] = b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"\nendstream"

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id in range(1, max(objects) + 1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode("ascii"))
        output.extend(objects[object_id])
        output.extend(b"\nendobj\n")

    xref_start = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def wrap_pdf_line(line, max_length):
    text = str(line or "")
    if not text:
        return [""]
    output = []
    current = ""
    for word in text.split(" "):
        if not current:
            current = word
        elif len(current) + len(word) + 1 <= max_length:
            current += " " + word
        else:
            output.append(current)
            current = word
    output.append(current)
    return output


def build_pdf_page_content(lines):
    content = bytearray(b"BT\n/F1 10 Tf\n40 760 Td\n12 TL\n")
    for line in lines:
        content.extend(pdf_text_string(line))
        content.extend(b" Tj\nT*\n")
    content.extend(b"ET")
    return bytes(content)


def pdf_text_string(text):
    raw = str(text or "").encode("cp1252", errors="replace")
    raw = raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    raw = raw.replace(b"\r", b" ").replace(b"\n", b" ")
    return b"(" + raw + b")"


def send_whatsapp_document_bytes(to, filename, content, caption=""):
    if DRY_RUN or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(f"Envio de documento omitido para {to}: {filename}", flush=True)
        return

    media = {
        "content": content,
        "mime_type": "application/pdf",
        "filename": filename,
    }
    media_id = upload_whatsapp_media(media)
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "document",
        "document": {
            "id": media_id,
            "filename": filename,
        },
    }
    if caption:
        payload["document"]["caption"] = caption[:1024]

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
            print(f"Documento enviado a WhatsApp para {to}: {filename}", flush=True)
            log_outgoing_message(to, "document", caption or filename, extra={"filename": filename})
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API respondio {error.code} al enviar documento: {detail}") from error


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
            log_outgoing_message(to, "text", body)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API respondio {error.code}: {detail}") from error


def send_whatsapp_buttons(to, body, buttons):
    if DRY_RUN or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(f"Envio de botones omitido para {to}: {body}", flush=True)
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": str(button["id"])[:256],
                            "title": str(button["title"])[:20],
                        },
                    }
                    for button in buttons[:3]
                ]
            },
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
            print(f"Botones enviados a WhatsApp para {to}", flush=True)
            log_outgoing_message(
                to,
                "buttons",
                body,
                extra={"buttons": [{"id": button.get("id"), "title": button.get("title")} for button in buttons[:3]]},
            )
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API respondio {error.code} al enviar botones: {detail}") from error


def send_whatsapp_list(to, body, header, button_text, rows):
    if DRY_RUN or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(f"Envio de lista omitido para {to}: {body}", flush=True)
        for row in rows[:10]:
            print(f"- {row.get('title')} ({row.get('id')})", flush=True)
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": str(header or "Opciones")[:60]},
            "body": {"text": str(body or "Elige una opción:")[:1024]},
            "action": {
                "button": str(button_text or "Elegir")[:20],
                "sections": [
                    {
                        "title": str(header or "Opciones")[:24],
                        "rows": [
                            {
                                "id": str(row["id"])[:200],
                                "title": str(row["title"])[:24],
                                "description": str(row.get("description") or "")[:72],
                            }
                            for row in rows[:10]
                        ],
                    }
                ],
            },
        },
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
            print(f"Lista enviada a WhatsApp para {to}", flush=True)
            log_outgoing_message(
                to,
                "list",
                body,
                extra={
                    "header": header,
                    "button_text": button_text,
                    "rows": [{"id": row.get("id"), "title": row.get("title")} for row in rows[:10]],
                },
            )
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"WhatsApp API respondio {error.code} al enviar lista: {detail}") from error


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


def local_image_media_for_url(image_url):
    parsed = urllib.parse.urlparse(image_url or "")
    path = urllib.parse.unquote(parsed.path or "")
    filename = Path(path).name
    if path == "/plano_stands.jpg" and PLANO_STANDS_JPG_BASE64:
        return {
            "filename": "plano_stands.jpg",
            "mime_type": "image/jpeg",
            "content": base64.b64decode(PLANO_STANDS_JPG_BASE64),
        }
    if path.startswith("/bienvenida/"):
        file_path = WELCOME_IMAGES_DIR / filename
        content_type = image_content_type(file_path) or image_content_type(Path(filename))
        if file_path.exists() and file_path.is_file() and content_type:
            return {"filename": filename, "mime_type": content_type, "content": file_path.read_bytes()}
        fallback = WELCOME_IMAGES_BASE64.get(filename, "")
        if fallback and content_type:
            return {"filename": filename, "mime_type": content_type, "content": base64.b64decode(fallback)}
    if path.startswith("/ferias_anteriores/"):
        file_path = PREVIOUS_FAIRS_DIR / filename
        content_type = image_content_type(file_path)
        if file_path.exists() and file_path.is_file() and content_type:
            return {"filename": filename, "mime_type": content_type, "content": file_path.read_bytes()}
    if path.startswith("/primera_feria/"):
        file_path = FIRST_FAIRS_DIR / filename
        content_type = image_content_type(file_path)
        if file_path.exists() and file_path.is_file() and content_type:
            return {"filename": filename, "mime_type": content_type, "content": file_path.read_bytes()}
    return None


def upload_whatsapp_media(media):
    boundary = f"----OriColombia{int(time.time() * 1000)}"
    parts = []
    for name, value in [
        ("messaging_product", "whatsapp"),
        ("type", media["mime_type"]),
    ]:
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        parts.append(str(value).encode("utf-8"))
        parts.append(b"\r\n")
    parts.append(f"--{boundary}\r\n".encode("utf-8"))
    parts.append(
        (
            f'Content-Disposition: form-data; name="file"; filename="{media["filename"]}"\r\n'
            f'Content-Type: {media["mime_type"]}\r\n\r\n'
        ).encode("utf-8")
    )
    parts.append(media["content"])
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    data = b"".join(parts)
    request = urllib.request.Request(
        f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/media",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(data)),
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        parsed = json.loads(response.read().decode("utf-8", errors="replace") or "{}")
    media_id = parsed.get("id")
    if not media_id:
        raise RuntimeError(f"Meta no devolvió id de media: {parsed}")
    return media_id


def send_whatsapp_image(to, image_url, caption=""):
    if DRY_RUN or not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print(f"Envio de imagen omitido. URL del plano: {image_url}", flush=True)
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    local_media = local_image_media_for_url(image_url)
    if local_media:
        try:
            media_id = upload_whatsapp_media(local_media)
            image_payload = {"id": media_id}
        except Exception as error:
            print(f"No se pudo subir imagen a Meta, se intenta por enlace: {error}", flush=True)
            image_payload = {"link": image_url}
    else:
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
            log_outgoing_message(to, "image", caption or image_url, extra={"image_url": image_url})
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        print(f"WhatsApp API respondio {error.code} al enviar imagen: {detail}", flush=True)
    except urllib.error.URLError as error:
        print(f"No se pudo conectar para enviar imagen a WhatsApp: {error}", flush=True)


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


def first_fair_image_urls():
    caption = "Lanzamiento Origen Colombia - Noviembre 2003"
    return [
        (
            f"{PUBLIC_BASE_URL}/primera_feria/Primera_feria_01.png",
            caption,
        ),
        (
            f"{PUBLIC_BASE_URL}/primera_feria/Primera_feria_02.png",
            caption,
        ),
        (
            f"{PUBLIC_BASE_URL}/primera_feria/Primera_feria_03.JPG",
            caption,
        ),
        (
            f"{PUBLIC_BASE_URL}/primera_feria/Primera_feria_04.JPG",
            caption,
        ),
        (
            f"{PUBLIC_BASE_URL}/primera_feria/Primera_feria_05.JPG",
            caption,
        ),
    ]


def fair_gallery_image_urls():
    previous_urls = [
        (url, "Feria Origen Colombia 2026.")
        for url in previous_fair_image_urls()
    ]
    if previous_urls:
        return previous_urls
    return welcome_image_urls()


def welcome_image_urls():
    return [
        (
            f"{PUBLIC_BASE_URL}/bienvenida/patio_de_las_artes.jpg",
            "Patio de las Artes - Feria Origen Colombia 2026.",
        ),
        (
            f"{PUBLIC_BASE_URL}/bienvenida/patio_de_las_artes_pasillos.jpg",
            "Patio de las Artes, pasillos cubiertos - Feria Origen Colombia 2026.",
        ),
        (
            f"{PUBLIC_BASE_URL}/bienvenida/salon_pierre_daguet.jpg",
            "Salon Pierre Daguet - Feria Origen Colombia 2026.",
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
