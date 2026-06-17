import re
import unicodedata

from data import BOOTHS, FAIR_INFO
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
    ],
    "date": ["fecha", "cuando", "dia", "dias", "horario", "hora", "abre", "cierra", "programacion"],
    "location": ["ubicacion", "direccion", "donde", "llegar", "mapa", "sede", "queda", "lugar"],
    "exhibitor": [
        "expositor",
        "expositores",
        "participar",
        "inscribir",
        "inscripcion",
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

    if is_openai_enabled():
        try:
            return ask_chatgpt(text, build_feria_context())
        except OpenAIClientError as error:
            print(f"No se pudo usar ChatGPT, se usa respaldo local: {error}", flush=True)

    return get_local_ai_reply(text, memory)


def get_memory(user_id):
    key = str(user_id or "default")
    if key not in CONVERSATIONS:
        CONVERSATIONS[key] = {"last_intent": None, "role": None, "selected_stand": None}
    return CONVERSATIONS[key]


def get_local_ai_reply(raw_message, memory):
    message = str(raw_message or "").strip()
    text = normalize(message)

    if not text:
        return welcome_reply(memory)

    if has_any(text, ["hola", "buenas", "buen dia", "buenos dias", "buenas tardes", "menu", "ayuda", "inicio"]):
        memory["last_intent"] = "greeting"
        return welcome_reply(memory)

    if has_any(text, ["soy visitante", "voy como visitante", "quiero visitar", "asistir", "ir a la feria"]):
        memory["role"] = "visitante"
        memory["last_intent"] = "visitor"
        return visitor_guide_reply()

    if has_any(text, ["soy expositor", "quiero exponer", "quiero vender", "quiero participar", "tengo una marca"]):
        memory["role"] = "expositor"
        memory["last_intent"] = "exhibitor"
        return exhibitor_guide_reply()

    if has_any(text, ["que puedo preguntar", "preguntarte", "recomiendame", "recomienda", "opciones"]):
        memory["last_intent"] = "suggestions"
        return suggestions_reply(memory)

    stand_number = extract_stand_number(text)
    if stand_number and should_treat_as_stand(text, memory):
        memory["last_intent"] = "booths"
        memory["selected_stand"] = stand_number
        return describe_stand(stand_number)

    if asks_for_history(text):
        memory["last_intent"] = "history"
        return (
            "Ese dato historico todavia no lo tengo confirmado en mi base de la feria. "
            f"Si quieres, escribe 'asesor' y el equipo de {FAIR_INFO['name']} te ayuda con la informacion oficial."
        )

    intent = detect_intent(text, memory)
    memory["last_intent"] = intent

    if intent == "event":
        return event_reply()
    if intent == "date":
        return date_reply()
    if intent == "location":
        return location_reply()
    if intent == "exhibitor":
        memory["role"] = "expositor"
        return exhibitor_guide_reply()
    if intent == "products":
        return products_reply(text)
    if intent == "activities":
        return activities_reply()
    if intent == "booths":
        return available_stands_reply()
    if intent == "prices":
        return prices_reply(memory)
    if intent == "advisor":
        return advisor_reply()
    if intent == "thanks":
        return "Con gusto. Soy Ori y estoy aqui para ayudarte con la feria cuando lo necesites."

    return smart_fallback_reply(message, memory)


def welcome_reply(memory):
    role_hint = ""
    if memory.get("role") == "expositor":
        role_hint = " Como expositor, puedo orientarte con stands, disponibilidad, medidas y pasos para participar."
    elif memory.get("role") == "visitante":
        role_hint = " Como visitante, puedo orientarte con fecha, ubicacion, productos y actividades."

    return (
        f"Hola, soy Ori, asistente virtual de {FAIR_INFO['name']}. "
        "Puedo ayudarte a ubicar informacion del evento, stands, expositores, productos, actividades y contacto con asesor."
        f"{role_hint} Puedes escribirme con tus propias palabras."
    )


def event_reply():
    return (
        f"La {FAIR_INFO['name']} es un espacio para {FAIR_INFO['purpose']} "
        f"Esta pensada para visitantes que quieren descubrir {FAIR_INFO['products'].rstrip('.')} "
        "y para marcas que buscan conectar con nuevas oportunidades comerciales."
    )


def date_reply():
    return (
        f"La feria esta programada {FAIR_INFO['dates']}. "
        f"La agenda detallada puede ajustarse antes del evento; para horarios exactos de una actividad, escribe 'asesor'."
    )


def location_reply():
    return (
        f"{FAIR_INFO['location']} "
        "Tambien puedo ayudarte a identificar si buscas informacion como visitante o como expositor."
    )


def visitor_guide_reply():
    return (
        f"Perfecto. Como visitante vas a encontrar {FAIR_INFO['products']} "
        f"Tambien habra {FAIR_INFO['activities']} "
        "Puedes preguntarme por fecha, ubicacion, actividades o productos."
    )


def exhibitor_guide_reply():
    return (
        f"Para participar como expositor, la feria ofrece {lower_first(FAIR_INFO['exhibitor_summary'])} "
        "Puedo revisar contigo stands disponibles, medidas y zona. "
        "Si ya tienes una marca, escribeme: nombre, marca, producto y stand que te interesa."
    )


def suggestions_reply(memory):
    if memory.get("role") == "expositor":
        return (
            "Puedes preguntarme cosas como: que stands estan disponibles, cuanto mide el stand 21, "
            "que zona tiene mejor flujo, que datos debo enviar para participar o como hablar con un asesor."
        )

    return (
        "Puedes preguntarme cosas como: donde es la feria, cuando se realiza, que productos encontrare, "
        "que actividades habra, como participar como expositor o que stands estan disponibles."
    )


def products_reply(text):
    category = detect_product_category(text)
    if category:
        return (
            f"Si buscas {category}, Ori lo puede orientar dentro de las categorias de la feria. "
            "La base actual confirma productos como artesanias, moda, accesorios, joyeria, decoracion, bienestar, gastronomia y servicios creativos. "
            "Para una marca o expositor especifico, escribe 'asesor'."
        )

    return (
        f"En la feria encontraras {FAIR_INFO['products']} "
        "Si me dices una categoria, por ejemplo moda, gastronomia o artesanias, te respondo mas puntual."
    )


def activities_reply():
    return (
        f"La feria tendra {FAIR_INFO['activities']} "
        "La programacion fina todavia debe confirmarse, asi que para una hora exacta lo mejor es escribir 'asesor'."
    )


def prices_reply(memory):
    if memory.get("role") == "expositor" or memory.get("last_intent") in {"booths", "exhibitor"}:
        return (
            "Los valores de participacion y condiciones comerciales todavia no estan cargados en Ori. "
            "Escribe tu nombre, marca, producto y stand de interes, o escribe 'asesor', para que el equipo te confirme precios."
        )

    return (
        "Aun no tengo precios o valores oficiales cargados para responder con seguridad. "
        "Si hablas de entrada, stand o participacion, dime cual de esos necesitas y te oriento."
    )


def advisor_reply():
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
            "Puedo ayudarte con stands disponibles, medidas, zonas y paso a asesor. "
            "Si quieres avanzar, enviame nombre, marca, producto y stand de interes."
        )

    return (
        "Te entiendo. Con la informacion cargada puedo orientarte sobre evento, fecha, ubicacion, productos, actividades, expositores y stands. "
        "Preguntame como lo dirias normalmente, por ejemplo: 'donde es', 'que stands hay disponibles' o 'quiero participar con mi marca'."
    )


def describe_stand(number):
    stand = next((item for item in BOOTHS if item["number"] == number), None)
    if not stand:
        return (
            f"No encuentro el stand {number} en el plano cargado. "
            "Puedo mostrarte stands disponibles o pasarte con asesor para validar el plano actualizado."
        )

    status = STATUS_LABELS[stand["status"]]
    zone = ZONE_LABELS[stand["zone"]]
    if stand["status"] == "available":
        next_step = "Si te interesa, enviame nombre, marca, producto y ciudad para que el equipo lo revise."
    elif stand["status"] == "reserved":
        next_step = "Esta reservado; puedo ayudarte a buscar opciones disponibles cercanas."
    else:
        next_step = "No aparece disponible; escribe 'stands disponibles' para ver alternativas."

    return f"El stand {stand['number']} esta {status}. Zona: {zone}. Medidas: {stand['size']}. {next_step}"


def available_stands_reply():
    patio = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "patio"
    )
    salon = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "salon"
    )

    return (
        "Estos son los stands disponibles segun el plano cargado:\n"
        f"Patio de las Artes: {', '.join(str(item) for item in patio)}.\n"
        f"Salon Pierre Daguet: {', '.join(str(item) for item in salon)}.\n"
        "Si quieres detalle de uno, escribeme por ejemplo: stand 21."
    )


def detect_intent(text, memory):
    scores = {}
    for intent, words in INTENTS.items():
        scores[intent] = sum(1 for word in words if normalize(word) in text)

    if scores["booths"] and has_any(text, ["disponible", "disponibles", "reservar", "medida", "zona"]):
        scores["booths"] += 2

    if memory.get("role") == "expositor" and scores["prices"]:
        scores["prices"] += 1

    best_intent, best_score = max(scores.items(), key=lambda item: item[1])
    return best_intent if best_score > 0 else "unknown"


def should_treat_as_stand(text, memory):
    return (
        bool(re.search(r"\b(?:stand|puesto)\s*\d{1,3}\b", text))
        or memory.get("last_intent") in {"booths", "exhibitor"}
        or memory.get("role") == "expositor"
    )


def asks_for_history(text):
    return has_any(text, ["primer", "primera", "historia", "origen de la feria", "ano se hizo", "año se hizo"])


def looks_like_lead(message):
    text = normalize(message)
    has_contact_style = any(char.isdigit() for char in message) or "@" in message
    has_business_words = has_any(text, ["marca", "producto", "emprendimiento", "ciudad", "vendo", "ofrezco"])
    has_name_shape = len(message.split()) >= 4
    return has_business_words and (has_contact_style or has_name_shape)


def detect_product_category(text):
    categories = [
        "artesanias",
        "moda",
        "accesorios",
        "joyeria",
        "decoracion",
        "bienestar",
        "gastronomia",
        "servicios creativos",
    ]
    for category in categories:
        if normalize(category) in text:
            return category
    return None


def lower_first(value):
    if not value:
        return value
    return value[0].lower() + value[1:]


def extract_stand_number(text):
    explicit = re.search(r"\b(?:stand|puesto)\s*(\d{1,3})\b", text)
    if explicit:
        return int(explicit.group(1))

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
        f"Resumen visitantes: {FAIR_INFO['visitor_summary']}\n"
        f"Resumen expositores: {FAIR_INFO['exhibitor_summary']}\n"
        f"Productos y servicios: {FAIR_INFO['products']}\n"
        f"Actividades: {FAIR_INFO['activities']}\n"
        f"Ubicacion: {FAIR_INFO['location']}\n"
        f"Apoyo humano: {FAIR_INFO['human_help']}\n"
        f"Stands disponibles Patio de las Artes: {', '.join(str(item) for item in available_patio)}\n"
        f"Stands disponibles Salon Pierre Daguet: {', '.join(str(item) for item in available_salon)}\n"
        f"Stands reservados: {', '.join(str(item) for item in reserved)}\n"
        f"Stands no disponibles: {', '.join(str(item) for item in unavailable)}\n"
        "Medidas generales: Patio 2.0 x 1.5 m; Salon 2.0 x 1.3 m. "
        "Algunos stands especiales tienen medidas distintas en el plano."
    )
