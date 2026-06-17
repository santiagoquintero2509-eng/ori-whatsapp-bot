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


def get_ori_reply(raw_message):
    if is_openai_enabled():
        try:
            return ask_chatgpt(str(raw_message or ""), build_feria_context())
        except OpenAIClientError as error:
            print(f"No se pudo usar ChatGPT, se usa respaldo local: {error}")

    return get_rule_reply(raw_message)


def get_rule_reply(raw_message):
    message = str(raw_message or "").strip()
    text = normalize(message)

    if not text:
        return menu()

    stand_number = extract_stand_number(text)
    if stand_number:
        return describe_stand(stand_number)

    if has_any(text, ["hola", "buenas", "menu", "ayuda", "inicio"]):
        return f"Hola, soy Ori, tu asistente virtual de {FAIR_INFO['name']}. {menu()}"

    if has_any(text, ["evento", "fecha", "cuando", "horario", "informacion", "info"]):
        return (
            f"La {FAIR_INFO['name']} sera {FAIR_INFO['dates']} en {FAIR_INFO['venue']}. "
            f"Es {FAIR_INFO['visitor_summary']} {unknown_schedule_note()}"
        )

    if has_any(text, ["expositor", "expositores", "participar", "inscribir", "inscripcion", "marca"]):
        return (
            f"Para expositores: {FAIR_INFO['exhibitor_summary']} Puedes preguntarme por "
            "stands disponibles o escribir 'asesor' para que el equipo revise tu caso."
        )

    if has_any(text, ["producto", "productos", "servicio", "servicios", "venden", "comprar"]):
        return (
            f"En la feria encontraras {FAIR_INFO['products']} Si buscas una categoria puntual, "
            "cuentame cual y te ayudo a orientar la consulta."
        )

    if has_any(text, ["ubicacion", "direccion", "donde", "llegar", "mapa", "sede"]):
        return FAIR_INFO["location"]

    if has_any(text, ["actividad", "actividades", "agenda", "programacion", "cultural"]):
        return f"La feria tendra {FAIR_INFO['activities']} {unknown_schedule_note()}"

    if has_any(text, ["stand", "stands", "puesto", "puestos", "disponible", "disponibles"]):
        return available_stands_reply()

    if has_any(text, ["precio", "precios", "valor", "cuanto cuesta", "tarifa", "costo"]):
        return (
            "Los precios no estan cargados en Ori todavia. Escribe 'asesor' y el equipo "
            "comercial te confirma valores, condiciones y disponibilidad actualizada."
        )

    if has_any(text, ["whatsapp", "asesor", "humano", "persona", "contacto", "llamar"]):
        return FAIR_INFO["human_help"]

    return (
        "Te entiendo. Por ahora puedo ayudarte con evento, expositores, productos, "
        f"ubicacion, actividades y stands. {menu()}"
    )


def describe_stand(number):
    stand = next((item for item in BOOTHS if item["number"] == number), None)
    if not stand:
        return (
            f"No encuentro el stand {number} en el plano cargado. Puedes preguntarme por "
            "'stands disponibles' o escribir 'asesor' para confirmar con el equipo."
        )

    status = STATUS_LABELS[stand["status"]]
    zone = ZONE_LABELS[stand["zone"]]
    next_step = (
        "Si te interesa, escribe tu nombre, marca y producto para que el equipo lo revise."
        if stand["status"] == "available"
        else "Si quieres revisarlo de todas formas, escribe 'asesor' para confirmar opciones cercanas."
    )

    return (
        f"El stand {stand['number']} esta {status}. Zona: {zone}. "
        f"Medidas: {stand['size']}. {next_step}"
    )


def available_stands_reply():
    patio = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "patio"
    )
    salon = sorted(
        item["number"] for item in BOOTHS if item["status"] == "available" and item["zone"] == "salon"
    )

    return (
        "Stands disponibles segun el plano cargado:\n"
        f"Patio de las Artes: {', '.join(str(item) for item in patio)}.\n"
        f"Salon Pierre Daguet: {', '.join(str(item) for item in salon)}.\n"
        'Puedes preguntarme por un numero, por ejemplo: "stand 21".'
    )


def menu():
    return (
        "Escribe una opcion: evento, expositores, productos, ubicacion, actividades, "
        "stands disponibles o asesor."
    )


def unknown_schedule_note():
    return "La programacion detallada se puede ajustar; si necesitas un dato exacto, escribe 'asesor'."


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
