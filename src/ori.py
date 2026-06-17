import re
import unicodedata

from data import BOOTHS, FAIR_INFO, STAND_PRICES
from groq_client import GroqClientError, is_groq_enabled, polish_with_groq
from openai_client import OpenAIClientError, ask_chatgpt, is_openai_enabled


STATUS_LABELS = {
    "available": "disponible",
    "reserved": "reservado",
    "unavailable": "no disponible",
}

ZONE_LABELS = {
    "patio": "Patio de las Artes",
    "salon": "Salon Pierre Daguet",
}

CONVERSATIONS = {}

INTENTS = {
    "plan": [
        "plano",
        "plano de la feria",
        "plano de stands",
        "mapa de la feria",
        "mapa de stands",
        "compartir el plano",
        "comparteme el plano",
        "ver el plano",
        "ver plano",
    ],
    "event": [
        "evento",
        "feria",
        "origen",
        "informacion",
        "info",
        "que es",
        "de que trata",
        "visit",
        "visitar",
        "trayectoria",
        "experiencia",
        "cuantas ferias",
    ],
    "date": ["fecha", "cuando", "dia", "dias", "horario", "hora", "abre", "cierra", "programacion"],
    "location": ["ubicacion", "direccion", "donde", "llegar", "mapa", "sede", "queda", "lugar"],
    "nearby": [
        "cerca",
        "cercano",
        "cercanos",
        "alrededor",
        "lugares",
        "sitios",
        "restaurantes",
        "restaurante",
        "cafes",
        "cafe cerca",
        "hoteles",
        "hotel",
        "turismo",
        "visitar cerca",
        "que hay cerca",
        "comer",
    ],
    "venue": [
        "convento",
        "san diego",
        "unibac",
        "historia de la sede",
        "patio de las artes",
        "salon pierre",
        "pierre daguet",
        "espacios",
    ],
    "exhibitor": [
        "expositor",
        "expositores",
        "participar",
        "registrar",
        "registrarme",
        "registrarse",
        "inscribir",
        "inscribirme",
        "inscribirse",
        "inscripcion",
        "formulario",
        "marca",
        "emprendimiento",
        "vender",
        "stand",
        "puesto",
    ],
    "products": [
        "producto",
        "productos",
        "servicio",
        "servicios",
        "comprar",
        "venden",
        "encuentro",
        "artesania",
        "moda",
        "gastronomia",
        "categoria",
        "categorias",
        "acepta",
    ],
    "activities": ["actividad", "actividades", "agenda", "cultural", "muestra", "networking", "experiencia"],
    "booths": ["stand", "stands", "puesto", "puestos", "disponible", "disponibles", "reservar", "reserva"],
    "prices": ["precio", "precios", "valor", "cuanto cuesta", "tarifa", "costo", "vale", "pagar"],
    "advisor": ["asesor", "humano", "persona", "contacto", "llamar", "whatsapp", "equipo"],
    "thanks": ["gracias", "listo", "perfecto", "ok", "vale", "super"],
}


def get_ori_reply(raw_message, user_id=None):
    text = str(raw_message or "").strip()
    memory = get_memory(user_id)

    base_reply = get_local_ai_reply(text, memory)
    final_reply = base_reply

    if is_groq_enabled():
        try:
            final_reply = keep_required_details(base_reply, polish_with_groq(text, base_reply, build_feria_context(), memory))
        except GroqClientError as error:
            print(f"No se pudo usar Groq, se usa cerebro local: {error}", flush=True)

    elif is_openai_enabled():
        try:
            final_reply = ask_chatgpt(text, build_feria_context())
        except OpenAIClientError as error:
            print(f"No se pudo usar ChatGPT, se usa respaldo local: {error}", flush=True)

    remember_turn(memory, text, final_reply)
    return final_reply


def get_memory(user_id):
    key = str(user_id or "default")
    if key not in CONVERSATIONS:
        CONVERSATIONS[key] = {
            "last_intent": None,
            "role": None,
            "selected_stand": None,
            "selected_stand_status": None,
            "blocked_stand": None,
            "blocked_stand_status": None,
            "pending_field": None,
            "category": None,
            "history": [],
        }
    return CONVERSATIONS[key]


def get_local_ai_reply(raw_message, memory):
    message = str(raw_message or "").strip()
    text = normalize(message)

    if not text:
        return welcome_reply(memory)

    category = detect_product_category(text)

    if asks_for_plan(text):
        memory["last_intent"] = "plan"
        memory["pending_field"] = None
        return plan_reply()

    if has_any(text, ["hola", "buenas", "buen dia", "buenos dias", "buenas tardes", "menu", "ayuda", "inicio"]):
        memory["last_intent"] = "greeting"
        return welcome_reply(memory)

    if has_any(text, ["soy visitante", "voy como visitante", "quiero visitar", "asistir", "ir a la feria"]):
        memory["role"] = "visitante"
        memory["last_intent"] = "visitor"
        memory["pending_field"] = None
        return visitor_guide_reply()

    if wants_human_help(text):
        memory["last_intent"] = "advisor"
        memory["pending_field"] = None
        return advisor_reply(memory)

    if has_any(text, ["soy expositor", "quiero exponer", "quiero vender", "quiero participar", "tengo una marca"]):
        memory["role"] = "expositor"
        if category:
            memory["category"] = category
            memory["last_intent"] = "registration_category"
            memory["pending_field"] = "registration"
            return category_followup_reply(category)
        memory["last_intent"] = "exhibitor"
        memory["pending_field"] = "category"
        return exhibitor_guide_reply()

    if memory.get("role") == "expositor" and (memory.get("pending_field") == "category" or category):
        if category:
            memory["category"] = category
            memory["pending_field"] = "registration"
            memory["last_intent"] = "registration_category"
            return category_followup_reply(category)

    if has_any(text, ["que puedo preguntar", "preguntarte", "recomiendame", "recomienda", "opciones"]):
        memory["last_intent"] = "suggestions"
        return suggestions_reply(memory)

    stand_number = extract_stand_number(text)
    if stand_number and should_treat_as_stand(text, memory):
        remember_stand_interest(memory, stand_number)
        memory["last_intent"] = "booths"
        return describe_stand(stand_number)

    if asks_for_history(text) and not has_any(text, ["sede", "convento", "san diego", "unibac", "patio", "salon"]):
        memory["last_intent"] = "history"
        return fair_history_reply()

    if asks_for_metrics(text):
        memory["last_intent"] = "metrics"
        return metrics_reply()

    intent = detect_intent(text, memory)
    memory["last_intent"] = intent

    if intent == "event":
        return event_reply()
    if intent == "plan":
        return plan_reply()
    if intent == "date":
        return date_reply()
    if intent == "nearby":
        return nearby_reply()
    if intent == "location":
        return location_reply()
    if intent == "venue":
        return venue_reply(text)
    if intent == "exhibitor":
        memory["role"] = "expositor"
        if category:
            memory["category"] = category
            memory["pending_field"] = "registration"
            memory["last_intent"] = "registration_category"
            return category_followup_reply(category)
        memory["pending_field"] = "category"
        return exhibitor_guide_reply()
    if intent == "products":
        return products_reply(text)
    if intent == "activities":
        return activities_reply()
    if intent == "booths":
        return available_stands_reply()
    if intent == "prices":
        return prices_reply(memory, text)
    if intent == "advisor":
        return advisor_reply(memory)
    if intent == "thanks":
        return "Con gusto. Soy Ori y estoy aqui para ayudarte con la feria cuando lo necesites."

    if asks_for_history(text):
        memory["last_intent"] = "history"
        return fair_history_reply()

    return smart_fallback_reply(message, memory)


def welcome_reply(memory):
    role_hint = ""
    if memory.get("role") == "expositor":
        role_hint = " Como expositor, puedo orientarte con stands, disponibilidad, medidas y pasos para participar."
    elif memory.get("role") == "visitante":
        role_hint = " Como visitante, puedo orientarte con fecha, ubicacion, productos y actividades."

    return (
        f"Hola, soy Ori, asistente virtual de {FAIR_INFO['name']}. "
        "Puedo ayudarte con evento, stands, expositores, productos, actividades y solicitudes para el equipo."
        f"{role_hint} Puedes escribirme con tus propias palabras."
    )


def event_reply():
    return (
        f"La {FAIR_INFO['name']} es un espacio para {FAIR_INFO['purpose']} "
        f"Esta pensada para visitantes que quieren descubrir {FAIR_INFO['products'].rstrip('.')} "
        "y para marcas que buscan conectar con nuevas oportunidades comerciales. "
        f"Origen Colombia cuenta con {FAIR_INFO['experience_years']}, {FAIR_INFO['total_fairs']}, "
        f"{FAIR_INFO['total_exhibitors']} y {FAIR_INFO['visitors_per_event']}."
    )


def fair_history_reply():
    return (
        f"La web oficial confirma que Origen Colombia tiene {FAIR_INFO['experience_years']} "
        f"y {FAIR_INFO['total_fairs']}. No publica en el texto visible el ano exacto de la primera feria, "
        "asi que prefiero no inventarlo. Si necesitas ese dato exacto, puedo dejar clara la solicitud para el equipo."
    )


def metrics_reply():
    return (
        f"Segun la web oficial, Origen Colombia cuenta con {FAIR_INFO['experience_years']}, "
        f"{FAIR_INFO['total_fairs']}, {FAIR_INFO['total_exhibitors']} y "
        f"{FAIR_INFO['visitors_per_event']}."
    )


def date_reply():
    return (
        f"La feria esta programada {FAIR_INFO['dates']}. "
        "La agenda detallada puede ajustarse antes del evento; por ahora no tengo horarios exactos de actividades."
    )


def location_reply():
    return (
        f"{FAIR_INFO['location']} "
        "La sede tiene dos espacios principales para exposicion: Patio de las Artes y Salon Pierre Daguet."
    )


def plan_reply():
    return (
        "Claro, con mucho gusto te comparto el plano actual de la feria. "
        "Ahi podras ubicar los stands disponibles y los que ya aparecen ocupados. "
        "Si quieres revisar un stand puntual, dime el numero."
    )


def nearby_reply():
    return (
        f"{FAIR_INFO['nearby_places']} "
        "Si quieres, dime si buscas comer, hospedarte o caminar cerca y te respondo mas puntual con la informacion cargada."
    )


def venue_reply(text):
    if has_any(text, ["patio", "patio de las artes"]):
        return FAIR_INFO["exhibition_spaces"]["patio"]

    if has_any(text, ["salon", "pierre", "daguet"]):
        return FAIR_INFO["exhibition_spaces"]["salon"]

    return (
        f"{FAIR_INFO['venue_history']} {FAIR_INFO['venue_context']} "
        f"Espacios de exposicion: {FAIR_INFO['exhibition_spaces']['patio']} "
        f"{FAIR_INFO['exhibition_spaces']['salon']}"
    )


def visitor_guide_reply():
    return (
        f"Perfecto. Como visitante vas a encontrar {FAIR_INFO['products']} "
        f"Tambien habra {FAIR_INFO['activities']} "
        f"La galeria oficial destaca: {FAIR_INFO['gallery_sections']} "
        "Puedes preguntarme por fecha, ubicacion, actividades, productos o espacios de la sede."
    )


def exhibitor_guide_reply():
    return (
        "Claro. Para participar como expositor, primero diligencia el formulario oficial: "
        f"{FAIR_INFO['registration_form_url']} "
        "Dime que categoria crees que aplica para tu marca, por ejemplo joyeria, gastronomia, moda o artesanias, y seguimos el hilo."
    )


def category_followup_reply(category):
    return (
        f"Perfecto, {category} aplica para la feria. "
        f"El siguiente paso es llenar el formulario oficial: {FAIR_INFO['registration_form_url']} "
        "Ten a mano marca, ciudad, producto, WhatsApp, correo, redes y catalogo o imagenes."
    )


def suggestions_reply(memory):
    if memory.get("role") == "expositor":
        return (
            "Puedes preguntarme cosas como: que stands estan disponibles, cuanto mide el stand 21, "
            "que categorias acepta la feria, que datos debo enviar para participar o como es la sede."
        )

    return (
        "Puedes preguntarme cosas como: donde es la feria, cuando se realiza, que productos encontrare, "
        "que actividades habra, como es el Convento de San Diego, como participar como expositor o que stands estan disponibles."
    )


def products_reply(text):
    if has_any(text, ["categoria", "categorias", "acepta"]):
        return f"Las categorias oficiales de inscripcion son: {FAIR_INFO['registration_categories']}"

    category = detect_product_category(text)
    if category:
        return (
            f"Si buscas {category}, Ori lo puede orientar dentro de las categorias de la feria. "
            f"La web oficial confirma categorias como: {FAIR_INFO['registration_categories']} "
            "Para una marca o expositor especifico, aun falta cargar el contacto oficial del equipo."
        )

    return (
        f"En la feria encontraras {FAIR_INFO['products']} "
        "Si me dices una categoria, por ejemplo moda, gastronomia o artesanias, te respondo mas puntual."
    )


def activities_reply():
    return (
        f"La feria tendra {FAIR_INFO['activities']} "
        "La programacion fina todavia debe confirmarse, asi que por ahora no tengo horas exactas cargadas."
    )


def prices_reply(memory, text=""):
    stand_number = extract_stand_number(text) or memory.get("selected_stand")
    if stand_number:
        stand = find_booth(stand_number)
        price = STAND_PRICES.get(stand_number)
        if not stand or not price:
            return (
                f"Aun no tengo precio cargado para el stand {stand_number}. "
                "Si quieres, puedo mostrarte los stands disponibles con precio cargado."
            )

        status = STATUS_LABELS[stand["status"]]
        zone = ZONE_LABELS[stand["zone"]]
        status_note = ""
        if stand["status"] == "reserved":
            status_note = " Ojo: aparece reservado, asi que no debo ofrecerlo como disponible."
        elif stand["status"] == "unavailable":
            status_note = " Ojo: aparece no disponible, asi que no debo ofrecerlo como opcion."

        return (
            f"El stand {stand_number} es {price['type']} de {price['size']} en {zone}. "
            f"Precio: {price['price']}. Estado: {status}.{status_note} "
            f"{FAIR_INFO['stand_includes']}"
        )

    if memory.get("role") == "expositor" or memory.get("last_intent") in {"booths", "exhibitor"}:
        return (
            "Ya tengo precios cargados por stand. Dime el numero que te interesa, por ejemplo "
            "'precio del stand 56', y te confirmo valor, medida, zona y disponibilidad."
        )

    return (
        "Tengo precios cargados para los stands. Dime el numero del stand que quieres revisar "
        "y te confirmo valor, medida, zona y disponibilidad."
    )


def advisor_reply(memory=None):
    memory = memory or {}
    blocked_stand = memory.get("blocked_stand")
    selected_stand = memory.get("selected_stand")

    if blocked_stand:
        blocked_status = STATUS_LABELS.get(memory.get("blocked_stand_status"), "no disponible")
        if selected_stand:
            return (
                f"{FAIR_INFO['human_help']} "
                f"Eso si: el stand {blocked_stand} aparece {blocked_status}, "
                f"asi que no debo tomarlo como disponible. Podemos seguir con el stand {selected_stand} "
                "o revisar otra opcion disponible."
            )
        return (
            f"{FAIR_INFO['human_help']} "
            f"Eso si: el stand {blocked_stand} aparece {blocked_status}, "
            "asi que no debo tomarlo como disponible. Podemos revisar otra opcion disponible."
        )

    return FAIR_INFO["human_help"]


def smart_fallback_reply(message, memory):
    if looks_like_lead(message):
        memory["last_intent"] = "lead"
        return (
            "Gracias, ya tengo una parte de tu informacion. Para que el equipo pueda revisarla mejor, envia en un solo mensaje: "
            "nombre, marca, producto, ciudad y stand de interes si ya lo tienes."
        )

    if memory.get("last_intent") == "booths":
        return (
            "Sigo contigo en el tema de stands. Puedes escribirme un numero, por ejemplo 'stand 21', "
            "o escribir 'stands disponibles' para ver las opciones cargadas."
        )

    if memory.get("role") == "expositor":
        return (
            "Creo que tu consulta va por el lado de participacion como expositor. "
            "Puedo ayudarte con stands disponibles, medidas y zonas. "
            f"Para registrarte, usa el formulario oficial: {FAIR_INFO['registration_form_url']}"
        )

    return (
        "Te entiendo. Con la informacion cargada puedo orientarte sobre evento, fecha, ubicacion, productos, actividades, expositores y stands. "
        "Preguntame como lo dirias normalmente, por ejemplo: 'donde es', 'que stands hay disponibles' o 'quiero participar con mi marca'."
    )


def describe_stand(number):
    stand = find_booth(number)
    if not stand:
        return (
            f"No encuentro el stand {number} en el plano cargado. "
            "Puedo mostrarte stands disponibles; para validar el plano actualizado falta cargar el contacto oficial del equipo."
        )

    zone = ZONE_LABELS[stand["zone"]]
    price_text = stand_price_text(number)
    if stand["status"] == "available":
        return (
            f"Genial eleccion. El stand {stand['number']} esta disponible en {zone}. "
            f"Medidas: {stand['size']}.{price_text} "
            "Si te interesa, enviame nombre, marca, producto y ciudad para que el equipo lo revise."
        )

    if stand["status"] == "reserved":
        return (
            f"Disculpa, el stand {stand['number']} ya esta reservado para otro expositor. "
            f"Zona: {zone}. Medidas: {stand['size']}.{price_text} "
            "No debo tomarlo como disponible, pero puedo sugerirte otro. Que otro te interesa?"
        )

    return (
        f"Disculpa, el stand {stand['number']} aparece no disponible. "
        f"Zona: {zone}. Medidas: {stand['size']}.{price_text} "
        "No debo ofrecerlo como opcion, pero puedo ayudarte a revisar alternativas disponibles."
    )


def available_stands_reply():
    patio = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "patio"
    )
    salon = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "salon"
    )

    return (
        "Claro, te comparto el plano actual y estos son los stands disponibles cargados:\n"
        f"Patio de las Artes: {', '.join(str(item) for item in patio)}.\n"
        f"Salon Pierre Daguet: {', '.join(str(item) for item in salon)}.\n"
        "Si quieres detalle de uno, escribeme por ejemplo: stand 21."
    )


def remember_stand_interest(memory, number):
    stand = find_booth(number)
    if not stand:
        memory["blocked_stand"] = number
        memory["blocked_stand_status"] = "unavailable"
        return

    if stand["status"] == "available":
        memory["selected_stand"] = number
        memory["selected_stand_status"] = "available"
        memory["blocked_stand"] = None
        memory["blocked_stand_status"] = None
        return

    memory["blocked_stand"] = number
    memory["blocked_stand_status"] = stand["status"]


def detect_intent(text, memory):
    scores = {}
    for intent, words in INTENTS.items():
        scores[intent] = sum(1 for word in words if normalize(word) in text)

    if wants_human_help(text):
        return "advisor"

    if scores.get("nearby", 0):
        scores["nearby"] += 3

    if scores["booths"] and has_any(text, ["disponible", "disponibles", "reservar", "medida", "zona"]):
        scores["booths"] += 2

    if scores["prices"]:
        scores["prices"] += 2

    if memory.get("role") == "expositor" and scores["prices"]:
        scores["prices"] += 1

    best_intent, best_score = max(scores.items(), key=lambda item: item[1])
    return best_intent if best_score > 0 else "unknown"


def should_treat_as_stand(text, memory):
    return (
        bool(re.search(r"\b(?:stand|puesto)\s*\d{1,3}\b", text))
        or has_any(text, ["quiero", "prefiero", "mejor", "reservado", "disponible", "no disponible"])
        or memory.get("last_intent") in {"booths", "exhibitor"}
        or memory.get("role") == "expositor"
    )


def wants_human_help(text):
    return has_any(
        text,
        [
            "asesor",
            "un asesor",
            "hablar con alguien",
            "hablar con una persona",
            "persona real",
            "humano",
            "contactame",
            "contactarme",
            "contacta",
            "contactenme",
            "llamame",
            "llamarme",
            "equipo de la feria",
        ],
    )


def asks_for_plan(text):
    return has_any(
        text,
        [
            "plano",
            "plano de la feria",
            "plano de stands",
            "mapa de la feria",
            "mapa de stands",
            "compartir el plano",
            "comparteme el plano",
            "ver el plano",
            "ver plano",
        ],
    )


def asks_for_history(text):
    if has_any(text, ["primera vez", "por primera vez", "participar", "expositor", "marca"]):
        return False

    return has_any(
        text,
        [
            "primera feria",
            "primer evento",
            "historia de la feria",
            "origen de la feria",
            "ano se hizo",
            "año se hizo",
            "cuando empezo",
            "cuando inicio",
        ],
    )


def asks_for_metrics(text):
    return has_any(
        text,
        [
            "cuantos expositores",
            "cuantos visitantes",
            "cuantas ferias",
            "ferias realizadas",
            "expositores totales",
            "visitantes por evento",
            "anos de experiencia",
            "años de experiencia",
        ],
    )


def looks_like_lead(message):
    text = normalize(message)
    has_contact_style = any(char.isdigit() for char in message) or "@" in message
    has_business_words = has_any(text, ["marca", "producto", "emprendimiento", "ciudad", "vendo", "ofrezco"])
    has_name_shape = len(message.split()) >= 4
    return has_business_words and (has_contact_style or has_name_shape)


def detect_product_category(text):
    category_aliases = {
        "Arte": ["arte", "pintura", "ilustracion", "escultura"],
        "Artesania tipica": ["artesania", "artesanias", "artesania tipica", "manualidades"],
        "Joyeria": ["joyeria", "joyer", "joria", "joyas", "bisuteria", "aretes", "collares", "pulseras", "anillos"],
        "Calzado y vestuario": ["calzado", "zapatos", "sandalias", "vestuario", "ropa", "moda", "bolsos", "bolso"],
        "Decoracion": ["decoracion", "hogar", "muebles", "deco"],
        "Anticuarios": ["anticuarios", "antiguedades"],
        "Salud y belleza": ["salud", "belleza", "cosmetica", "cosmeticos", "bienestar", "cuidado personal"],
        "Gastronomia": ["gastronomia", "comida", "cafe", "caf", "chocolate", "dulces", "bebidas"],
    }
    for category, aliases in category_aliases.items():
        if has_any(text, aliases):
            return category
    return None


def find_booth(number):
    return next((item for item in BOOTHS if item["number"] == number), None)


def stand_price_text(number):
    price = STAND_PRICES.get(number)
    if not price:
        return ""
    return f" Precio: {price['price']} ({price['type']} de {price['size']})."


def keep_required_details(base_reply, polished_reply):
    final_reply = str(polished_reply or "").strip()
    if not final_reply:
        return base_reply

    urls = re.findall(r"https?://\\S+", base_reply)
    missing_urls = [url for url in urls if url not in final_reply]
    if missing_urls:
        final_reply = f"{final_reply}\n\nFormulario oficial: {missing_urls[0]}"

    return final_reply


def remember_turn(memory, user_message, reply):
    history = memory.setdefault("history", [])
    history.append({"user": user_message, "ori": reply})
    del history[:-4]


def lower_first(value):
    if not value:
        return value
    return value[0].lower() + value[1:]


def extract_stand_number(text):
    explicit = re.search(r"\b(?:stand|puesto)\s*(\d{1,3})\b", text)
    if explicit:
        return int(explicit.group(1))

    referenced = re.search(r"\b(?:el|la|numero|nro|#)\s*(\d{1,3})\b", text)
    if referenced:
        return int(referenced.group(1))

    if re.fullmatch(r"\d{1,3}", text):
        return int(text)

    return None


def has_any(text, words):
    return any(normalize(word) in text for word in words)


def normalize(value):
    normalized = unicodedata.normalize("NFD", str(value).lower())
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    cleaned = re.sub(r"[?¿!¡.,;:()]", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def build_feria_context():
    available_patio = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "patio"
    )
    available_salon = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "salon"
    )
    reserved = sorted(item["number"] for item in BOOTHS if item["status"] == "reserved")
    unavailable = sorted(item["number"] for item in BOOTHS if item["status"] == "unavailable")

    return (
        f"Nombre: {FAIR_INFO['name']}\n"
        f"Fechas: {FAIR_INFO['dates']}\n"
        f"Sede: {FAIR_INFO['venue']}\n"
        f"Proposito: {FAIR_INFO['purpose']}\n"
        f"Web oficial: {FAIR_INFO['official_site']}\n"
        f"Trayectoria: {FAIR_INFO['experience_years']}; {FAIR_INFO['total_fairs']}; "
        f"{FAIR_INFO['total_exhibitors']}; {FAIR_INFO['visitors_per_event']}\n"
        f"Ferias publicadas: {FAIR_INFO['official_fairs']}\n"
        f"Nota publica de ferias activas: {FAIR_INFO['active_fair_public_note']}\n"
        f"Formulario oficial de inscripcion: {FAIR_INFO['registration_form_url']}\n"
        f"Nota del formulario: {FAIR_INFO['registration_form_note']}\n"
        f"Resumen visitantes: {FAIR_INFO['visitor_summary']}\n"
        f"Resumen expositores: {FAIR_INFO['exhibitor_summary']}\n"
        f"Productos y servicios: {FAIR_INFO['products']}\n"
        f"Categorias oficiales de inscripcion: {FAIR_INFO['registration_categories']}\n"
        f"Datos solicitados en inscripcion: {FAIR_INFO['registration_fields']}\n"
        f"Actividades: {FAIR_INFO['activities']}\n"
        f"Ubicacion: {FAIR_INFO['location']}\n"
        f"Lugares cercanos: {FAIR_INFO['nearby_places']}\n"
        f"Historia sede: {FAIR_INFO['venue_history']}\n"
        f"Contexto sede: {FAIR_INFO['venue_context']}\n"
        f"Espacio Patio: {FAIR_INFO['exhibition_spaces']['patio']}\n"
        f"Espacio Salon: {FAIR_INFO['exhibition_spaces']['salon']}\n"
        f"Galeria: {FAIR_INFO['gallery_sections']}\n"
        f"Apoyo humano: {FAIR_INFO['human_help']}\n"
        f"Stands disponibles Patio de las Artes: {', '.join(str(item) for item in available_patio)}\n"
        f"Stands disponibles Salon Pierre Daguet: {', '.join(str(item) for item in available_salon)}\n"
        f"Stands reservados: {', '.join(str(item) for item in reserved)}\n"
        f"Stands no disponibles: {', '.join(str(item) for item in unavailable)}\n"
        f"Incluye en stands: {FAIR_INFO['stand_includes']}\n"
        f"Precios de stands: {format_price_context()}\n"
        "Medidas generales: Patio 2.0 x 1.5 m; Salon 2.0 x 1.3 m. "
        "Algunos stands especiales tienen medidas distintas en el plano."
    )


def format_price_context():
    grouped = {}
    for number, price in sorted(STAND_PRICES.items()):
        key = (price["zone"], price["type"], price["size"], price["price"])
        grouped.setdefault(key, []).append(number)

    lines = []
    for (zone, booth_type, size, amount), numbers in grouped.items():
        zone_name = ZONE_LABELS.get(zone, zone)
        stand_list = ", ".join(str(item) for item in numbers)
        lines.append(f"{zone_name} - {booth_type} {size} {amount}: {stand_list}")
    return " | ".join(lines)
