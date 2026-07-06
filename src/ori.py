import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from data import BOOTHS, FAIR_INFO, STAND_PRICES
from form_responses import (
    filter_form_records,
    find_form_record,
    format_form_record,
    last_form_error,
    record_brand,
)
from groq_client import GroqClientError, classify_admin_intent_with_groq, is_groq_enabled, polish_with_groq
from openai_client import OpenAIClientError, ask_chatgpt, is_openai_enabled
from preinscription import (
    DEFAULT_DRIVE_FOLDER_ID,
    delete_preinscription_by_chat_phone,
    pending_queue_items,
    remove_pending_preinscriptions_for_phone,
    retry_pending_queue,
    submit_preinscription,
    update_confirmed_stand,
    upload_product_media,
)


STATUS_LABELS = {
    "available": "disponible",
    "reserved": "reservado",
    "unavailable": "no disponible",
}

ZONE_LABELS = {
    "patio": "Patio de las Artes",
    "salon": "Salon Pierre Daguet",
}

ADMIN_PHONE_DEFAULT = "573004851602"
ADMIN_ENTRY_CODE_DEFAULT = "In_adm1n"
ADMIN_EXIT_CODE_DEFAULT = "Out_adm1n"
ADVISOR_WHATSAPP_LINK = "https://wa.me/573160282537"
BOGOTA_TZ = timezone(timedelta(hours=-5))
MEMORY_PATH = Path(os.getenv("ORI_USER_MEMORY_PATH", "memoria_revisable/usuarios.json"))
PERSISTENT_STATE = {}
CONVERSATIONS = {}

PREINSCRIPTION_FIELD_ORDER = [
    "preferred_stands",
    "legal_name",
    "representative",
    "stand_name",
    "city",
    "email",
    "socials",
    "products",
    "category",
    "files",
    "confirmation",
]

PREINSCRIPTION_FIELD_LABELS = {
    "legal_name": "Razón social",
    "representative": "Representante",
    "stand_name": "Nombre para el stand",
    "city": "Ciudad",
    "whatsapp": "WhatsApp",
    "email": "Correo",
    "socials": "Redes",
    "products": "Productos",
    "files": "Archivos de productos",
    "category": "Categoria",
    "preferred_stands": "Stands de interes",
}

PREINSCRIPTION_FIELD_ALIASES = {
    "legal_name": ["razon social", "razon", "nombre legal", "empresa", "marca"],
    "representative": ["representante", "nombre representante", "contacto"],
    "stand_name": ["nombre para el stand", "nombre del stand", "stand", "nombre comercial"],
    "city": ["ciudad", "origen", "ciudad de origen"],
    "whatsapp": ["whatsapp", "telefono", "celular", "numero"],
    "email": ["correo", "email", "correo electronico"],
    "socials": ["redes", "redes sociales", "instagram", "pagina web", "web"],
    "products": ["productos", "producto", "productos a participar", "productos para participar"],
    "files": ["archivos", "archivo", "imagenes", "imagen", "catalogo", "pdf", "fotos"],
    "category": ["categoria", "categoria de producto", "tipo de producto"],
    "preferred_stands": ["stands", "stand de interes", "stands de interes", "puestos", "ubicacion"],
}

PREINSCRIPTION_CORRECTION_NUMBER_MAP = {
    "1": "legal_name",
    "2": "representative",
    "3": "stand_name",
    "4": "city",
    "5": "email",
    "6": "socials",
    "7": "products",
    "8": "files",
    "9": "category",
    "10": "preferred_stands",
}


def load_persistent_state():
    if not MEMORY_PATH.exists():
        return {"users": {}, "stands": {}, "admin_sessions": {}, "admin_pending_actions": {}, "admin_last_form_lookup": {}, "admin_last_context": {}, "admin_guided": {}}

    try:
        state = json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"No se pudo cargar memoria persistente: {error}", flush=True)
        return {"users": {}, "stands": {}, "admin_sessions": {}, "admin_pending_actions": {}, "admin_last_form_lookup": {}, "admin_last_context": {}, "admin_guided": {}}

    if not isinstance(state, dict):
        return {"users": {}, "stands": {}, "admin_sessions": {}, "admin_pending_actions": {}, "admin_last_form_lookup": {}, "admin_last_context": {}, "admin_guided": {}}

    state.setdefault("users", {})
    state.setdefault("stands", {})
    state.setdefault("admin_sessions", {})
    state.setdefault("admin_pending_actions", {})
    state.setdefault("admin_last_form_lookup", {})
    state.setdefault("admin_last_context", {})
    state.setdefault("admin_guided", {})
    return state


def save_persistent_state():
    try:
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_PATH.write_text(
            json.dumps(PERSISTENT_STATE, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as error:
        print(f"No se pudo guardar memoria persistente: {error}", flush=True)


PERSISTENT_STATE = load_persistent_state()
CONVERSATIONS = PERSISTENT_STATE.setdefault("users", {})

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
        "asistir",
        "trayectoria",
        "experiencia",
        "cuantas ferias",
        "como es la feria",
    ],
    "date": ["fecha", "cuando", "dia", "dias", "horario", "hora", "abre", "cierra", "programacion"],
    "location": ["ubicacion", "direccion", "donde", "llegar", "mapa", "sede", "queda", "lugar"],
    "confirmed_exhibitors": [
        "expositores",
        "expositor",
        "marcas",
        "marcas confirmadas",
        "quienes participan",
        "quienes participaran",
        "quien participa",
        "quien participara",
        "que marcas",
        "que marcas participan",
        "que marcas participaran",
        "que expositores hay",
        "expositores confirmados",
        "quienes estaran",
        "que encontrare",
    ],
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
        "participar",
        "como puedo participar",
        "quiero participar",
        "estoy interesado en participar",
        "registrar",
        "registrarme",
        "registrarse",
        "inscribir",
        "inscribirme",
        "inscribirse",
        "inscripcion",
        "formulario",
        "tengo una marca",
        "emprendimiento",
        "vender",
        "quiero exponer",
        "quiero vender",
        "quiero un stand",
        "reservar un stand",
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
        "artesanias",
        "joyeria",
        "joyas",
        "bisuteria",
        "accesorios",
        "moda",
        "gastronomia",
        "categoria",
        "categorias",
        "acepta",
    ],
    "activities": ["actividad", "actividades", "agenda", "cultural", "muestra", "networking", "experiencia"],
    "previous_fairs": [
        "fotos",
        "imagenes",
        "galeria",
        "ferias anteriores",
        "feria anterior",
        "ediciones anteriores",
        "versiones anteriores",
        "como ha sido",
        "como se ve",
        "ver fotos",
        "mostrar fotos",
    ],
    "booths": [
        "stand",
        "stands",
        "stan",
        "están",
        "estan",
        "puesto",
        "puestos",
        "disponible",
        "disponibles",
        "reservar",
        "reserva",
    ],
    "prices": ["precio", "precios", "valor", "cuanto cuesta", "tarifa", "costo", "vale", "pagar"],
    "advisor": ["asesor", "humano", "persona", "contacto", "llamar", "whatsapp", "equipo"],
    "thanks": ["gracias", "listo", "perfecto", "ok", "vale", "super"],
}


def get_ori_reply(raw_message, user_id=None, incoming_media=None):
    text = str(raw_message or "").strip()
    memory = get_memory(user_id)

    admin_reply = handle_admin_command(text, user_id) if not incoming_media else None
    if admin_reply:
        remember_turn(memory, text, admin_reply)
        return admin_reply

    if incoming_media and not text:
        text = media_message_text(incoming_media)

    base_reply = get_local_ai_reply(text, memory, incoming_media=incoming_media)
    final_reply = base_reply
    used_groq = False

    if should_keep_base_reply(base_reply, memory):
        remember_turn(memory, text, final_reply)
        save_review_memory_if_needed(text, base_reply, final_reply, memory, used_groq)
        return final_reply

    if is_groq_enabled():
        try:
            final_reply = keep_required_details(base_reply, polish_with_groq(text, base_reply, build_feria_context(), memory))
            used_groq = final_reply != base_reply
        except GroqClientError as error:
            print(f"No se pudo usar Groq, se usa cerebro local: {error}", flush=True)

    elif is_openai_enabled():
        try:
            final_reply = ask_chatgpt(text, build_feria_context())
        except OpenAIClientError as error:
            print(f"No se pudo usar ChatGPT, se usa respaldo local: {error}", flush=True)

    remember_turn(memory, text, final_reply)
    save_review_memory_if_needed(text, base_reply, final_reply, memory, used_groq)
    return final_reply


def should_keep_base_reply(base_reply, memory=None):
    text = normalize(base_reply)
    if memory and memory.get("last_intent") == "preinscription_flow":
        return True
    return False


def media_message_text(media):
    media_type = (media or {}).get("type") or "archivo"
    if media_type == "image":
        return "[imagen de producto]"
    if media_type == "document":
        return "[documento de producto]"
    return "[archivo de producto]"


def get_memory(user_id):
    key = str(user_id or "default")
    if key not in CONVERSATIONS:
        CONVERSATIONS[key] = {
            "phone": key,
            "last_intent": None,
            "role": None,
            "selected_stand": None,
            "selected_stand_status": None,
            "blocked_stand": None,
            "blocked_stand_status": None,
            "desired_stand_type": None,
            "desired_zone": None,
            "pending_field": None,
            "last_offer": None,
            "last_suggested_stand": None,
            "category": None,
            "city": None,
            "brand": None,
            "product": None,
            "confirmed_stand": None,
            "lead_stage": None,
            "process_stage": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": None,
            "form_submitted": False,
            "form_submitted_at": None,
            "registration_link_sent_at": None,
            "preinscription": {},
            "history": [],
            "welcome_gallery_sent": False,
            "welcome_gallery_pending": False,
        }
    memory = CONVERSATIONS[key]
    defaults = {
        "phone": key,
        "last_intent": None,
        "role": None,
        "selected_stand": None,
        "selected_stand_status": None,
        "blocked_stand": None,
        "blocked_stand_status": None,
        "desired_stand_type": None,
        "desired_zone": None,
        "pending_field": None,
        "last_offer": None,
        "last_suggested_stand": None,
        "category": None,
        "city": None,
        "brand": None,
        "product": None,
        "confirmed_stand": None,
        "lead_stage": None,
        "process_stage": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": None,
        "form_submitted": False,
        "form_submitted_at": None,
        "registration_link_sent_at": None,
        "preinscription": {},
        "history": [],
        "welcome_gallery_sent": False,
        "welcome_gallery_pending": False,
    }
    for field, default in defaults.items():
        memory.setdefault(field, default)
    return memory


def handle_admin_command(raw_message, user_id=None):
    message = str(raw_message or "").strip()
    text = normalize(message)
    admin_key = normalize_phone(user_id)

    if is_admin_entry_message(message):
        activate_admin_session(admin_key)
        return "Acceso interno activo. Puedes consultar datos de formularios, historial, clientes y stands."

    if is_admin_exit_message(message):
        clear_admin_own_active_preinscription(admin_key)
        if is_permanent_admin_user(admin_key):
            PERSISTENT_STATE.setdefault("admin_pending_actions", {}).pop(admin_key, None)
            PERSISTENT_STATE.setdefault("admin_last_context", {}).pop(admin_key, None)
            save_persistent_state()
            return "Acceso interno permanente activo. Limpié acciones pendientes, pero este número seguirá en modo administrador."
        deactivate_admin_session(admin_key)
        return "Acceso interno cerrado."

    if not is_admin_user(user_id):
        if mentions_internal_access(text):
            return "Puedo ayudarte con información de la feria, ubicación, stands, productos y participación."
        return None

    pending = PERSISTENT_STATE.setdefault("admin_pending_actions", {}).get(admin_key)

    if pending and confirms_admin_action(text):
        return execute_admin_action(admin_key, pending)

    if pending and cancels_admin_action(text):
        PERSISTENT_STATE["admin_pending_actions"].pop(admin_key, None)
        save_persistent_state()
        return "Listo, no hice ningún cambio."

    action = parse_admin_action(message, text)
    if not action:
        action = parse_admin_followup_action(message, text, admin_key)
    if not action:
        action = parse_admin_action_with_groq(message, admin_key)
    if not action:
        return (
            "Acceso interno activo.\n\n"
            "No voy a iniciar un flujo de cliente mientras estés en acceso interno. "
            "Puedes pedirme datos de formularios, historial, clientes o stands.\n\n"
            "Ejemplos:\n"
            "- quiénes han llenado el formulario\n"
            "- quiénes te han escrito hoy\n"
            "- dame la razón social de Arroz\n"
            "- dale el stand 4 a una marca"
        )

    if action["type"] in {"confirm_stand", "block_stand", "release_stand", "reset_preinscription", "forget_chat_memory"}:
        PERSISTENT_STATE.setdefault("admin_pending_actions", {})[admin_key] = action
        save_persistent_state()
        return admin_action_confirmation_prompt(action)

    if action["type"] == "stand_owner":
        return admin_stand_owner_reply(action["stand"])

    if action["type"] == "reason_social_lookup":
        remember_admin_context(admin_key, "reason_social_lookup")
        return admin_reason_social_lookup_reply(action["query"])

    if action["type"] == "brand_stand_assignment":
        remember_admin_context(admin_key, "brand_stand_assignment")
        return admin_brand_stand_assignment_reply(action["query"])

    if action["type"] == "client_info":
        remember_admin_context(admin_key, "client_info")
        return admin_client_info_reply(action["query"])

    if action["type"] == "confirmed_stands":
        return admin_confirmed_stands_reply()

    if action["type"] == "unassigned_stands":
        return admin_unassigned_stands_reply()

    if action["type"] == "interested_summary":
        return admin_interested_summary_reply(action.get("category"))

    if action["type"] == "admin_help":
        return admin_help_reply()

    if action["type"] == "connection_status":
        return admin_connection_status_reply()

    if action["type"] == "queue_status":
        return admin_queue_status_reply()

    if action["type"] == "retry_pending_queue":
        return admin_retry_pending_queue_reply()

    if action["type"] == "chat_history_prompt":
        remember_admin_context(admin_key, "chat_history_period")
        return "Claro. ¿Qué historial quieres revisar: hoy, ayer o en general?"

    if action["type"] == "chat_history":
        remember_admin_context(admin_key, "chat_history_period")
        return admin_chat_history_reply(action.get("period", "all"), admin_key=admin_key)

    if action["type"] == "form_lookup":
        remember_admin_context(admin_key, "form_lookup")
        return admin_form_lookup_reply(action["query"], admin_key)

    if action["type"] == "retry_form_lookup":
        last_query = PERSISTENT_STATE.get("admin_last_form_lookup", {}).get(admin_key, "")
        if not last_query:
            return "Claro. Dime qué razón social quieres consultar en el formulario."
        return admin_form_lookup_reply(last_query, admin_key, force=True)

    if action["type"] == "form_summary":
        remember_admin_context(
            admin_key,
            "form_summary",
            category=action.get("category"),
            today_only=action.get("today_only", False),
        )
        return admin_form_summary_reply(action.get("category"), action.get("today_only", False))

    return None


def parse_admin_action(message, text):
    if has_any(text, ["soy el administrador", "soy administrador", "modo administrador", "admin"]):
        return {"type": "admin_help"}

    forget_match = re.search(r"\bforg[_\s-]*(\+?\d[\d\s().-]{8,}\d)\b", message, flags=re.IGNORECASE)
    if forget_match:
        phone = normalize_phone(forget_match.group(1))
        if phone:
            return {"type": "forget_chat_memory", "phone": phone}

    natural_reason_match = re.search(
        r"\b(?:dame|dime|busca|buscar|cual\s+es|cual\s+seria|que\s+es|que)\s+"
        r"(?:la\s+)?razon\s+social\s+(?:de|del|para|asociada\s+a)\s+(.+)$",
        text,
    )
    if natural_reason_match:
        query = clean_admin_query(natural_reason_match.group(1))
        if query:
            return {"type": "reason_social_lookup", "query": query}

    natural_assign_match = re.search(
        r"\b(?:dale|darle|asigna|asignar|ponle|pon|dejale|dejarle|entregale)\s+"
        r"(?:el\s+)?stand\s*(\d{1,3})\s+(?:a|para)\s+(.+)$",
        text,
    )
    if natural_assign_match:
        return {
            "type": "confirm_stand",
            "stand": int(natural_assign_match.group(1)),
            "brand": clean_admin_query(natural_assign_match.group(2)),
        }

    natural_brand_gets_stand = re.search(
        r"^(.+?)\s+(?:queda|quedaria|va|iria|se\s+queda)\s+(?:con|en)\s+(?:el\s+)?stand\s*(\d{1,3})\b",
        text,
    )
    if natural_brand_gets_stand:
        return {
            "type": "confirm_stand",
            "stand": int(natural_brand_gets_stand.group(2)),
            "brand": clean_admin_query(natural_brand_gets_stand.group(1)),
        }

    if is_admin_queue_retry_request(text):
        return {"type": "retry_pending_queue"}

    if is_admin_queue_status_request(text):
        return {"type": "queue_status"}

    if asks_connection_status(text):
        return {"type": "connection_status"}

    if is_admin_chat_history_request(text):
        period = detect_admin_history_period(text)
        if period:
            return {"type": "chat_history", "period": period}
        return {"type": "chat_history_prompt"}

    if asks_admin_unassigned_stands(text):
        return {"type": "unassigned_stands"}

    reset_pre_match = re.search(
        r"\b(?:reinicia|reiniciar|resetea|resetear|restablece|restablecer|borra|borrar|limpia|limpiar)\s+"
        r"(?:la\s+)?preinscripcion\b",
        text,
    )
    if reset_pre_match:
        phone = extract_phone_candidate(message)
        if phone:
            return {"type": "reset_preinscription", "phone": phone}
        return {"type": "admin_help"}

    confirm_match = re.search(
        r"\bconfirm\w*\s+(?:el\s+)?stand\s*(\d{1,3})\s+para\s+(.+)$",
        text,
    )
    if confirm_match:
        stand = int(confirm_match.group(1))
        brand = extract_brand_after_para(message, stand)
        return {"type": "confirm_stand", "stand": stand, "brand": brand}

    block_match = re.search(
        r"\b(?:bloquea|bloquear|reserva|reservar|ocupa|ocupar)\s+(?:el\s+)?stand\s*(\d{1,3})(?:\s+para\s+(.+))?\b",
        text,
    )
    if block_match:
        stand = int(block_match.group(1))
        brand = extract_brand_after_para(message, stand) if " para " in text else None
        return {"type": "block_stand", "stand": stand, "brand": brand}

    mark_block_match = re.search(
        r"\bmarca\s+(?:el\s+)?stand\s*(\d{1,3})\s+como\s+(?:bloqueado|reservado|ocupado|no disponible)\b",
        text,
    )
    if mark_block_match:
        return {"type": "block_stand", "stand": int(mark_block_match.group(1)), "brand": None}

    release_match = re.search(r"\b(?:libera|liberar|desocupa|desocupar)\s+(?:el\s+)?stand\s*(\d{1,3})\b", text)
    if release_match:
        return {"type": "release_stand", "stand": int(release_match.group(1))}

    owner_match = re.search(r"\b(?:quien|quienes|marca)\s+(?:tiene|tienen|esta|ocupa|ocupan)\s+(?:el\s+)?stand\s*(\d{1,3})\b", text)
    if owner_match:
        return {"type": "stand_owner", "stand": int(owner_match.group(1))}

    brand_assignment_query = extract_brand_assignment_query(text)
    if brand_assignment_query:
        return {"type": "brand_stand_assignment", "query": brand_assignment_query}

    client_info_query = extract_admin_client_info_query(text)
    if client_info_query:
        return {"type": "client_info", "query": client_info_query}

    if has_any(
        text,
        [
            "preinscritos",
            "formularios recibidos",
            "quien lleno formulario",
            "quienes llenaron formulario",
            "quienes han llenado formulario",
            "quienes han llenado el formulario",
            "quienes diligenciaron formulario",
            "inscritos en formulario",
            "lista formularios",
            "lista preinscritos",
        ],
    ):
        return {
            "type": "form_summary",
            "category": detect_product_category(text),
            "today_only": has_any(text, ["hoy", "del dia", "dia de hoy"]),
        }

    if looks_like_form_lookup(text):
        query = extract_form_lookup_query(text)
        if query and normalize(query) not in {"el", "la", "si", "formulario"}:
            return {"type": "form_lookup", "query": query}

    if has_any(text, ["intenta nuevamente", "intentar nuevamente", "vuelve a intentar", "reintenta", "intenta otra vez"]):
        return {"type": "retry_form_lookup"}

    if has_any(text, ["stands confirmados", "stand confirmados", "confirmados"]):
        return {"type": "confirmed_stands"}

    category = detect_product_category(text)
    if has_any(text, ["interesados", "clientes interesados", "resumen de clientes", "leads", "preinscritos"]):
        return {"type": "interested_summary", "category": category}

    return None


def parse_admin_action_with_groq(message, admin_key):
    if not is_groq_enabled():
        return None

    try:
        parsed = classify_admin_intent_with_groq(
            message,
            {
                "last_context": PERSISTENT_STATE.setdefault("admin_last_context", {}).get(admin_key) or {},
                "pending_action": PERSISTENT_STATE.setdefault("admin_pending_actions", {}).get(admin_key) or {},
            },
        )
    except GroqClientError as error:
        print(f"No se pudo interpretar comando administrativo con Groq: {error}", flush=True)
        return None

    return admin_action_from_groq(parsed)


def admin_action_from_groq(parsed):
    intent = normalize(parsed.get("intent") or "")
    if not intent or intent == "unknown":
        return None

    intent_map = {
        "form_summary": "form_summary",
        "form_lookup": "form_lookup",
        "client_info": "client_info",
        "reason_social_lookup": "reason_social_lookup",
        "brand_stand_assignment": "brand_stand_assignment",
        "confirm_stand": "confirm_stand",
        "block_stand": "block_stand",
        "release_stand": "release_stand",
        "stand_owner": "stand_owner",
        "confirmed_stands": "confirmed_stands",
        "unassigned_stands": "unassigned_stands",
        "chat_history": "chat_history",
        "queue_status": "queue_status",
        "retry_pending_queue": "retry_pending_queue",
        "connection_status": "connection_status",
        "reset_preinscription": "reset_preinscription",
        "admin_help": "admin_help",
    }
    action_type = intent_map.get(intent)
    if not action_type:
        return None

    if action_type in {"form_lookup", "client_info", "reason_social_lookup", "brand_stand_assignment"}:
        query = clean_admin_query(parsed.get("query"))
        if not query:
            return None
        return {"type": action_type, "query": query}

    if action_type == "form_summary":
        category = clean_admin_query(parsed.get("category"))
        return {"type": "form_summary", "category": category or None, "today_only": bool(parsed.get("today_only"))}

    if action_type == "chat_history":
        period = normalize(parsed.get("period") or "")
        if period not in {"today", "yesterday", "all"}:
            return {"type": "chat_history_prompt"}
        return {"type": "chat_history", "period": period}

    if action_type in {"confirm_stand", "block_stand"}:
        stand = clean_int(parsed.get("stand"))
        brand = clean_admin_query(parsed.get("brand"))
        if not stand:
            return None
        if action_type == "confirm_stand" and not brand:
            return None
        return {"type": action_type, "stand": stand, "brand": brand or None}

    if action_type in {"release_stand", "stand_owner"}:
        stand = clean_int(parsed.get("stand"))
        if not stand:
            return None
        return {"type": action_type, "stand": stand}

    if action_type == "reset_preinscription":
        phone = normalize_phone(parsed.get("phone"))
        if not phone:
            return None
        return {"type": "reset_preinscription", "phone": phone}

    return {"type": action_type}


def clean_int(value):
    match = re.search(r"\d{1,3}", str(value or ""))
    return int(match.group(0)) if match else None


def is_admin_chat_history_request(text):
    return has_any(
        text,
        [
            "quienes le han escrito",
            "quien le ha escrito",
            "quienes te han escrito",
            "quien te ha escrito",
            "quienes han escrito",
            "quien escribio",
            "quienes escribieron",
            "historial de chats",
            "historial de conversaciones",
            "mensajes recibidos",
            "conversaciones de ori",
            "chats de ori",
            "personas que escribieron",
            "numeros que escribieron",
        ],
    )


def asks_admin_unassigned_stands(text):
    return has_any(
        text,
        [
            "sin stand",
            "sin estand",
            "sin puesto",
            "sin ubicacion",
            "no tiene stand",
            "no tienen stand",
            "pendiente de stand",
            "pendientes de stand",
            "stand pendiente",
            "stand asignado pendiente",
        ],
    )


def detect_admin_history_period(text):
    if has_any(text, ["hoy", "dia de hoy", "del dia"]):
        return "today"
    if has_any(text, ["ayer"]):
        return "yesterday"
    if has_any(text, ["general", "en general", "todos", "todas", "completo", "completa"]):
        return "all"
    return None


def parse_admin_followup_action(message, text, admin_key):
    context = PERSISTENT_STATE.setdefault("admin_last_context", {}).get(admin_key) or {}
    if context.get("type") == "guided_assign_stand":
        number_match = re.search(r"\b(\d{1,3})\b", text)
        brand = clean_admin_query(context.get("brand"))
        if number_match and brand:
            return {"type": "confirm_stand", "stand": int(number_match.group(1)), "brand": brand}
        return None

    if context.get("type") == "chat_history_period":
        period = detect_admin_history_period(text)
        if period:
            return {"type": "chat_history", "period": period}
        return None

    if context.get("type") == "form_summary" and asks_to_refresh_previous_admin_answer(text):
        return {
            "type": "form_summary",
            "category": context.get("category"),
            "today_only": bool(context.get("today_only", False)),
        }

    if context.get("type") not in {"brand_stand_assignment", "client_info", "form_lookup"}:
        return None

    query = extract_short_brand_followup(message, text)
    if not query:
        return None

    if context.get("type") == "client_info":
        return {"type": "client_info", "query": query}
    if context.get("type") == "form_lookup":
        return {"type": "form_lookup", "query": query}
    return {"type": "brand_stand_assignment", "query": query}


def asks_connection_status(text):
    return has_any(
        text,
        [
            "estado conexiones",
            "estado de conexiones",
            "revisa conexiones",
            "revisar conexiones",
            "sheet y drive",
            "google sheet y drive",
            "esta conectado a sheet",
            "esta conectado al sheet",
            "esta conectado a drive",
            "conexion con drive",
            "conexion con sheet",
            "apps script",
        ],
    )


def is_admin_queue_retry_request(text):
    return has_any(
        text,
        [
            "reenviar formularios pendientes",
            "reenvia formularios pendientes",
            "reenviar preinscripciones pendientes",
            "reenvia preinscripciones pendientes",
            "subir formularios pendientes",
            "enviar formularios pendientes",
            "procesar cola",
            "reenviar cola",
        ],
    )


def is_admin_queue_status_request(text):
    return has_any(
        text,
        [
            "formularios en cola",
            "preinscripciones en cola",
            "cola de formularios",
            "cola de preinscripciones",
            "pendientes por subir",
            "formularios pendientes",
            "preinscripciones pendientes",
        ],
    )


def asks_to_refresh_previous_admin_answer(text):
    return has_any(
        text,
        [
            "actualiza",
            "actualizar",
            "actualizala",
            "actualizalo",
            "esa informacion",
            "enviala de nuevo",
            "enviamela de nuevo",
            "mandala de nuevo",
            "muestrala de nuevo",
            "otra vez",
            "nuevamente",
            "intenta nuevamente",
        ],
    )


def remember_admin_context(admin_key, context_type, **details):
    PERSISTENT_STATE.setdefault("admin_last_context", {})[admin_key] = {
        "type": context_type,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **details,
    }
    save_persistent_state()


def extract_short_brand_followup(message, text):
    if not text or len(text) > 60:
        return None

    if has_any(
        text,
        [
            "stand",
            "formulario",
            "preinscripcion",
            "confirmar",
            "bloquear",
            "liberar",
            "gracias",
            "hola",
            "asesor",
            "plano",
            "ubicacion",
            "ruta",
        ],
    ):
        return None

    words = text.split()
    if len(words) > 5:
        return None

    query = re.sub(r"^(y|e|tambien|tambien\s+y|ahora|ok|listo)\s+", "", text).strip(" ?¿.,;:")
    if not query or query in {"si", "no", "eso", "ese", "este", "otra", "otro"}:
        return None

    return clean_admin_query(query) or None


def admin_action_confirmation_prompt(action):
    if action["type"] == "confirm_stand":
        stand = action["stand"]
        brand = action["brand"]
        current = admin_stand_assignment(stand)
        current_note = ""
        if current:
            current_note = f"\n\nAtención: actualmente aparece confirmado para {current.get('brand', 'otra marca')}."
        sheet_owner = form_record_for_confirmed_stand(stand)
        if sheet_owner and not record_matches_brand(sheet_owner, brand):
            current_note += f"\n\nAtención: en la hoja ya aparece para {admin_record_title(sheet_owner)}."
        return (
            f"Voy a marcar el stand {stand} como confirmado para {brand}.{current_note}\n\n"
            "Al confirmar, Ori también enviará el mensaje de confirmación al expositor.\n\n"
            "Para aplicar el cambio, responde: sí confirmo.\n"
            "Para dejarlo igual, responde: cancelar."
        )

    if action["type"] == "block_stand":
        stand = action["stand"]
        brand = action.get("brand")
        current = admin_stand_assignment(stand)
        current_note = ""
        if current:
            current_note = f"\n\nAtención: actualmente aparece {current.get('status', 'ocupado')} para {current.get('brand', 'administración')}."
        brand_note = f" para {brand}" if brand else " por administración"
        return (
            f"Voy a bloquear el stand {stand}{brand_note}. Ori dejará de ofrecerlo como disponible.{current_note}\n\n"
            "Para aplicar el cambio, responde: sí confirmo.\n"
            "Para dejarlo igual, responde: cancelar."
        )

    if action["type"] == "release_stand":
        return (
            f"Voy a liberar la confirmación administrativa del stand {action['stand']}.\n\n"
            "Para aplicar el cambio, responde: sí confirmo.\n"
            "Para dejarlo igual, responde: cancelar."
        )

    if action["type"] == "reset_preinscription":
        return (
            f"Voy a reiniciar el estado de preinscripción del número {action['phone']}.\n\n"
            "Esto permite que ese contacto pueda iniciar una nueva preinscripción por WhatsApp.\n\n"
            "Para aplicar el cambio, responde: sí confirmo.\n"
            "Para dejarlo igual, responde: cancelar."
        )

    if action["type"] == "forget_chat_memory":
        return (
            f"Voy a borrar toda la memoria de Ori asociada al chat {action['phone']}.\n\n"
            "Esto reinicia la conversación de ese número, elimina su estado de preinscripción, "
            "quita formularios pendientes en cola y borra del Google Sheet la fila que coincida en la columna Teléfono chat.\n\n"
            "Para aplicar el cambio, responde: sí confirmo.\n"
            "Para dejarlo igual, responde: cancelar."
        )

    return "Necesito que confirmes el cambio antes de guardarlo."


def execute_admin_action(admin_key, action):
    if action["type"] == "confirm_stand":
        reply = confirm_stand_for_brand(action["stand"], action["brand"])
    elif action["type"] == "block_stand":
        reply = block_stand_by_admin(action["stand"], action.get("brand"))
    elif action["type"] == "release_stand":
        reply = release_stand_confirmation(action["stand"])
    elif action["type"] == "reset_preinscription":
        reply = reset_preinscription_for_phone(action["phone"])
    elif action["type"] == "forget_chat_memory":
        reply = forget_chat_memory_for_phone(action["phone"])
    else:
        reply = "No pude aplicar esa acción."

    PERSISTENT_STATE.setdefault("admin_pending_actions", {}).pop(admin_key, None)
    save_persistent_state()
    return reply


def block_stand_by_admin(stand, brand=None):
    booth = base_booth(stand)
    if not booth:
        return f"No encuentro el stand {stand} en el plano cargado, así que no lo bloqueé."

    now = datetime.now(timezone.utc).isoformat()
    label = brand or "Bloqueado por administración"
    matched_user_id, matched_memory = find_user_by_brand(brand) if brand else (None, None)
    assignment = {
        "stand": stand,
        "brand": label,
        "status": "bloqueado",
        "confirmed_at": now,
        "confirmed_by": "admin",
        "user_id": matched_user_id,
    }
    if matched_memory:
        assignment.update(
            {
                "phone": matched_memory.get("phone"),
                "category": matched_memory.get("category"),
                "product": matched_memory.get("product"),
                "city": matched_memory.get("city"),
                "form_submitted": bool(matched_memory.get("form_submitted")),
            }
        )
        matched_memory["confirmed_stand"] = stand
        matched_memory["selected_stand"] = stand
        matched_memory["selected_stand_status"] = "blocked"
        matched_memory["lead_stage"] = "bloqueado"
        matched_memory["updated_at"] = now

    PERSISTENT_STATE.setdefault("stands", {})[str(stand)] = assignment
    save_persistent_state()

    return (
        f"Listo. Bloqueé el stand {stand}.\n\n"
        f"Estado actualizado: reservado / bloqueado.\n"
        f"Referencia: {label}."
    )


def confirm_stand_for_brand(stand, brand):
    booth = base_booth(stand)
    if not booth:
        return f"No encuentro el stand {stand} en el plano cargado, así que no lo confirmé."

    sheet_owner = form_record_for_confirmed_stand(stand)
    if sheet_owner and not record_matches_brand(sheet_owner, brand):
        return (
            f"No confirmé el stand {stand} porque ya aparece asignado a {admin_record_title(sheet_owner)} "
            "en la hoja de preinscripciones."
        )

    matched_user_id, matched_memory = find_user_by_brand(brand)
    form_record = find_form_record(brand, force=True)
    now = datetime.now(timezone.utc).isoformat()
    assignment = {
        "stand": stand,
        "brand": brand,
        "status": "confirmado",
        "confirmed_at": now,
        "confirmed_by": "admin",
        "user_id": matched_user_id,
    }
    if form_record:
        assignment.update(
            {
                "brand": record_brand(form_record),
                "phone": form_record.get("whatsapp"),
                "category": form_record.get("category"),
                "product": form_record.get("products"),
                "city": form_record.get("city"),
                "email": form_record.get("email"),
                "representative": form_record.get("representative"),
                "form_submitted": True,
            }
        )
    if matched_memory:
        assignment.update(
            {
                "phone": matched_memory.get("phone"),
                "category": matched_memory.get("category"),
                "product": matched_memory.get("product"),
                "city": matched_memory.get("city"),
                "form_submitted": bool(matched_memory.get("form_submitted")),
            }
        )
        matched_memory["confirmed_stand"] = stand
        matched_memory["selected_stand"] = stand
        matched_memory["selected_stand_status"] = "confirmed"
        matched_memory["brand"] = matched_memory.get("brand") or brand
        matched_memory["lead_stage"] = "confirmado"
        matched_memory["updated_at"] = now

    PERSISTENT_STATE.setdefault("stands", {})[str(stand)] = assignment
    save_persistent_state()

    sheet_note = sync_confirmed_stand_to_sheet(assignment, brand, stand)
    notification_note = send_exhibitor_confirmation_message(assignment, stand)

    user_note = ""
    if matched_memory:
        user_note = (
            f"\nCategoría: {matched_memory.get('category') or 'sin categoría cargada'}"
            f"\nProducto: {matched_memory.get('product') or 'sin producto cargado'}"
            f"\nTeléfono: {matched_memory.get('phone') or 'sin teléfono'}"
        )

    return (
        f"Listo. Confirmé el stand {stand} para {brand}.\n\n"
        f"Estado actualizado: ocupado / confirmado.{user_note}{sheet_note}{notification_note}"
    )


def sync_confirmed_stand_to_sheet(assignment, original_brand, stand):
    query = assignment.get("brand") or original_brand
    representative = assignment.get("representative") or ""
    try:
        result = update_confirmed_stand(query, stand, representative=representative)
    except Exception as error:
        print(f"No se pudo actualizar stand confirmado en Sheet: {error}", flush=True)
        return "\nHoja de cálculo: no pude actualizarla en este momento."

    if result.get("ok"):
        return "\nHoja de cálculo: stand confirmado actualizado."
    if result.get("queued"):
        return "\nHoja de cálculo: actualización pendiente en cola."
    return f"\nHoja de cálculo: no pude actualizarla ({result.get('error') or 'sin detalle'})."


def send_exhibitor_confirmation_message(assignment, stand):
    phone = normalize_outbound_whatsapp_number(assignment.get("phone") or assignment.get("user_id"))
    if not phone:
        return "\nMensaje al expositor: no pude enviarlo porque no encontré un WhatsApp válido."

    brand = assignment.get("brand") or "tu marca"
    message = exhibitor_confirmation_message(brand, stand)
    try:
        send_whatsapp_text_from_ori(phone, message)
    except Exception as error:
        print(f"No se pudo enviar confirmación al expositor {phone}: {error}", flush=True)
        return "\nMensaje al expositor: no pude enviarlo en este momento."

    return "\nMensaje al expositor: enviado."


def exhibitor_confirmation_message(brand, stand):
    return (
        f"¡Qué alegría darte esta noticia, {brand}!\n\n"
        f"¡Nos emociona mucho contar contigo en esta edición con el stand {stand}!\n\n"
        "Tu preinscripción para Feria Origen Colombia 2027 fue revisada y tu participación ha sido confirmada.\n\n"
        "Muy pronto el equipo organizador se comunicará contigo para continuar con los detalles de inscripción, pagos y preparación para la feria."
    )


def normalize_outbound_whatsapp_number(value):
    phone = normalize_phone(value)
    if not phone:
        return ""
    if len(phone) == 10 and phone.startswith("3"):
        return "57" + phone
    if len(phone) == 12 and phone.startswith("57"):
        return phone
    return phone


def send_whatsapp_text_from_ori(to, body):
    token = os.getenv("WHATSAPP_TOKEN", "")
    phone_number_id = os.getenv("PHONE_NUMBER_ID", "")
    graph_version = os.getenv("GRAPH_API_VERSION", "v20.0")
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    if dry_run or not token or not phone_number_id:
        print(f"Envío de confirmación omitido para {to}: DRY_RUN activo o faltan credenciales.", flush=True)
        return

    url = f"https://graph.facebook.com/{graph_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        response.read()


def admin_form_lookup_reply(query, admin_key=None, force=False):
    if admin_key and query:
        PERSISTENT_STATE.setdefault("admin_last_form_lookup", {})[admin_key] = query
        save_persistent_state()

    if force:
        try:
            from form_responses import get_form_records

            get_form_records(force=True)
        except Exception as error:
            print(f"No se pudo refrescar hoja de formularios: {error}", flush=True)

    record = find_form_record(query, force=True)
    if not record:
        error = last_form_error()
        if error:
            return (
                "No pude consultar la hoja de preinscripciones en este momento. "
                "El enlace ya puede estar compartido, pero Google todavía puede bloquear la descarga CSV. "
                "Revisa que la hoja permita lectura con enlace o publícala como CSV."
            )
        return f"No encontré una preinscripción para {query} en la hoja conectada."

    return "Sí, encontré esta preinscripción:\n\n" + format_form_record(record)


def admin_reason_social_lookup_reply(query):
    record = find_form_record(query, force=True)
    if not record:
        error = last_form_error()
        if error:
            return (
                "No pude consultar la hoja de preinscripciones en este momento. "
                "Intenta nuevamente en unos segundos."
            )
        return f"No encontré una razón social asociada a {query} en la hoja conectada."

    legal_name = record.get("legal_name") or "sin dato"
    stand_name = record.get("stand_name") or query
    representative = record.get("representative") or "sin dato"
    whatsapp = record.get("whatsapp") or "sin dato"
    return (
        f"La razón social asociada a {stand_name} es: {legal_name}.\n\n"
        f"Representante: {representative}\n"
        f"WhatsApp: {whatsapp}"
    )


def admin_client_info_reply(query):
    record = find_form_record(query, force=True)
    assignment = find_admin_assignment_by_brand(query)
    memories = find_user_memories_for_client(query, record)
    brand = resolved_client_brand(query, record, assignment, memories)

    if not record and not assignment and not memories:
        return (
            f"No encontré información administrativa para {query} en la hoja, memoria de WhatsApp "
            "ni stands confirmados. Puede estar escrito diferente."
        )

    lines = [f"Informe administrativo: {brand}"]
    lines.append("")

    if record:
        lines.extend(format_admin_record_lines(record))
    else:
        lines.append("Formulario: no encontré registro en la hoja conectada.")

    lines.append("")
    lines.extend(format_admin_assignment_lines(query, record, assignment, memories))

    lines.append("")
    if memories:
        lines.extend(format_admin_memory_lines(memories[0]))
        if len(memories) > 1:
            lines.append(f"Otros chats posiblemente relacionados: {len(memories) - 1}.")
    else:
        lines.append("Conversación por WhatsApp: no encontré memoria asociada a esta marca o teléfono.")

    return "\n".join(lines)


def format_admin_record_lines(record):
    lines = [
        "Formulario: preinscripción recibida.",
        f"Razón social: {record.get('legal_name') or 'sin dato'}",
        f"Representante: {record.get('representative') or 'sin dato'}",
        f"Nombre para el stand: {record.get('stand_name') or 'sin dato'}",
        f"Ciudad: {record.get('city') or 'sin dato'}",
        f"WhatsApp: {record.get('whatsapp') or 'sin dato'}",
        f"Correo: {record.get('email') or 'sin dato'}",
        f"Producto: {record.get('products') or 'sin dato'}",
    ]
    if record.get("socials"):
        lines.append(f"Redes/web: {record.get('socials')}")
    if record.get("sample"):
        lines.append(f"Muestra/catálogo: {record.get('sample')}")
    if record.get("comments"):
        lines.append(f"Comentarios: {record.get('comments')}")
    return lines


def format_admin_assignment_lines(query, record, assignment, memories):
    if assignment:
        return [
            f"Stand asignado: {assignment.get('stand') or 'sin número'}",
            f"Estado administrativo: {assignment.get('status') or 'confirmado'}",
        ]

    if record and record.get("confirmed_stand"):
        return [
            f"Stand asignado en hoja: {record.get('confirmed_stand')}",
            "Estado administrativo: validar si esa columna corresponde a confirmación final del equipo.",
        ]

    for _, memory in memories:
        if memory.get("confirmed_stand"):
            return [
                f"Stand confirmado en memoria: {memory.get('confirmed_stand')}",
                "Estado administrativo: confirmado en memoria de WhatsApp.",
            ]

    return [
        "Stand asignado: pendiente.",
        "Estado administrativo: preinscripción recibida, pendiente de asignación de stand."
        if record
        else "Estado administrativo: sin preinscripción en hoja, revisar manualmente.",
    ]


def format_admin_memory_lines(memory_item):
    user_id, memory = memory_item
    parts = []
    selected = memory.get("selected_stand")
    blocked = memory.get("blocked_stand")
    suggested = memory.get("last_suggested_stand")
    if selected:
        parts.append(f"mostró interés en el stand {selected}")
    elif suggested:
        parts.append(f"recibió sugerencia del stand {suggested}")
    elif blocked:
        parts.append(f"consultó el stand {blocked}, que aparece {STATUS_LABELS.get(memory.get('blocked_stand_status'), 'no disponible')}")
    else:
        parts.append("ha conversado con Ori")

    if memory.get("form_submitted"):
        parts.append("ya indicó que llenó o envió el formulario")
    elif memory.get("registration_link_sent_at"):
        parts.append("ya recibió el link de preinscripción")
    else:
        parts.append("aún no indicó formulario enviado")

    lines = [
        f"Conversación por WhatsApp: {', y '.join(parts)}.",
        f"Teléfono del chat: {memory.get('phone') or user_id}",
    ]
    if memory.get("brand"):
        lines.append(f"Marca detectada en chat: {memory.get('brand')}")
    if memory.get("category"):
        lines.append(f"Categoría detectada en chat: {memory.get('category')}")
    if memory.get("product"):
        lines.append(f"Producto detectado en chat: {memory.get('product')}")
    if memory.get("city"):
        lines.append(f"Ciudad detectada en chat: {memory.get('city')}")
    return lines


def admin_help_reply():
    return (
        "Acceso interno activo.\n\n"
        "Puedes pedirme, por ejemplo:\n"
        "- Ori, dame más información sobre Aurora Boreal\n"
        "- Ori, qué datos tienes de Panta\n"
        "- Ori, dame la razón social de Arroz\n"
        "- Ori, busca Aurora Boreal en el formulario\n"
        "- Ori, Aurora Boreal ya llenó formulario?\n"
        "- Ori, muestra preinscritos\n"
        "- Ori, ver formularios pendientes\n"
        "- Ori, reenviar formularios pendientes\n"
        "- Ori, quiénes le han escrito\n"
        "- Ori, confirma el stand 3 para Aurora Boreal\n"
        "- Ori, dale el stand 29 a Zonum SAS\n"
        "- Ori, reinicia preinscripción de este número 573004851602\n"
        "- Ori, forg_573004851602\n"
        "- Ori, bloquea el stand 3\n"
        "- Ori, quien tiene el stand 3"
    )


def admin_guided_menu_text():
    return (
        "Acceso interno activo.\n\n"
        "Elige qué quieres revisar:"
    )


def admin_guided_preinscribed_rows(admin_key):
    records = filter_form_records(force=True)
    if not records:
        return admin_no_form_records_reply(), []

    preinscribed = [record for record in records if not str(record.get("confirmed_stand") or "").strip()]
    if not preinscribed:
        return "Por ahora no hay preinscritos pendientes de stand confirmado.", []

    rows = []
    lookup = {}
    for index, record in enumerate(preinscribed[:10]):
        row_id = f"ORI_ADM_PRE_{index}"
        title = admin_record_title(record)
        category = record.get("category") or "sin categoría"
        interests = record.get("comments") or record.get("postdata") or record.get("raw", {}).get("Stands de interes", "")
        description = f"{category}"
        if interests:
            description += f" - Interés: {interests}"
        rows.append(
            {
                "id": row_id,
                "title": title,
                "description": description,
            }
        )
        lookup[row_id] = {"kind": "preinscrito", "query": title, "record": record}

    save_admin_guided_lookup(admin_key, lookup)
    body = f"Preinscritos pendientes: {len(preinscribed)}\n\nElige una razón social para revisar sus datos."
    if len(preinscribed) > 10:
        body += f"\n\nMostrando los primeros 10 de {len(preinscribed)}."
    return body, rows


def admin_guided_confirmed_rows(admin_key):
    records = filter_form_records(force=True)
    if not records:
        return admin_no_form_records_reply(), []

    confirmed = [record for record in records if str(record.get("confirmed_stand") or "").strip()]
    if not confirmed:
        return "Por ahora no hay expositores confirmados en la hoja.", []

    rows = []
    lookup = {}
    for index, record in enumerate(confirmed[:10]):
        row_id = f"ORI_ADM_CON_{index}"
        title = admin_record_title(record)
        stand = str(record.get("confirmed_stand") or "").strip()
        category = record.get("category") or "sin categoría"
        rows.append(
            {
                "id": row_id,
                "title": title,
                "description": f"Stand {stand} - {category}",
            }
        )
        lookup[row_id] = {"kind": "confirmado", "query": title, "record": record}

    save_admin_guided_lookup(admin_key, lookup)
    body = f"Expositores confirmados: {len(confirmed)}\n\nElige una razón social para ver el detalle."
    if len(confirmed) > 10:
        body += f"\n\nMostrando los primeros 10 de {len(confirmed)}."
    return body, rows


def admin_confirmed_records_text():
    records = filter_form_records(force=True)
    if not records:
        return admin_no_form_records_reply()

    confirmed = [record for record in records if str(record.get("confirmed_stand") or "").strip()]
    if not confirmed:
        return "Por ahora no hay expositores confirmados en la hoja."

    confirmed = sorted(
        confirmed,
        key=lambda record: (
            int(re.findall(r"\d{1,3}", str(record.get("confirmed_stand") or "999"))[0])
            if re.findall(r"\d{1,3}", str(record.get("confirmed_stand") or ""))
            else 999
        ),
    )
    lines = [f"Expositores confirmados: {len(confirmed)}"]
    for record in confirmed:
        brand = record_brand(record)
        stand = str(record.get("confirmed_stand") or "").strip()
        category = record.get("category") or "sin categoría"
        lines.append(f"- {brand}: stand {stand}, {category}")
    return "\n".join(lines)


def admin_guided_record_detail(admin_key, button_id):
    selected = admin_guided_selected_record(admin_key, button_id)
    if not selected:
        return "No pude encontrar esa selección. Vuelve a abrir la lista y elige la razón social nuevamente.", None

    record = selected["record"]
    kind = selected["kind"]
    save_admin_selected_record(admin_key, record, kind)
    lines = [admin_record_title(record), ""]

    if kind == "confirmado":
        lines.append(f"Stand confirmado: {record.get('confirmed_stand') or 'sin stand'}")

    lines.extend(
        [
            f"Categoría: {record.get('category') or 'sin categoría'}",
            f"Stands de interés: {admin_record_stand_interests(record)}",
            f"Archivos de productos: {record.get('sample') or 'No registra'}",
            f"Representante: {record.get('representative') or 'sin dato'}",
            f"WhatsApp: {record.get('whatsapp') or 'sin dato'}",
        ]
    )

    if record.get("products"):
        lines.append(f"Productos: {record.get('products')}")

    return "\n".join(lines), kind


def admin_prepare_guided_assignment(admin_key):
    selected = get_admin_selected_record(admin_key)
    if not selected:
        return "Primero elige una razón social desde Preinscritos o Confirmados."

    brand = selected.get("query") or "esta marca"
    remember_admin_context(admin_key, "guided_assign_stand", brand=brand)
    return (
        f"Perfecto. Vamos a asignar un stand a {brand}.\n\n"
        f"{admin_available_stands_text()}\n\n"
        "Escribe el número del stand que quieres asignar."
    )


def admin_prepare_guided_release(admin_key):
    selected = get_admin_selected_record(admin_key)
    if not selected:
        return "Primero elige una razón social desde Confirmados."

    record = find_form_record(selected.get("query"), force=True)
    stand = int(str(record.get("confirmed_stand") or "0").strip() or 0) if record else 0
    if not stand:
        return "Esa razón social no tiene stand confirmado en la hoja."

    action = {"type": "release_stand", "stand": stand}
    PERSISTENT_STATE.setdefault("admin_pending_actions", {})[admin_key] = action
    save_persistent_state()
    return admin_action_confirmation_prompt(action)


def admin_available_stands_text():
    occupied = confirmed_stands_from_sheet()
    available = []
    for booth in BOOTHS:
        number = int(booth["number"])
        if number in occupied:
            continue
        if admin_stand_assignment(number):
            continue
        available.append(number)

    if not available:
        return "No encuentro stands disponibles en este momento."

    patio = sorted(number for number in available if (base_booth(number) or {}).get("zone") == "patio")
    salon = sorted(number for number in available if (base_booth(number) or {}).get("zone") == "salon")
    lines = ["Stands disponibles actualmente:"]
    if patio:
        lines.append(f"Patio de las Artes: {', '.join(str(number) for number in patio)}")
    if salon:
        lines.append(f"Salon Pierre Daguet: {', '.join(str(number) for number in salon)}")
    return "\n".join(lines)


def save_admin_guided_lookup(admin_key, lookup):
    if not admin_key:
        return
    bucket = PERSISTENT_STATE.setdefault("admin_guided", {}).setdefault(admin_key, {})
    bucket["lookup"] = lookup
    bucket["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_persistent_state()


def admin_guided_selected_record(admin_key, button_id):
    bucket = PERSISTENT_STATE.setdefault("admin_guided", {}).get(admin_key) or {}
    lookup = bucket.get("lookup") or {}
    item = lookup.get(button_id)
    if not item:
        return None
    record = item.get("record") if isinstance(item.get("record"), dict) else None
    if not record:
        record = find_form_record(item.get("query"), force=True)
    if not record:
        return None
    return {"record": record, "kind": item.get("kind") or "preinscrito"}


def save_admin_selected_record(admin_key, record, kind):
    if not admin_key:
        return
    bucket = PERSISTENT_STATE.setdefault("admin_guided", {}).setdefault(admin_key, {})
    bucket["selected"] = {
        "query": admin_record_title(record),
        "kind": kind,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_persistent_state()


def get_admin_selected_record(admin_key):
    bucket = PERSISTENT_STATE.setdefault("admin_guided", {}).get(admin_key) or {}
    return bucket.get("selected") or {}


def admin_record_title(record):
    return record.get("legal_name") or record_brand(record)


def record_matches_brand(record, brand):
    target = normalize(brand)
    if not target:
        return False
    values = [
        record.get("legal_name"),
        record.get("stand_name"),
        record.get("representative"),
    ]
    for value in values:
        text = normalize(value)
        if text and (text == target or text in target or target in text):
            return True
    return False


def admin_record_stand_interests(record):
    raw = record.get("raw") or {}
    candidates = [
        raw.get("Stands de interes"),
        raw.get("Stands de interés"),
        raw.get("Stand de interes"),
        raw.get("Stand de interés"),
        record.get("comments"),
        record.get("postdata"),
    ]
    for value in candidates:
        if str(value or "").strip():
            return str(value).strip()
    return "No registra"


def admin_no_form_records_reply():
    if last_form_error():
        return (
            "No pude consultar la hoja de preinscripciones en este momento. "
            "Revisa la conexión con Google Sheet e intenta nuevamente."
        )
    return "No encontré preinscritos en la hoja conectada."


def confirmed_stands_from_sheet():
    stands = set()
    for record in filter_form_records(force=True):
        value = str(record.get("confirmed_stand") or "").strip()
        if not value:
            continue
        for match in re.findall(r"\d{1,3}", value):
            stands.add(int(match))
    return stands


def admin_form_summary_reply(category=None, today_only=False):
    records = filter_form_records(category=category, today_only=today_only, force=True)
    if not records:
        error = last_form_error()
        if error:
            return (
                "No pude consultar la hoja de preinscripciones en este momento. "
                "Revisa que la Google Sheet esté compartida para lectura con el enlace."
            )
        if category:
            return f"No encontré preinscritos de {category} en la hoja conectada."
        return "No encontré preinscritos en la hoja conectada."

    title = "Preinscritos"
    if category:
        title += f" de {category}"
    if today_only:
        title += " de hoy"
    lines = [f"{title}: {len(records)}"]
    for record in records[:12]:
        brand = record_brand(record)
        city = record.get("city") or "sin ciudad"
        phone = record.get("whatsapp") or "sin WhatsApp"
        product = record.get("products") or "sin producto"
        stand_status = record_stand_status(record)
        lines.append(f"- {brand}: {city}, {phone}, {product}. {stand_status}")
    return "\n".join(lines)


def admin_unassigned_stands_reply():
    records = filter_form_records(force=True)
    if not records:
        error = last_form_error()
        if error:
            return (
                "No pude consultar la hoja de preinscripciones en este momento. "
                "Intenta nuevamente en unos segundos."
            )
        return "No encontré preinscritos en la hoja conectada."

    unassigned = [record for record in records if not record.get("confirmed_stand")]
    if not unassigned:
        return "Todos los preinscritos de la hoja tienen stand confirmado."

    lines = [f"Preinscritos sin stand confirmado: {len(unassigned)}"]
    for record in unassigned[:15]:
        brand = record_brand(record)
        city = record.get("city") or "sin ciudad"
        phone = record.get("whatsapp") or "sin WhatsApp"
        product = record.get("products") or "sin producto"
        lines.append(f"- {brand}: {city}, {phone}, {product}")
    return "\n".join(lines)


def record_stand_status(record):
    stand = str(record.get("confirmed_stand") or "").strip()
    if stand:
        return f"Stand confirmado: {stand}"
    return "Sin stand confirmado"


def admin_queue_status_reply():
    items = pending_queue_items()
    if not items:
        return "No encontré formularios pendientes en la cola de este servidor."

    submit_items = [item for item in items if item.get("action") == "submit_preinscription"]
    file_items = [item for item in items if item.get("action") == "upload_file"]
    lines = [
        "Pendientes en cola:",
        f"- Formularios: {len(submit_items)}",
        f"- Archivos: {len(file_items)}",
    ]

    for item in submit_items[:8]:
        data = item.get("data") or {}
        brand = data.get("razon_social") or data.get("nombre_para_stand") or "sin razón social"
        phone = data.get("whatsapp") or data.get("telefono_chat") or "sin WhatsApp"
        products = data.get("productos") or "sin producto"
        lines.append(f"- {brand}: {phone}, {products}")

    if len(submit_items) > 8:
        lines.append(f"... y {len(submit_items) - 8} formularios más.")

    lines.append("")
    lines.append("Para intentar subirlos al Sheet, escribe: Ori, reenviar formularios pendientes")
    return "\n".join(lines)


def admin_retry_pending_queue_reply():
    result = retry_pending_queue()
    if result.get("total", 0) == 0:
        return "No encontré formularios pendientes en la cola de este servidor."

    lines = [
        "Resultado de reenvío de cola:",
        f"- Pendientes encontrados: {result.get('total', 0)}",
        f"- Enviados correctamente: {result.get('sent', 0)}",
        f"- Siguen pendientes: {result.get('remaining', 0)}",
    ]
    failures = result.get("failures") or []
    if failures:
        lines.append("")
        lines.append("No pude reenviar estos elementos:")
        for failure in failures[:5]:
            lines.append(f"- {shorten_text(failure, 120)}")
    return "\n".join(lines)


def admin_connection_status_reply():
    sheet_enabled = os.getenv("USE_FORM_SHEET", "true").lower() != "false"
    sheet_id = os.getenv("FORM_RESPONSES_SHEET_ID", "")
    form_url = os.getenv("FORM_RESPONSES_CSV_URL", "")
    webhook = os.getenv("PREINSCRIPTION_WEBHOOK_URL", "").strip()
    drive_id = os.getenv("PREINSCRIPTION_DRIVE_FOLDER_ID", DEFAULT_DRIVE_FOLDER_ID).strip()

    lines = ["Estado de conexiones:"]
    if sheet_enabled and (sheet_id or form_url):
        lines.append("- Google Sheet lectura: configurado.")
    else:
        lines.append("- Google Sheet lectura: falta configurar FORM_RESPONSES_SHEET_ID o FORM_RESPONSES_CSV_URL.")

    if webhook:
        lines.append("- Guardado de preinscripciones en Sheet/Drive: configurado.")
    else:
        lines.append("- Guardado de preinscripciones en Sheet/Drive: falta PREINSCRIPTION_WEBHOOK_URL.")

    if drive_id:
        lines.append("- Carpeta madre de Drive: configurada.")
    else:
        lines.append("- Carpeta madre de Drive: falta PREINSCRIPTION_DRIVE_FOLDER_ID.")

    lines.append("")
    lines.append("Si falta el webhook, Ori puede conversar y recibir datos, pero no puede escribirlos todavía en Google Sheet/Drive.")
    return "\n".join(lines)


def admin_chat_history_reply(period="all", admin_key=None):
    contacts = []
    for user_id, memory in CONVERSATIONS.items():
        history_item = latest_customer_history_item(user_id, memory, admin_key)
        if not history_item:
            continue

        updated_at = parse_datetime(history_item.get("created_at")) or parse_datetime(memory.get("updated_at") or memory.get("created_at"))
        if not history_period_matches(updated_at, period):
            continue
        contacts.append((updated_at or datetime.min.replace(tzinfo=timezone.utc), user_id, memory, history_item))

    contacts.extend(load_conversation_log_contacts(period, existing_user_ids={item[1] for item in contacts}))
    contacts.sort(key=lambda item: item[0], reverse=True)

    label = {"today": "hoy", "yesterday": "ayer", "all": "en general"}.get(period, "en general")
    if not contacts:
        return f"No encontré conversaciones de {label} en la memoria de Ori."

    lines = [f"Conversaciones de {label}: {len(contacts)}"]
    for updated_at, user_id, memory, history_item in contacts[:15]:
        phone = memory.get("phone") or user_id or "sin teléfono"
        brand = memory.get("brand") or "sin marca"
        role = memory.get("role") or "sin rol"
        stage = lead_stage(memory) if is_lead_memory(memory) else "sin etapa comercial"
        stand = memory.get("confirmed_stand") or memory.get("selected_stand") or memory.get("last_suggested_stand") or "sin stand"
        last_message = history_item.get("user") or "sin último mensaje"
        lines.append(
            f"- {phone}: {brand}, {role}, stand {stand}, {stage}. "
            f"Último: {shorten_text(last_message, 80)} ({format_local_datetime(updated_at)})"
        )

    if len(contacts) > 15:
        lines.append(f"... y {len(contacts) - 15} conversaciones más.")
    return "\n".join(lines)


def admin_chat_phone_list_reply(period="all", admin_key=None):
    contacts = []
    for user_id, memory in CONVERSATIONS.items():
        history_item = latest_customer_history_item(user_id, memory, admin_key)
        if not history_item:
            continue

        updated_at = parse_datetime(history_item.get("created_at")) or parse_datetime(memory.get("updated_at") or memory.get("created_at"))
        if not history_period_matches(updated_at, period):
            continue
        contacts.append((updated_at or datetime.min.replace(tzinfo=timezone.utc), user_id, memory, history_item))

    contacts.extend(load_conversation_log_contacts(period, existing_user_ids={item[1] for item in contacts}))
    contacts.sort(key=lambda item: item[0], reverse=True)

    seen = set()
    phones = []
    for _, user_id, memory, _ in contacts:
        phone = str(memory.get("phone") or user_id or "").strip()
        normalized_phone = normalize_phone(phone)
        if not normalized_phone or normalized_phone in seen:
            continue
        seen.add(normalized_phone)
        phones.append(normalized_phone)

    label = {"today": "hoy", "yesterday": "ayer", "all": "en general"}.get(period, "en general")
    if not phones:
        return f"No encontré números que le hayan escrito {label}."

    lines = [f"Números que le han escrito {label}: {len(phones)}"]
    lines.extend(f"- {phone}" for phone in phones[:50])
    if len(phones) > 50:
        lines.append(f"... y {len(phones) - 50} números más.")
    return "\n".join(lines)


def latest_customer_history_item(user_id, memory, admin_key=None):
    last_customer_message = memory.get("last_customer_message")
    last_customer_at = parse_datetime(memory.get("last_customer_at"))
    if last_customer_message and last_customer_at:
        return {"user": last_customer_message, "created_at": last_customer_at.isoformat()}

    history = memory.get("history", [])
    if not history:
        return None

    activation_time = None
    if admin_key and phones_are_equivalent(normalize_phone(user_id), admin_key):
        session = PERSISTENT_STATE.setdefault("admin_sessions", {}).get(admin_key) or {}
        activation_time = parse_datetime(session.get("activated_at"))

    for item in reversed(history):
        user_message = item.get("user", "")
        if is_internal_history_message(user_message):
            continue

        item_time = parse_datetime(item.get("created_at"))
        if activation_time and item_time and item_time >= activation_time:
            continue

        if is_customer_context_message(user_message, memory):
            return item
    return None


def load_conversation_log_contacts(period="all", existing_user_ids=None):
    existing_user_ids = set(existing_user_ids or [])
    path = Path(os.getenv("ORI_CONVERSATION_LOG_PATH", "memoria_revisable/conversaciones_todas.jsonl"))
    if not path.exists():
        return []

    latest_by_phone = {}
    try:
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                phone = item.get("phone") or item.get("user_id")
                if not phone or phone in existing_user_ids:
                    continue
                updated_at = parse_datetime(item.get("created_at"))
                if not history_period_matches(updated_at, period):
                    continue
                if item.get("internal"):
                    continue
                current = latest_by_phone.get(phone)
                if not current or (updated_at and updated_at > current[0]):
                    memory = {
                        "phone": phone,
                        "brand": item.get("brand"),
                        "role": item.get("role"),
                        "selected_stand": item.get("selected_stand"),
                        "confirmed_stand": item.get("confirmed_stand"),
                        "lead_stage": item.get("lead_stage"),
                    }
                    history_item = {"user": item.get("user_message") or "sin ultimo mensaje", "created_at": item.get("created_at")}
                    latest_by_phone[phone] = (updated_at or datetime.min.replace(tzinfo=timezone.utc), phone, memory, history_item)
    except OSError as error:
        print(f"No se pudo leer historial completo de conversaciones: {error}", flush=True)
        return []
    return list(latest_by_phone.values())


def is_internal_history_message(message):
    text = normalize(message)
    raw = clean_admin_access_code(message)
    if raw in {admin_entry_code(), admin_exit_code()}:
        return True
    return bool(
        is_admin_chat_history_request(text)
        or asks_connection_status(text)
        or has_any(text, ["muestra preinscritos", "quienes han llenado formulario", "quienes han llenado el formulario"])
    )


def is_customer_context_message(message, memory):
    text = normalize(message)
    if not text:
        return False
    if is_lead_memory(memory):
        return True
    pre = memory.get("preinscription") or {}
    if pre.get("last_submission") or pre.get("fields"):
        return True
    return not has_any(text, ["acceso interno", "estado conexiones"])


def history_period_matches(updated_at, period):
    if period == "all":
        return True
    if not updated_at:
        return False
    local_date = updated_at.astimezone(BOGOTA_TZ).date()
    today = datetime.now(BOGOTA_TZ).date()
    if period == "today":
        return local_date == today
    if period == "yesterday":
        return local_date == today - timedelta(days=1)
    return True


def parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_local_datetime(value):
    if not value:
        return "sin fecha"
    return value.astimezone(BOGOTA_TZ).strftime("%Y-%m-%d %H:%M")


def latest_user_message(memory):
    for item in reversed(memory.get("history", [])):
        message = item.get("user")
        if message:
            return message
    return ""


def shorten_text(value, max_length):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."


def release_stand_confirmation(stand):
    sheet_record = form_record_for_confirmed_stand(stand)
    sheet_note = ""
    if sheet_record:
        try:
            result = update_confirmed_stand(
                admin_record_title(sheet_record),
                "",
                representative=sheet_record.get("representative") or "",
                status="preinscrito",
                confirmed_by="Ori admin",
            )
            if result.get("ok"):
                sheet_note = "\nHoja de calculo: stand confirmado limpiado."
            elif result.get("queued"):
                sheet_note = "\nHoja de calculo: liberacion pendiente en cola."
            else:
                sheet_note = f"\nHoja de calculo: no pude limpiarla ({result.get('error') or 'sin detalle'})."
        except Exception as error:
            print(f"No se pudo liberar stand confirmado en Sheet: {error}", flush=True)
            sheet_note = "\nHoja de cálculo: no pude limpiarla en este momento."

    removed = PERSISTENT_STATE.setdefault("stands", {}).pop(str(stand), None)
    for memory in CONVERSATIONS.values():
        if memory.get("confirmed_stand") == stand:
            memory["confirmed_stand"] = None
            memory["lead_stage"] = "preinscrito" if memory.get("form_submitted") else "interesado"
            if memory.get("selected_stand") == stand:
                memory["selected_stand_status"] = "available"
            memory["updated_at"] = datetime.now(timezone.utc).isoformat()

    save_persistent_state()
    if not removed and not sheet_record:
        return f"El stand {stand} no tenía una confirmación administrativa guardada."
    return f"Listo. Liberé la confirmación administrativa del stand {stand}.{sheet_note}"


def reset_preinscription_for_phone(phone):
    user_id, memory = find_user_by_phone(phone)
    if not memory:
        return f"No encontré memoria de WhatsApp para el número {phone}."

    clear_preinscription_state(memory)
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_persistent_state()
    return f"Listo. Reinicié el estado de preinscripción del número {memory.get('phone') or user_id}."


def forget_chat_memory_for_phone(phone):
    target_phone = normalize_phone(phone)
    user_id, memory = find_user_by_phone(phone)
    display_phone = (memory.get("phone") if memory else None) or target_phone or phone
    removed_memory = bool(memory)
    removed_stands = remove_stand_assignments_for_phone(target_phone, user_id)
    removed_admin_state = remove_admin_state_for_phone(target_phone)
    removed_queue = remove_pending_preinscriptions_for_phone(target_phone)
    sheet_result = delete_sheet_preinscription_for_phone(target_phone)

    if memory:
        CONVERSATIONS.pop(user_id, None)
    save_persistent_state()

    lines = [f"Listo. Reinicié todo lo asociado al chat {display_phone}."]
    lines.append("")
    lines.append(f"- Memoria de WhatsApp: {'borrada' if removed_memory else 'no había memoria local guardada'}")
    lines.append(f"- Stands internos asociados: {removed_stands}")
    lines.append(f"- Estados internos de administrador asociados: {removed_admin_state}")
    lines.append(f"- Formularios pendientes en cola: {removed_queue}")
    lines.append(f"- Google Sheet: {sheet_result}")
    lines.append("")
    lines.append("La próxima vez que ese número escriba, Ori lo tratará como una conversación nueva.")
    return "\n".join(lines)


def remove_stand_assignments_for_phone(phone, user_id=None):
    removed = 0
    stands = PERSISTENT_STATE.setdefault("stands", {})
    for stand, assignment in list(stands.items()):
        assignment_phone = normalize_phone(assignment.get("phone"))
        assignment_user_id = normalize_phone(assignment.get("user_id"))
        if (
            phones_are_equivalent(assignment_phone, phone)
            or phones_are_equivalent(assignment_user_id, phone)
            or (user_id and str(assignment.get("user_id") or "") == str(user_id))
        ):
            stands.pop(stand, None)
            removed += 1
    return removed


def remove_admin_state_for_phone(phone):
    removed = 0
    for state_key in ["admin_sessions", "admin_pending_actions", "admin_last_form_lookup", "admin_last_context"]:
        bucket = PERSISTENT_STATE.setdefault(state_key, {})
        for key in list(bucket.keys()):
            if phones_are_equivalent(normalize_phone(key), phone):
                bucket.pop(key, None)
                removed += 1
    return removed


def delete_sheet_preinscription_for_phone(phone):
    if not phone:
        return "no se recibió un número válido"
    try:
        result = delete_preinscription_by_chat_phone(phone)
    except Exception as error:
        print(f"No se pudo borrar preinscripción en Sheet: {error}", flush=True)
        return "no pude borrarla en este momento"

    if result.get("ok"):
        deleted = int(result.get("deleted", 0) or 0)
        if deleted:
            refresh_form_cache_after_delete()
            return f"fila eliminada ({deleted})"
        refresh_form_cache_after_delete()
        return "no había fila con ese Teléfono chat"
    if result.get("queued"):
        return "borrado pendiente en cola"
    return f"no pude borrarla ({result.get('error') or 'sin detalle'})"


def refresh_form_cache_after_delete():
    try:
        from form_responses import clear_form_cache

        clear_form_cache()
    except Exception:
        pass


def clear_admin_own_active_preinscription(admin_key):
    user_id, memory = find_user_by_phone(admin_key)
    if not memory:
        return
    pre = memory.get("preinscription") or {}
    if pre.get("active") or memory.get("pending_field") == "preinscription":
        clear_preinscription_state(memory)
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_persistent_state()


def clear_preinscription_state(memory):
    memory["preinscription"] = {}
    memory["form_submitted"] = False
    memory["form_submitted_at"] = None
    memory["registration_link_sent_at"] = None
    memory["pending_field"] = None
    memory["last_offer"] = None
    memory["last_intent"] = None
    memory["lead_stage"] = None
    memory["process_stage"] = None
    memory["post_submission_corrections"] = []


def find_user_by_phone(phone):
    target = normalize_phone(phone)
    if not target:
        return None, None
    for user_id, memory in CONVERSATIONS.items():
        memory_phone = normalize_phone(memory.get("phone") or user_id)
        if phones_are_equivalent(memory_phone, target) or phones_are_equivalent(normalize_phone(user_id), target):
            return user_id, memory
    return None, None


def admin_stand_owner_reply(stand):
    booth = find_booth(stand)
    if not booth:
        return f"No encuentro el stand {stand} en el plano cargado."

    sheet_record = form_record_for_confirmed_stand(stand)
    if sheet_record:
        details = [
            f"Stand {stand}: confirmado / ocupado.",
            f"Marca o referencia: {record_brand(sheet_record)}",
            f"Razón social: {sheet_record.get('legal_name') or 'sin dato'}",
            f"Representante: {sheet_record.get('representative') or 'sin dato'}",
            f"Producto: {sheet_record.get('products') or 'sin producto cargado'}",
            f"Teléfono: {sheet_record.get('whatsapp') or 'sin teléfono'}",
        ]
        return "\n".join(details)

    assignment = admin_stand_assignment(stand)
    interested = interested_users_for_stand(stand)

    if assignment:
        status = assignment.get("status") or "confirmado"
        brand = assignment.get("brand", "sin marca")
        details = [
            f"Stand {stand}: {status} / ocupado.",
            f"Marca o referencia: {brand}",
            f"Categoría: {assignment.get('category') or 'sin categoría cargada'}",
            f"Producto: {assignment.get('product') or 'sin producto cargado'}",
            f"Teléfono: {assignment.get('phone') or assignment.get('user_id') or 'sin teléfono'}",
        ]
        return "\n".join(details)

    if last_form_error():
        return (
            "No pude consultar la hoja de preinscripciones en este momento. "
            "Intenta nuevamente en unos segundos."
        )

    status = STATUS_LABELS.get(booth.get("status"), booth.get("status"))
    lines = [f"Stand {stand}: no tiene confirmación administrativa guardada. Estado actual: {status}."]
    if interested:
        lines.append("")
        lines.append("Interesados detectados:")
        lines.extend(format_lead_line(memory) for memory in interested[:6])
    else:
        lines.append("No veo interesados guardados para ese stand.")
    return "\n".join(lines)


def form_record_for_confirmed_stand(stand):
    target = str(stand).strip()
    if not target:
        return None
    for record in filter_form_records(force=True):
        value = str(record.get("confirmed_stand") or "").strip()
        if value == target:
            return record
    return None


def admin_brand_stand_assignment_reply(query):
    record = find_form_record(query, force=True)

    if record and record.get("confirmed_stand"):
        return (
            f"{record_brand(record)} tiene confirmado el stand {record.get('confirmed_stand')} "
            "en la hoja de preinscripciones."
        )

    assignment = find_admin_assignment_by_brand(query)
    if assignment:
        stand = assignment.get("stand")
        status = assignment.get("status") or "confirmado"
        brand = assignment.get("brand") or query
        return (
            f"{brand} tiene el stand {stand} marcado en memoria administrativa.\n\n"
            f"Estado: {status}.\n"
            f"Categoría: {assignment.get('category') or 'sin categoría cargada'}.\n"
            f"Teléfono: {assignment.get('phone') or assignment.get('user_id') or 'sin teléfono'}."
        )

    if last_form_error():
        return (
            "No pude consultar la hoja de preinscripciones en este momento. "
            "Intenta nuevamente en unos segundos."
        )

    if record:
        return (
            f"{record_brand(record)} sí aparece en la hoja de preinscripciones, "
            "pero por ahora no encuentro un stand asignado o confirmado para esa razón social.\n\n"
            "Puedes confirmarlo con: Ori, confirma el stand 29 para "
            f"{record_brand(record)}"
        )

    return (
        f"No encontré una preinscripción ni un stand confirmado para {query}. "
        "Puedes revisar el nombre exacto de la razón social o buscarla primero en el formulario."
    )


def find_admin_assignment_by_brand(query):
    target = normalize(query)
    if not target:
        return None

    best = None
    best_score = 0
    for assignment in PERSISTENT_STATE.setdefault("stands", {}).values():
        brand = normalize(assignment.get("brand", ""))
        if not brand:
            continue
        score = 0
        if target == brand:
            score = 5
        elif target in brand or brand in target:
            score = 3
        else:
            shared = set(target.split()) & set(brand.split())
            if len(shared) >= 2:
                score = len(shared)
        if score > best_score:
            best = assignment
            best_score = score
    return best if best_score >= 2 else None


def admin_confirmed_stands_reply():
    sheet_reply = admin_confirmed_records_text()
    if (
        "Expositores confirmados:" in sheet_reply
        or "No pude consultar" in sheet_reply
        or last_form_error()
    ):
        return sheet_reply

    assignments = sorted(
        PERSISTENT_STATE.setdefault("stands", {}).values(),
        key=lambda item: int(item.get("stand", 0)),
    )
    if not assignments:
        return "Por ahora no hay stands confirmados en el panel interno."

    lines = ["Stands confirmados o bloqueados:"]
    for assignment in assignments:
        lines.append(
            f"Stand {assignment.get('stand')}: {assignment.get('brand', 'sin marca')} "
            f"- {assignment.get('status') or 'confirmado'} "
            f"({assignment.get('category') or 'sin categoría'})"
        )
    return "\n".join(lines)


def admin_interested_summary_reply(category=None):
    leads = list(iter_leads(category))
    form_records = filter_form_records(category=category)
    if not leads and not form_records:
        if category:
            return f"No veo interesados guardados en {category}."
        return "Por ahora no veo clientes interesados guardados."

    title = f"Interesados en {category}:" if category else "Clientes interesados:"
    lines = [title]
    lines.extend(format_lead_line(memory) for memory in leads[:12])
    if form_records:
        lines.append("")
        lines.append("Preinscritos en formulario:")
        for record in form_records[:12]:
            lines.append(format_form_lead_line(record))
    return "\n".join(lines)


def format_lead_line(memory):
    brand = memory.get("brand") or "sin marca"
    category = memory.get("category") or "sin categoría"
    stand = memory.get("confirmed_stand") or memory.get("selected_stand") or "sin stand"
    stage = lead_stage(memory)
    phone = memory.get("phone") or "sin teléfono"
    return f"- {brand}: {category}, stand {stand}, {stage}. Tel: {phone}"


def format_form_lead_line(record):
    brand = record_brand(record)
    category = record.get("category") or "sin categoría"
    phone = record.get("whatsapp") or "sin teléfono"
    city = record.get("city") or "sin ciudad"
    return f"- {brand}: {category}, {city}. Tel: {phone}"


def iter_leads(category=None):
    normalized_category = normalize(category or "")
    for user_id, memory in CONVERSATIONS.items():
        if is_admin_user(user_id):
            continue
        if not is_lead_memory(memory):
            continue
        if normalized_category and normalized_category not in normalize(memory.get("category") or ""):
            continue
        yield memory


def interested_users_for_stand(stand):
    return [
        memory
        for memory in iter_leads()
        if memory.get("selected_stand") == stand or memory.get("confirmed_stand") == stand
    ]


def is_lead_memory(memory):
    return any(
        [
            memory.get("role") == "expositor",
            memory.get("category"),
            memory.get("brand"),
            memory.get("product"),
            memory.get("selected_stand"),
            memory.get("form_submitted"),
            memory.get("confirmed_stand"),
        ]
    )


def lead_stage(memory):
    if memory.get("confirmed_stand"):
        return "confirmado"
    if memory.get("form_submitted"):
        return "preinscrito"
    if memory.get("selected_stand"):
        return "interesado"
    return memory.get("lead_stage") or "interesado"


def admin_stand_assignment(stand):
    return PERSISTENT_STATE.setdefault("stands", {}).get(str(stand))


def find_user_by_brand(brand):
    normalized_brand = normalize(brand)
    if not normalized_brand:
        return None, None
    for user_id, memory in CONVERSATIONS.items():
        memory_brand = normalize(memory.get("brand") or "")
        if memory_brand and (memory_brand == normalized_brand or normalized_brand in memory_brand or memory_brand in normalized_brand):
            return user_id, memory
    return None, None


def find_user_memories_for_client(query, record=None):
    target = normalize(query)
    record_phone = normalize_phone(record.get("whatsapp")) if record else ""
    record_terms = set()
    if record:
        for field in ("legal_name", "stand_name", "representative", "email", "products", "socials"):
            value = normalize(record.get(field))
            if value:
                record_terms.add(value)

    matches = []
    for user_id, memory in CONVERSATIONS.items():
        score = client_memory_match_score(user_id, memory, target, record_phone, record_terms)
        if score >= 2:
            matches.append((score, user_id, memory))

    matches.sort(key=lambda item: item[0], reverse=True)
    return [(user_id, memory) for _, user_id, memory in matches[:5]]


def client_memory_match_score(user_id, memory, target, record_phone="", record_terms=None):
    record_terms = record_terms or set()
    score = 0
    memory_phone = normalize_phone(memory.get("phone") or user_id)
    if record_phone and phones_are_equivalent(memory_phone, record_phone):
        score += 12

    haystacks = [
        (memory.get("brand"), 6),
        (memory.get("product"), 3),
        (memory.get("category"), 2),
        (memory.get("city"), 1),
    ]
    for value, weight in haystacks:
        score += text_match_score(target, normalize(value), weight)
        for term in record_terms:
            score += text_match_score(term, normalize(value), max(1, weight - 1))

    history_text = normalize(" ".join(
        f"{item.get('user', '')} {item.get('ori', '')}" for item in memory.get("history", [])[-8:]
    ))
    score += text_match_score(target, history_text, 2)
    for term in record_terms:
        score += text_match_score(term, history_text, 1)

    return score


def text_match_score(needle, haystack, weight=1):
    if not needle or not haystack:
        return 0
    if needle == haystack:
        return 5 * weight
    if needle in haystack or haystack in needle:
        return 3 * weight
    shared = set(needle.split()) & set(haystack.split())
    if len(shared) >= 2:
        return len(shared) * weight
    return 0


def resolved_client_brand(query, record=None, assignment=None, memories=None):
    if record:
        return record_brand(record)
    if assignment and assignment.get("brand"):
        return assignment.get("brand")
    memories = memories or []
    for _, memory in memories:
        if memory.get("brand"):
            return memory.get("brand")
    return query


def sync_form_record_to_memory(memory, record):
    if not record:
        return
    memory["role"] = "expositor"
    memory["form_submitted"] = True
    memory["lead_stage"] = "preinscrito"
    memory["process_stage"] = "preinscripcion_recibida"
    memory["form_submitted_at"] = memory.get("form_submitted_at") or datetime.now(timezone.utc).isoformat()
    memory["brand"] = memory.get("brand") or record_brand(record)
    memory["city"] = memory.get("city") or record.get("city")
    memory["product"] = memory.get("product") or record.get("products")
    memory["category"] = memory.get("category") or record.get("category") or detect_product_category(normalize(record.get("products", "")))
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()


def mark_registration_link_sent(memory):
    now = datetime.now(timezone.utc).isoformat()
    memory["role"] = "expositor"
    if not memory.get("form_submitted"):
        memory["lead_stage"] = "link_enviado"
        memory["process_stage"] = "link_preinscripcion_enviado"
    memory["registration_link_sent_at"] = memory.get("registration_link_sent_at") or now
    memory["updated_at"] = now


def mark_form_submitted_by_user(memory):
    now = datetime.now(timezone.utc).isoformat()
    memory["role"] = "expositor"
    memory["form_submitted"] = True
    memory["lead_stage"] = "preinscrito"
    memory["process_stage"] = "preinscripcion_reportada"
    memory["form_submitted_at"] = memory.get("form_submitted_at") or now
    memory["pending_field"] = None
    memory["last_offer"] = None
    memory["updated_at"] = now


def sync_form_status_if_needed(memory, text):
    if memory.get("form_submitted"):
        return
    if not should_check_form_by_phone(text, memory):
        return
    record = find_form_record(phone=memory.get("phone"))
    if record:
        sync_form_record_to_memory(memory, record)


def should_check_form_by_phone(text, memory):
    return bool(
        memory.get("role") == "expositor"
        or memory.get("registration_link_sent_at")
        or wants_to_participate(text)
        or wants_registration_link(text)
        or wants_to_reserve(text)
        or asks_preinscription_status(text)
        or has_submitted_form(text, memory)
        or has_any(text, ["formulario", "preinscripcion", "inscripcion", "stand", "stands"])
    )


def extract_brand_after_para(message, stand):
    pattern = re.compile(
        rf"stand\s*{stand}\s+para\s+(.+)$",
        re.IGNORECASE,
    )
    match = pattern.search(str(message or ""))
    if not match:
        return "marca sin nombre"
    brand = match.group(1).strip(" .,!¡?¿")
    brand = re.sub(r"\s+", " ", brand)
    return brand or "marca sin nombre"


def clean_admin_query(value):
    query = clean_detected_value(value)
    if not query:
        return None
    query = re.sub(r"^(ori|por favor|si|a)\s+", "", query, flags=re.IGNORECASE).strip()
    return query or None


def extract_brand_assignment_query(text):
    if "stand" not in text and "estand" not in text and "ubicacion" not in text:
        return None
    if not has_any(text, ["asignado", "asignada", "confirmado", "confirmada", "que stand", "que estand", "cual stand", "cual estand", "tiene stand", "tiene estand"]):
        return None

    question_match = re.search(
        r"\b(?:que|cual)\s+(?:stand|estand)\s+(?:tiene|tiene asignado|tiene confirmado|se le asigno|se asigno a)\s+(.+)$",
        text,
    )
    if question_match:
        return clean_admin_query(question_match.group(1))

    direct_match = re.search(
        r"^(.+?)\s+(?:ya\s+)?(?:tiene|tendra|tendria|cuenta\s+con)\s+(?:stand|ubicacion)\s+(?:asignad[oa]|confirmad[oa])\b",
        text,
    )
    if direct_match:
        return clean_admin_query(direct_match.group(1))

    assigned_to_match = re.search(
        r"\b(?:stand|ubicacion)\s+(?:asignad[oa]|confirmad[oa])\s+(?:para|a)\s+(.+)$",
        text,
    )
    if assigned_to_match:
        return clean_admin_query(assigned_to_match.group(1))

    return None


def extract_admin_client_info_query(text):
    patterns = [
        r"\b(?:dame|dame\s+por\s+favor|muestrame|mu[eé]strame|dime|consulta|consultar|revisa|revisar)\s+(?:mas\s+)?(?:informacion|informacion\s+completa|datos|detalle|detalles|estado|perfil)\s+(?:sobre|de|del|para)\s+(.+)$",
        r"\b(?:que|cuales)\s+(?:datos|informacion|detalle|detalles)\s+(?:tienes|hay|tenemos)\s+(?:sobre|de|del|para)\s+(.+)$",
        r"\b(?:estado|perfil|informacion|datos)\s+(?:de|del|sobre)\s+(.+)$",
        r"\b(?:busca|buscar)\s+(?:a\s+)?(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        query = clean_admin_query(match.group(1))
        query = re.sub(r"\s+(?:en\s+)?(?:el\s+)?(?:formulario|preinscripcion)$", "", query or "").strip()
        if query and normalize(query) not in {"el", "la", "los", "las", "formulario", "preinscripcion", "stand"}:
            return query
    return None


def looks_like_form_lookup(text):
    if "formulario" not in text and "preinscripcion" not in text:
        return False
    return has_any(
        text,
        [
            "busca",
            "buscar",
            "consulta",
            "consultar",
            "revisa",
            "revisar",
            "llen",
            "lleno",
            "llena",
            "llene",
            "llenado",
            "envio",
            "enviado",
            "diligencio",
            "diligenciado",
            "preinscrito",
            "preinscrita",
        ],
    )


def extract_form_lookup_query(text):
    lookup_match = re.search(
        r"\b(?:busca|buscar|consulta|consultar|revisa|revisar)\s+(?:a\s+|si\s+)?(.+?)(?:\s+(?:en\s+)?(?:el\s+)?(?:formulario|preinscripcion)|$)",
        text,
    )
    if lookup_match:
        return clean_admin_query(lookup_match.group(1))

    query = re.sub(r"^(ori|por favor|si|a)\s+", "", text).strip()
    query = re.sub(
        r"\b(?:ya\s+)?(?:llen\w*|envio|enviado|diligencio|diligenciado|esta\s+en|esta\s+preinscrit[oa])\b.*$",
        "",
        query,
    ).strip()
    query = re.sub(r"\b(?:el\s+)?(?:formulario|preinscripcion)\b", "", query).strip()
    return clean_admin_query(query)


def confirms_admin_action(text):
    simple_confirmations = {"si", "sí", "ok", "okay", "listo", "dale"}
    if text.strip() in simple_confirmations:
        return True
    confirmation_phrases = [
        "si confirma",
        "si confirmo",
        "sí confirmo",
        "confirmo",
        "confirma",
        "confirmar",
        "cofirmo",
        "si cofirmo",
        "aplica",
        "aplicar",
        "hazlo",
        "hacerlo",
    ]
    return any(has_whole_phrase(text, phrase) for phrase in confirmation_phrases)


def cancels_admin_action(text):
    return has_any(text, ["cancelar", "cancela", "no confirma", "no confirmo", "dejalo igual"])


def is_admin_user(user_id):
    return is_admin_session_active(user_id)


def is_admin_session_active(user_id):
    key = normalize_phone(user_id)
    if not key:
        return False
    if is_permanent_admin_user(key):
        return True
    session = PERSISTENT_STATE.setdefault("admin_sessions", {}).get(key) or {}
    return bool(session.get("active"))


def is_permanent_admin_user(user_id):
    key = normalize_phone(user_id)
    if not key:
        return False
    configured = os.getenv("ORI_ADMIN_PHONE", ADMIN_PHONE_DEFAULT)
    admin_numbers = [normalize_phone(item) for item in re.split(r"[,;\s]+", configured or "") if item.strip()]
    return any(phones_are_equivalent(key, admin_phone) for admin_phone in admin_numbers)


def activate_admin_session(admin_key):
    if not admin_key:
        return
    PERSISTENT_STATE.setdefault("admin_sessions", {})[admin_key] = {
        "active": True,
        "activated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_persistent_state()


def deactivate_admin_session(admin_key):
    if not admin_key:
        return
    PERSISTENT_STATE.setdefault("admin_sessions", {}).pop(admin_key, None)
    PERSISTENT_STATE.setdefault("admin_pending_actions", {}).pop(admin_key, None)
    PERSISTENT_STATE.setdefault("admin_last_context", {}).pop(admin_key, None)
    save_persistent_state()


def is_admin_entry_message(message):
    return clean_admin_access_code(message) == admin_entry_code()


def is_admin_exit_message(message):
    return clean_admin_access_code(message) == admin_exit_code()


def clean_admin_access_code(message):
    return str(message or "").strip().strip("*`_ ")


def admin_entry_code():
    return os.getenv("ORI_ADMIN_ENTRY_CODE", ADMIN_ENTRY_CODE_DEFAULT).strip()


def admin_exit_code():
    return os.getenv("ORI_ADMIN_EXIT_CODE", ADMIN_EXIT_CODE_DEFAULT).strip()


def mentions_internal_access(text):
    return has_any(
        text,
        [
            "modo administrador",
            "administrador",
            "admin",
            "clave interna",
            "acceso interno",
            "codigo interno",
        ],
    )


def normalize_phone(value):
    return re.sub(r"\D+", "", str(value or ""))


def extract_phone_candidate(message):
    for match in re.findall(r"\+?\d[\d\s().-]{8,}\d", str(message or "")):
        phone = normalize_phone(match)
        if 10 <= len(phone) <= 15:
            return phone
    digits = normalize_phone(message)
    if 10 <= len(digits) <= 15:
        return digits
    return ""


def phones_are_equivalent(left, right):
    if not left or not right:
        return False
    if left == right:
        return True
    if len(left) >= 10 and len(right) >= 10:
        return left[-10:] == right[-10:]
    return False


def get_local_ai_reply(raw_message, memory, incoming_media=None):
    message = str(raw_message or "").strip()
    text = normalize(message)

    if not text:
        return welcome_reply(memory)
    if not memory.get("history") and not incoming_media and is_greeting_text(text):
        return welcome_reply(memory)

    category = detect_product_category(text)
    update_lead_memory_from_text(memory, message, text, category)
    sync_form_status_if_needed(memory, text)

    if asks_to_change_topic(text):
        reset_topic_memory(memory)

    preinscription_reply = handle_preinscription_flow(message, text, memory, incoming_media)
    if preinscription_reply:
        return preinscription_reply

    if asks_private_stand_owner(text):
        return privacy_stand_owner_reply()

    stand_number = extract_stand_number(text)
    if asks_stand_includes(text):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        memory["last_intent"] = "stand_includes"
        memory["pending_field"] = None
        return stand_includes_reply(stand_number)

    if stand_number and should_treat_as_stand(text, memory):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        remember_stand_interest(memory, stand_number)
        memory["last_intent"] = "booths"
        if asks_stand_price(text):
            return prices_reply(memory, text)
        return describe_stand(stand_number, memory)

    if wants_human_help(text):
        clear_arrival_context(memory)
        memory["last_intent"] = "advisor"
        memory["pending_field"] = None
        memory["last_offer"] = None
        return advisor_reply(memory)

    if has_submitted_form(text, memory):
        clear_arrival_context(memory)
        sync_form_record_to_memory(memory, find_form_record(phone=memory.get("phone")))
        memory["last_intent"] = "form_submitted"
        mark_form_submitted_by_user(memory)
        return form_submitted_reply()

    if is_contextual_thanks(text):
        memory["last_intent"] = "thanks"
        memory["pending_field"] = None
        memory["last_offer"] = None
        return thanks_reply(memory)

    if asks_preinscription_status(text):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        memory["last_intent"] = "preinscription_status"
        memory["pending_field"] = None
        memory["last_offer"] = None
        return preinscription_status_reply()

    if asks_ambiguous_value_question(text) and has_no_value_context(memory):
        memory["last_intent"] = "ambiguous_value"
        memory["last_offer"] = "visitor_or_exhibitor_value"
        memory["pending_field"] = None
        return ambiguous_value_reply()

    if wants_plan_after_prices_offer(text, memory):
        memory["last_offer"] = None
        memory["last_intent"] = "plan"
        memory["pending_field"] = None
        return plan_reply()

    if is_affirmative_followup(text, memory):
        return handle_affirmative_followup(memory)

    if likes_suggested_stand(text, memory):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        stand = memory.get("last_suggested_stand")
        remember_stand_interest(memory, stand)
        memory["last_intent"] = "booths"
        return describe_stand(stand, memory)

    if asks_for_maps_link(text):
        memory["role"] = "visitante"
        memory["last_intent"] = "maps_link"
        memory["pending_field"] = None
        memory["last_offer"] = None
        return maps_link_reply()

    if is_arrival_followup(text, memory):
        origin = detect_arrival_origin(text)
        memory["role"] = "visitante"
        memory["last_intent"] = "arrival"
        memory["pending_field"] = None
        return arrival_origin_reply(origin)

    if wants_to_start_preinscription_after_offer(text, memory):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        return start_preinscription_flow(memory)

    if wants_registration_link(text):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        if memory.get("form_submitted"):
            memory["pending_field"] = None
            return form_submitted_reply()
        if category:
            memory["category"] = category
        return start_preinscription_flow(memory)

    if wants_to_reserve(text):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        if memory.get("form_submitted"):
            memory["pending_field"] = None
            return submitted_reservation_reply(memory)
        return start_preinscription_flow(memory)

    if asks_for_fair_images(text):
        memory["role"] = "visitante"
        memory["last_intent"] = "previous_fairs"
        memory["pending_field"] = None
        memory["last_offer"] = None
        return previous_fairs_reply()

    if asks_for_plan(text):
        memory["last_intent"] = "plan"
        memory["pending_field"] = None
        return plan_reply()

    if asks_for_arrival(text) and asks_entry_cost(text):
        memory["role"] = "visitante"
        memory["last_intent"] = "arrival_cost"
        memory["pending_field"] = None
        return arrival_and_cost_reply()

    if asks_for_route(text):
        memory["role"] = "visitante"
        memory["last_intent"] = "arrival"
        memory["pending_field"] = "arrival_origin"
        memory["last_offer"] = "maps_link"
        return arrival_route_reply()

    if asks_entry_cost(text):
        memory["role"] = "visitante"
        memory["last_intent"] = "entry_cost"
        memory["pending_field"] = None
        return entry_cost_reply()

    if has_any(text, ["hola", "buenas", "buen dia", "buenos dias", "buenas tardes", "menu", "ayuda", "inicio"]):
        memory["last_intent"] = "greeting"
        return welcome_reply(memory)

    if has_any(text, ["soy visitante", "soy turista", "voy como visitante", "voy como turista", "quiero visitar", "asistir", "ir a la feria"]):
        memory["role"] = "visitante"
        if not has_any(text, ["donde", "ubicacion", "direccion", "queda", "cerca", "productos", "marcas", "actividades", "fecha", "cuando"]):
            memory["last_intent"] = "visitor"
            memory["pending_field"] = None
            return visitor_guide_reply()

    if category and should_treat_category_as_visitor_product(text, memory):
        memory["role"] = "visitante"
        memory["last_intent"] = "products"
        memory["pending_field"] = None
        memory["last_offer"] = None
        return products_reply(text)

    city = detect_city_origin(text)
    if city and memory.get("role") == "expositor":
        memory["city"] = city
        memory["last_intent"] = "lead_city"
        memory["pending_field"] = None
        return exhibitor_city_reply(memory, city)

    stand_type = detect_stand_type(text)
    if stand_type and (should_follow_stand_filters(memory) or has_any(text, ["stand", "stands", "stan", "estan", "puesto", "puestos"])):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        memory["desired_stand_type"] = stand_type
        memory["last_intent"] = "booths"
        zone = detect_zone_preference(text)
        if zone:
            memory["desired_zone"] = zone
            return matching_stands_reply(stand_type, zone, memory)
        return stand_type_followup_reply(stand_type)

    if wants_to_participate(text):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        if memory.get("form_submitted"):
            memory["last_intent"] = "form_submitted"
            memory["pending_field"] = None
            return form_submitted_reply()
        if category:
            memory["category"] = category
        return participation_overview_reply(memory)

    if memory.get("role") == "expositor" and (memory.get("pending_field") == "category" or category):
        if category:
            if memory.get("pending_field") == "registration" and category == memory.get("category"):
                memory["last_intent"] = "product_detail"
                return start_preinscription_flow(memory)
            memory["category"] = category
            if memory.get("form_submitted"):
                return form_submitted_reply()
            return start_preinscription_flow(memory)

    stand_type = detect_stand_type(text)
    if stand_type and (should_follow_stand_filters(memory) or has_any(text, ["stand", "stands", "stan", "estan", "puesto", "puestos"])):
        clear_arrival_context(memory)
        memory["desired_stand_type"] = stand_type
        memory["last_intent"] = "booths"
        zone = detect_zone_preference(text)
        if zone:
            memory["desired_zone"] = zone
            return matching_stands_reply(stand_type, zone, memory)
        return stand_type_followup_reply(stand_type)

    zone = detect_zone_preference(text)
    if zone and memory.get("desired_stand_type") and should_follow_stand_filters(memory):
        memory["desired_zone"] = zone
        memory["last_intent"] = "booths"
        return matching_stands_reply(memory["desired_stand_type"], zone, memory)

    if asks_for_stand_recommendation(text, memory):
        clear_arrival_context(memory)
        memory["role"] = "expositor"
        memory["last_intent"] = "booths"
        return stand_recommendation_reply(memory)

    if has_any(text, ["que puedo preguntar", "preguntarte"]):
        memory["last_intent"] = "suggestions"
        return suggestions_reply(memory)

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
    if intent == "confirmed_exhibitors":
        return confirmed_exhibitors_reply()
    if intent == "location":
        return location_reply()
    if intent == "entry_cost":
        return entry_cost_reply()
    if intent == "venue":
        return venue_reply(text)
    if intent == "exhibitor":
        memory["role"] = "expositor"
        if memory.get("form_submitted"):
            memory["pending_field"] = None
            return form_submitted_reply()
        if category:
            memory["category"] = category
        return participation_overview_reply(memory)
    if intent == "products":
        return products_reply(text)
    if intent == "activities":
        return activities_reply()
    if intent == "previous_fairs":
        return previous_fairs_reply()
    if intent == "booths":
        return available_stands_reply()
    if intent == "prices":
        return prices_reply(memory, text)
    if intent == "advisor":
        return advisor_reply(memory)
    if intent == "thanks":
        return thanks_reply(memory)

    if asks_for_history(text):
        memory["last_intent"] = "history"
        return fair_history_reply()

    return smart_fallback_reply(message, memory)


def handle_preinscription_flow(message, text, memory, incoming_media=None):
    pre = memory.setdefault("preinscription", {})

    if submitted_preinscription_exists(memory):
        if memory.get("pending_field") == "post_submission_correction" and message.strip():
            return record_post_submission_correction(memory, message)
        if incoming_media:
            return (
                "Recibí el archivo como complemento de tu preinscripción.\n\n"
                "No creé una nueva solicitud. El equipo revisará la información enviada y se comunicará contigo "
                "para confirmar disponibilidad, inscripción y métodos de pago."
            )
        if wants_to_correct_preinscription(text):
            memory["pending_field"] = "post_submission_correction"
            save_persistent_state()
            return (
                "Claro, no voy a crear una nueva preinscripción.\n\n"
                "Escríbeme el dato que quieres ajustar y lo dejaré como nota para el equipo."
            )
        if pre.get("active"):
            pre["active"] = False
            memory["pending_field"] = None
            save_persistent_state()
            return duplicate_preinscription_reply(memory)
        if (
            wants_registration_link(text)
            or wants_to_reserve(text)
            or wants_to_participate(text)
            or has_submitted_form(text, memory)
            or has_any(text, ["inscribirme", "preinscribirme", "formulario", "registrarme"])
        ):
            return duplicate_preinscription_reply(memory)

    if incoming_media:
        if pre.get("active") and pre.get("step") in {"files", "correction_files"}:
            return receive_preinscription_media(memory, incoming_media)
        return (
            "Recibí el archivo. Si quieres hacer una preinscripción, escríbeme que deseas participar "
            "y te guío paso a paso."
        )

    if not pre.get("active"):
        return None

    memory["role"] = "expositor"
    memory["last_intent"] = "preinscription_flow"

    if wants_to_cancel_preinscription(text):
        memory["preinscription"] = {}
        memory["pending_field"] = None
        return "Listo, detuve la preinscripción por ahora. Cuando quieras retomarla, escríbeme que deseas participar."

    step = pre.get("step") or next_preinscription_step(pre)

    if step == "correction_select":
        field = detect_preinscription_correction_field(text)
        if not field:
            return preinscription_correction_options_reply()
        return begin_preinscription_field_correction(memory, field)

    if step == "correction_value":
        field = pre.get("editing_field")
        if not field:
            pre["step"] = "correction_select"
            save_persistent_state()
            return preinscription_correction_options_reply()

        updated_value = message.strip()
        if not updated_value:
            return preinscription_field_correction_prompt(field, memory)

        if field == "preferred_stands":
            stands = extract_preferred_stands(updated_value)
            valid, unavailable = validate_preferred_stands(stands)
            if not stands:
                return "Dime 1 o 2 stands de interés según el plano de venta. Por ejemplo: 29 o 29, 40."
            if unavailable:
                unavailable_text = ", ".join(str(item) for item in unavailable)
                return (
                    f"Estos stands no aparecen disponibles en la información actual: {unavailable_text}.\n\n"
                    "Por favor dime 1 o 2 stands disponibles."
                )
            updated_value = ", ".join(str(item) for item in valid[:2])

        pre.setdefault("fields", {})[field] = clean_preinscription_value(updated_value)
        sync_preinscription_field_to_memory(memory, field, updated_value)
        pre.pop("editing_field", None)
        pre["step"] = "confirmation"
        save_persistent_state()
        return "Perfecto, ya actualicé ese dato.\n\n" + preinscription_summary_reply(memory)

    if step == "correction_files":
        if incoming_media:
            return receive_preinscription_media(memory, incoming_media)
        if says_no_files(text):
            pre["files"] = []
            pre.pop("folder_url", None)
            pre["files_status"] = "No enviados"
            pre.pop("editing_field", None)
            pre["step"] = "confirmation"
            save_persistent_state()
            return "Perfecto, dejé los archivos como no enviados.\n\n" + preinscription_summary_reply(memory)
        if is_done_with_files(text):
            if not pre.get("files"):
                pre["files_status"] = "No enviados"
            else:
                pre["files_status"] = "Recibidos"
            pre.pop("editing_field", None)
            pre["step"] = "confirmation"
            save_persistent_state()
            return "Perfecto, ya actualicé los archivos.\n\n" + preinscription_summary_reply(memory)
        return preinscription_field_correction_prompt("files", memory)

    if step == "files":
        if says_no_files(text):
            pre["files_status"] = "No enviados"
            pre["step"] = "confirmation"
            save_persistent_state()
            return (
                "No hay problema, podemos continuar sin archivos por ahora.\n\n"
                "Si más adelante tienes imágenes o catálogo, podrás enviarlos para complementar la revisión de tus productos.\n\n"
                f"{preinscription_prompt('confirmation', memory)}"
            )
        if is_done_with_files(text):
            if not pre.get("files"):
                pre["files_status"] = "No enviados"
                no_files_note = "No hay problema, continuamos sin archivos por ahora.\n\n"
            else:
                pre["files_status"] = "Recibidos"
                no_files_note = "Perfecto, ya tengo tus archivos de productos.\n\n"
            pre["step"] = "confirmation"
            save_persistent_state()
            return no_files_note + preinscription_prompt("confirmation", memory)
        return (
            "Puedes enviarme imágenes, catálogo o PDF de tus productos.\n\n"
            "Si no tienes archivos por ahora, escríbeme 'no tengo'. "
            "Cuando termines de enviarlos, escríbeme 'listo'."
        )

    if step == "confirmation":
        if wants_to_correct_preinscription(text):
            pre["step"] = "correction_select"
            save_persistent_state()
            return preinscription_correction_options_reply()
        if confirms_preinscription(text):
            return finish_preinscription(memory)
        return "Para enviarla, respóndeme 'sí confirmo'. Si quieres corregir algo, dime 'corregir'."

    if step == "preferred_stands":
        stands = extract_preferred_stands(text)
        valid, unavailable = validate_preferred_stands(stands)
        if not stands:
            return "Dime 1 o 2 stands de interés según el plano de venta. Por ejemplo: 29 o 29, 40."
        if unavailable:
            unavailable_text = ", ".join(str(item) for item in unavailable)
            return (
                f"Estos stands no aparecen disponibles en la información actual: {unavailable_text}.\n\n"
                "Por favor dime 1 o 2 stands disponibles."
            )
        selected_stands = ", ".join(str(item) for item in valid[:2])
        pre.setdefault("fields", {})["preferred_stands"] = selected_stands
        sync_preinscription_field_to_memory(memory, "preferred_stands", selected_stands)
        pre["step"] = next_preinscription_step(pre)
        save_persistent_state()
        return preinscription_prompt(pre["step"], memory)

    value = message.strip()
    if not value:
        return preinscription_prompt(step, memory)

    pre.setdefault("fields", {})[step] = clean_preinscription_value(value)
    sync_preinscription_field_to_memory(memory, step, value)
    pre["step"] = next_preinscription_step(pre)
    save_persistent_state()
    return preinscription_prompt(pre["step"], memory)


def start_preinscription_flow(memory):
    if submitted_preinscription_exists(memory):
        memory["pending_field"] = None
        save_persistent_state()
        return duplicate_preinscription_reply(memory)

    pre = memory.setdefault("preinscription", {})
    if pre.get("active"):
        return preinscription_prompt(pre.get("step") or next_preinscription_step(pre), memory)

    memory["role"] = "expositor"
    memory["lead_stage"] = "preinscripcion_en_conversacion"
    memory["process_stage"] = "preinscripcion_en_conversacion"
    memory["last_intent"] = "preinscription_flow"
    memory["pending_field"] = "preinscription"
    memory["preinscription"] = {
        "active": True,
        "step": "preferred_stands",
        "fields": {},
        "files": [],
        "files_status": "Pendiente",
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    save_persistent_state()
    return (
        "¡Perfecto! Empecemos tu preinscripción.\n\n"
        "*Stand de interés*\n"
        "Dime 1 o 2 stands que te interesen según el plano de venta. Sujeto a disponibilidad."
    )


def preinscription_prompt(step, memory):
    prompts = {
        "preferred_stands": (
            "*Stand de interés*\n"
            "Dime 1 o 2 stands que te interesen según el plano de venta. Sujeto a disponibilidad."
        ),
        "legal_name": "*Razón social*\n¿Cuál es la razón social de tu marca o empresa?",
        "representative": "*Nombre del representante*\nO persona que diligencia el formulario.",
        "stand_name": "*Nombre para el stand*\n¿Con cuál nombre quieres que aparezca identificado el stand?",
        "city": "*Ciudad de origen*\n¿De qué ciudad viene tu marca?",
        "email": "*Correo electrónico*\n¿Cuál es el correo de contacto?",
        "socials": "*Redes sociales o página web*\nCompárteme tus redes sociales o página web. Si no tienes, puedes responder: No tengo.",
        "products": (
            "*Productos a participar*\n"
            "Detalle sus productos a participar, los cuales están sujetos a aprobación. "
            "Solo pueden participar los productos aprobados por la organización."
        ),
        "files": (
            "*Archivos de productos*\n"
            "Puedes enviarme imágenes, catálogo o PDF de tus productos.\n\n"
            "Si no tienes archivos, responde: No tengo.\n"
            "Si ya terminaste de enviarlos, responde: Listo."
        ),
        "category": (
            "*Categoría*\n"
            "¿En qué categoría participa tu marca?\n\n"
            "Elige una opción del listado."
        ),
        "confirmation": preinscription_summary_reply(memory),
    }
    return prompts.get(step) or prompts["legal_name"]


def select_preinscription_category(memory, category):
    pre = memory.setdefault("preinscription", {})
    if not pre.get("active"):
        return "Para elegir una categoría, primero inicia el proceso de preinscripción."

    pre.setdefault("fields", {})["category"] = clean_preinscription_value(category)
    sync_preinscription_field_to_memory(memory, "category", category)
    pre["step"] = next_preinscription_step(pre)
    save_persistent_state()
    return (
        f"Perfecto, dejamos tu categoría como: {category}.\n\n"
        f"{preinscription_prompt(pre['step'], memory)}"
    )


def preferred_stands_prompt():
    return (
        "¡Perfecto! Ya tengo la información principal para tu preinscripción.\n\n"
        "Antes de enviarla, te comparto el plano actual y estos son los stands disponibles:\n\n"
        f"{available_stands_text()}\n\n"
        "Dime 1 o 2 stands de interés. Recuerda que la asignación final queda sujeta "
        "a confirmación por parte del equipo organizador."
    )


def preinscription_correction_options_reply():
    return (
        "Claro, lo ajustamos sin empezar de cero.\n\n"
        "Dime exactamente qué dato quieres cambiar. Puedes responder solo con el número:\n\n"
        "1. Razón social\n"
        "2. Representante\n"
        "3. Nombre para el stand\n"
        "4. Ciudad\n"
        "5. Correo\n"
        "6. Redes\n"
        "7. Productos\n"
        "8. Archivos de productos\n"
        "9. Categoría\n"
        "10. Stands de interés"
    )


def detect_preinscription_correction_field(text):
    normalized = normalize(text)
    if not normalized:
        return None

    number_match = re.fullmatch(r"\s*(10|[1-9])\s*[\.\)]?\s*", str(text or ""))
    if number_match:
        return PREINSCRIPTION_CORRECTION_NUMBER_MAP.get(number_match.group(1))

    for field, aliases in PREINSCRIPTION_FIELD_ALIASES.items():
        for alias in aliases:
            normalized_alias = normalize(alias)
            if has_whole_phrase(normalized, normalized_alias) or normalized == normalized_alias:
                return field
    return None


def begin_preinscription_field_correction(memory, field):
    pre = memory.setdefault("preinscription", {})
    pre["editing_field"] = field
    pre["step"] = "correction_files" if field == "files" else "correction_value"
    save_persistent_state()
    return preinscription_field_correction_prompt(field, memory)


def preinscription_field_correction_prompt(field, memory):
    label = PREINSCRIPTION_FIELD_LABELS.get(field, "dato")
    if field == "files":
        return (
            "Perfecto, actualicemos los archivos de productos.\n\n"
            "Puedes enviarme imágenes, catálogo o PDF. Si quieres reemplazar los archivos anteriores, envíame los nuevos ahora.\n\n"
            "Cuando termines, escríbeme: listo. Si quieres dejarlo sin archivos, escríbeme: no tengo."
        )
    if field == "preferred_stands":
        return (
            "Perfecto, actualicemos los stands de interés.\n\n"
            f"Estos son los stands disponibles:\n\n{available_stands_text()}\n\n"
            "Dime 1 o 2 stands de interés."
        )
    return f"Perfecto, ¿cuál es el nuevo dato para {label}?"


def next_preinscription_step(pre):
    fields = pre.setdefault("fields", {})
    for field in PREINSCRIPTION_FIELD_ORDER:
        if field == "files":
            if pre.get("files_status") not in {"Recibidos", "No enviados"}:
                return "files"
            continue
        if field == "confirmation":
            return "confirmation"
        if field not in fields or not fields.get(field):
            return field
    return "confirmation"


def receive_preinscription_media(memory, media):
    pre = memory.setdefault("preinscription", {})
    legal_name = pre.get("fields", {}).get("legal_name") or memory.get("brand") or memory.get("phone") or "Sin razón social"
    result = upload_product_media(
        legal_name,
        media,
        os.getenv("WHATSAPP_TOKEN", ""),
        os.getenv("GRAPH_API_VERSION", "v20.0"),
    )
    file_record = {
        "filename": result.get("filename") or media.get("filename") or media_message_text(media),
        "file_url": result.get("file_url"),
        "folder_url": result.get("folder_url"),
        "media_id": media.get("id"),
        "queued": bool(result.get("queued")),
    }
    pre.setdefault("files", []).append(file_record)
    pre["files_status"] = "Recibidos"
    if result.get("folder_url"):
        pre["folder_url"] = result.get("folder_url")
    save_persistent_state()

    if media.get("type") == "document":
        received = "Recibí el catálogo o documento."
    else:
        received = "Recibí esta imagen."
    return f"{received} Puedes enviar más archivos o escribir 'listo' cuando termines."


def finish_preinscription(memory):
    pre = memory.setdefault("preinscription", {})
    data = build_preinscription_data(memory)
    result = submit_preinscription(data)
    now = datetime.now(timezone.utc).isoformat()

    memory["form_submitted"] = True
    memory["form_submitted_at"] = now
    memory["lead_stage"] = "preinscrito"
    memory["process_stage"] = "preinscripcion_recibida"
    memory["pending_field"] = None
    memory["last_intent"] = "preinscription_flow"
    memory["preinscription"] = {
        "active": False,
        "submitted_at": now,
        "last_submission": data,
        "queued": bool(result.get("queued")),
        "error": result.get("error"),
    }
    save_persistent_state()

    return (
        "¡Listo! Tu preinscripción fue recibida correctamente.\n\n"
        "El equipo revisará la información, los productos y los stands de interés. "
        "Luego se comunicará contigo para confirmar disponibilidad, inscripción y métodos de pago.\n\n"
        "Si necesitas apoyo adicional, puedes hablar con un asesor aquí:\n"
        f"{ADVISOR_WHATSAPP_LINK}"
    )


def submitted_preinscription_exists(memory):
    pre = memory.get("preinscription") or {}
    return bool(
        memory.get("form_submitted")
        or pre.get("submitted_at")
        or pre.get("last_submission")
        or memory.get("process_stage") in {"preinscripcion_recibida", "preinscripcion_reportada"}
    )


def duplicate_preinscription_reply(memory):
    selected_stand = memory.get("selected_stand")
    stand_note = ""
    if selected_stand:
        stand_note = (
            f"\n\nTengo presente tu interés por el stand {selected_stand}. "
            "El número queda sujeto a confirmación final por parte del equipo organizador."
        )
    return (
        "Tu preinscripción ya fue recibida, así que no necesitas enviarla de nuevo.\n\n"
        "El equipo revisará la información, los productos y los stands de interés. Luego se comunicará contigo "
        "para confirmar disponibilidad, inscripción y métodos de pago."
        f"{stand_note}\n\n"
        "Si necesitas apoyo adicional, puedes hablar con un asesor aquí:\n"
        f"{ADVISOR_WHATSAPP_LINK}"
    )


def record_post_submission_correction(memory, message):
    now = datetime.now(timezone.utc).isoformat()
    memory.setdefault("post_submission_corrections", []).append(
        {
            "at": now,
            "message": message.strip(),
        }
    )
    memory["pending_field"] = None
    memory["updated_at"] = now
    save_persistent_state()
    return (
        "Listo, dejé esa corrección como nota para el equipo.\n\n"
        "No creé una nueva preinscripción. El equipo revisará tu solicitud y se comunicará contigo para confirmar "
        "disponibilidad, inscripción y métodos de pago."
    )


def build_preinscription_data(memory):
    pre = memory.setdefault("preinscription", {})
    fields = pre.setdefault("fields", {})
    files = pre.get("files", [])
    file_urls = [item.get("file_url") for item in files if item.get("file_url")]
    folder_url = pre.get("folder_url") or next((item.get("folder_url") for item in files if item.get("folder_url")), "")
    return {
        "razon_social": fields.get("legal_name", ""),
        "nombre_representante": fields.get("representative", ""),
        "nombre_para_stand": fields.get("stand_name", ""),
        "ciudad_origen": fields.get("city", ""),
        "whatsapp": fields.get("whatsapp", "") or memory.get("phone", ""),
        "correo": fields.get("email", ""),
        "redes": fields.get("socials", ""),
        "productos": fields.get("products", ""),
        "categoria": fields.get("category", ""),
        "stands_interes": fields.get("preferred_stands", ""),
        "archivos_productos": "\n".join(file_urls) if file_urls else pre.get("files_status", "No enviados"),
        "carpeta_drive": folder_url,
        "telefono_chat": memory.get("phone", ""),
    }


def preinscription_summary_reply(memory):
    data = build_preinscription_data(memory)
    return (
        "Excelente, antes de enviar tu preinscripción revisa que todo esté correcto:\n\n"
        f"*Stands de interés:* {data['stands_interes'] or 'pendiente'}\n"
        f"*Razón social:* {data['razon_social'] or 'pendiente'}\n"
        f"*Representante:* {data['nombre_representante'] or 'pendiente'}\n"
        f"*Nombre para el stand:* {data['nombre_para_stand'] or 'pendiente'}\n"
        f"*Ciudad:* {data['ciudad_origen'] or 'pendiente'}\n"
        f"*Correo:* {data['correo'] or 'pendiente'}\n"
        f"*Redes:* {data['redes'] or 'pendiente'}\n"
        f"*Productos:* {data['productos'] or 'pendiente'}\n"
        f"*Categoría:* {data['categoria'] or 'pendiente'}\n"
        f"*Archivos de productos:* {data['archivos_productos'] or 'No enviados'}\n"
        "\n"
        "¿Confirmas que puedo enviar tu preinscripción?"
    )


def available_stands_text():
    return admin_available_stands_text()


def sync_preinscription_field_to_memory(memory, step, value):
    if step == "legal_name":
        memory["brand"] = clean_preinscription_value(value)
    elif step == "city":
        memory["city"] = clean_preinscription_value(value)
    elif step == "products":
        memory["product"] = clean_preinscription_value(value)
    elif step == "category":
        memory["category"] = clean_preinscription_value(value)
    elif step == "preferred_stands":
        first_stand = extract_preferred_stands(value)
        if first_stand:
            memory["selected_stand"] = first_stand[0]


def clean_preinscription_value(value):
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    if normalize(cleaned) in {"no", "no tengo", "ninguno", "ninguna", "no aplica"}:
        return "No registra"
    return cleaned[:500]


def extract_preferred_stands(text):
    numbers = [int(item) for item in re.findall(r"\b\d{1,3}\b", str(text or ""))]
    output = []
    for number in numbers:
        if number not in output:
            output.append(number)
    return output[:2]


def validate_preferred_stands(stands):
    valid = []
    unavailable = []
    for stand in stands[:2]:
        booth = find_booth(stand)
        if booth and booth.get("status") == "available":
            valid.append(stand)
        else:
            unavailable.append(stand)
    return valid, unavailable


def says_no_files(text):
    return has_any(text, ["no tengo", "no por ahora", "no cuento", "no", "ninguno", "ninguna", "sin archivos"])


def is_done_with_files(text):
    return has_any(text, ["listo", "ya", "termine", "ya termine", "eso es todo", "enviado", "ya envie"])


def confirms_preinscription(text):
    confirmation_phrases = [
        "si confirmo",
        "confirmo",
        "todo esta correcto",
        "esta correcto",
        "correcto",
        "puedes enviarla",
        "puede enviarla",
        "enviala",
        "enviarla",
        "enviar",
    ]
    if text.strip() in {"si", "ok", "okay", "listo", "dale"}:
        return True
    return any(has_whole_phrase(text, phrase) for phrase in confirmation_phrases)


def wants_to_correct_preinscription(text):
    return any(
        has_whole_phrase(text, phrase)
        for phrase in ["corregir", "corrige", "cambiar", "editar", "modificar", "no esta correcto", "cambiar un dato"]
    )


def wants_to_cancel_preinscription(text):
    return has_any(text, ["cancelar preinscripcion", "detener preinscripcion", "salir preinscripcion", "no quiero seguir"])


def update_lead_memory_from_text(memory, raw_message, text, category=None):
    now = datetime.now(timezone.utc).isoformat()

    if category and (memory.get("role") == "expositor" or wants_to_participate(text) or has_any(text, ["marca", "producto", "stand"])):
        memory["category"] = category

    brand = detect_brand_name(raw_message)
    if brand:
        memory["brand"] = brand

    product = detect_product_description(raw_message)
    if product:
        memory["product"] = product

    if any([category, brand, product, wants_to_participate(text), memory.get("role") == "expositor"]):
        memory["lead_stage"] = lead_stage(memory)
        memory["updated_at"] = now


def detect_brand_name(message):
    value = str(message or "").strip()
    patterns = [
        r"(?:mi\s+)?marca\s+(?:se\s+llama|es|llamada)\s+(.+?)(?:,|\.|\s+y\s+|\s+que\s+|\s+dise(?:n|ñ)amos\s+|\s+producimos\s+|\s+vendemos\s+|$)",
        r"(?:empresa|emprendimiento)\s+(?:se\s+llama|es|llamada)\s+(.+?)(?:,|\.|\s+y\s+|\s+que\s+|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            brand = clean_detected_value(match.group(1))
            if brand:
                return brand
    return None


def detect_product_description(message):
    value = str(message or "").strip()
    patterns = [
        r"\b(?:producimos|vendemos|hacemos|ofrecemos|dise(?:n|ñ)amos)\s+(.+?)(?:,|\.|\s+y\s+mi\s+marca|\s+para\s+la\s+feria|$)",
        r"\b(?:son|serian|serian)\s+(.+?)(?:,|\.|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.IGNORECASE)
        if match:
            product = clean_detected_value(match.group(1))
            product = clean_product_prefix(product)
            if product and len(product.split()) <= 14:
                return product
    return None


def clean_product_prefix(product):
    if not product:
        return product
    cleaned = re.sub(
        r"^(?:y\s+)?(?:producimos|vendemos|hacemos|ofrecemos|disenamos|diseñamos)\s+",
        "",
        product,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or product


def clean_detected_value(value):
    cleaned = re.sub(r"\s+", " ", str(value or "").strip(" .,!¡?¿:;"))
    if not cleaned:
        return None
    return cleaned[:120]


def asks_private_stand_owner(text):
    return bool(
        re.search(r"\b(?:quien|quienes|marca)\s+(?:tiene|tienen|esta|ocupa|ocupan)\s+(?:el\s+)?stand\s*\d{1,3}\b", text)
    )


def privacy_stand_owner_reply():
    return (
        "Por privacidad no puedo compartir datos de otros expositores. "
        "Si quieres, puedo ayudarte a revisar disponibilidad general, precios o el proceso de preinscripción."
    )


def welcome_reply(memory):
    role_hint = ""
    if memory.get("role") == "expositor":
        role_hint = " Como expositor, puedo orientarte con stands, disponibilidad, medidas y pasos para participar."
    elif memory.get("role") == "visitante":
        role_hint = " Como visitante, puedo orientarte con fecha, ubicación, productos y actividades."

    if not memory.get("history"):
        return (
            "Hola, soy Ori Colombia, tu asistente virtual de Feria Origen Colombia.\n\n"
            "¡Qué alegría saludarte! Estoy aquí para ayudarte a conocer la feria y acompañarte si quieres hacer parte de ella.\n\n"
            "Puedo contarte sobre el evento, fechas, ubicación, productos, actividades, stands, precios y expositores internacionales.\n\n"
            "También puedo guiarte si deseas participar como expositor.\n\n"
            "¿Qué te gustaría saber primero: información de la feria, cómo llegar o cómo participar?"
        )

    return (
        "Hola, soy Ori Colombia!\n\n"
        "Qué bueno tenerte de vuelta. Puedo ayudarte con información de la feria, ubicación, productos, "
        "actividades, stands, precios, expositores internacionales o participación como expositor.\n\n"
        "¿Qué te gustaría revisar primero: información de la feria, cómo llegar o cómo participar?"
        f"{role_hint}"
    )


def consume_welcome_gallery_signal(user_id):
    memory = get_memory(user_id)
    if not memory.get("welcome_gallery_pending"):
        return False
    memory["welcome_gallery_pending"] = False
    save_persistent_state()
    return True


def event_reply():
    return (
        f"La {FAIR_INFO['name']} se realizará {FAIR_INFO['dates']} en la sede UNIBAC, "
        "en el Centro Histórico de Cartagena.\n\n"
        "Vas a encontrar arte, diseño, moda, joyería, gastronomía, artesanías, bienestar "
        "y marcas colombianas con propuestas muy especiales.\n\n"
        "¡La entrada para visitantes es 100% gratuita!\n\n"
        "¿Quieres que te cuente primero sobre productos, cómo llegar, actividades, imágenes de ferias anteriores "
        "o lugares cercanos?"
    )


def fair_history_reply():
    return (
        f"La web oficial confirma que Origen Colombia tiene {FAIR_INFO['experience_years']} "
        f"y {FAIR_INFO['total_fairs']}. No publica en el texto visible el año exacto de la primera feria, "
        "así que prefiero no inventarlo. Si necesitas ese dato exacto, puedo dejar clara la solicitud para el equipo."
    )


def metrics_reply():
    return (
        f"Según la web oficial, Origen Colombia cuenta con {FAIR_INFO['experience_years']}, "
        f"{FAIR_INFO['total_fairs']}, {FAIR_INFO['total_exhibitors']} y "
        f"{FAIR_INFO['visitors_per_event']}."
    )


def date_reply():
    return (
        f"La feria está programada {FAIR_INFO['dates']}. "
        "La agenda detallada puede ajustarse antes del evento; por ahora no tengo horarios exactos de actividades."
    )


def location_reply():
    return (
        "La feria se realiza en la sede UNIBAC, junto a la Plaza de San Diego, en el Centro Histórico de Cartagena.\n\n"
        f"Te dejo la ubicación en Google Maps:\n{FAIR_INFO['google_maps_url']}\n\n"
        "Si me dices desde qué zona sales, te oriento con una ruta más puntual."
    )


def entry_cost_reply():
    return (
        "¡Sí! La entrada para visitantes es 100% gratuita.\n\n"
        "Puedes venir a recorrer la feria, conocer marcas colombianas, descubrir productos únicos "
        "y disfrutar la experiencia sin pagar entrada."
    )


def arrival_and_cost_reply():
    return (
        f"{FAIR_INFO['location']} {FAIR_INFO['arrival_tip']} "
        "Si me dices desde dónde sales, te puedo orientar mejor con la ruta. "
        "Y si vienes como visitante, la entrada es 100% gratuita."
    )


def arrival_route_reply():
    return (
        "¡Claro! La feria se realiza en UNIBAC, junto a la Plaza de San Diego, en el Centro Histórico de Cartagena.\n\n"
        f"Ubicación en Google Maps:\n{FAIR_INFO['google_maps_url']}\n\n"
        "¿Desde dónde sales: Centro, Bocagrande, Getsemaní, Crespo, aeropuerto, terminal u otra zona?"
    )


def maps_link_reply():
    return (
        "¡Claro! Te comparto la ubicación en Google Maps:\n\n"
        f"{FAIR_INFO['google_maps_url']}\n\n"
        "La feria se realiza en la sede UNIBAC, junto a la Plaza de San Diego, en el Centro Histórico de Cartagena."
    )


def arrival_origin_reply(origin):
    if origin in {"cartagena", "centro", "ciudad_amurallada", "getsemani", "bocagrande", "crespo", "aeropuerto", "terminal"}:
        extras = {
            "cartagena": "Si ya estás en Cartagena,",
            "centro": "Si estás en el Centro Histórico,",
            "ciudad_amurallada": "Si estás dentro de la Ciudad Amurallada,",
            "getsemani": "Si estás en Getsemaní,",
            "bocagrande": "Si sales desde Bocagrande,",
            "crespo": "Si estás en Crespo,",
            "aeropuerto": "Si vienes desde el aeropuerto,",
            "terminal": "Si vienes desde la terminal,",
        }
        return (
            f"¡Perfecto! {extras[origin]} puedes usar esta ubicación en Google Maps:\n\n"
            f"{FAIR_INFO['google_maps_url']}\n\n"
            "En taxi o Uber puedes pedir que te lleven a Plaza de San Diego o UNIBAC Bellas Artes. "
            "Como referencia, queda cerca del Hotel Sofitel Santa Clara, en el sector San Diego del Centro Histórico."
        )

    return (
        "¡Claro! Si vienes desde otra ciudad, lo más práctico es llegar primero a Cartagena y luego abrir esta ubicación:\n\n"
        f"{FAIR_INFO['google_maps_url']}\n\n"
        "La feria queda en el Claustro de San Diego / UNIBAC, "
        "en pleno Centro Histórico."
    )


def plan_reply():
    return (
        "Claro, con mucho gusto te comparto el plano actual de la feria. "
        "Ahí podrás ubicar los stands disponibles y los que ya aparecen ocupados. "
        "Si quieres revisar un stand puntual, dime el número."
    )


def nearby_reply():
    return (
        "Cerca de la feria tienes varios puntos bonitos para complementar la visita.\n\n"
        f"{FAIR_INFO['nearby_places']}\n\n"
        "¿Quieres recomendaciones para comer, hospedarte o caminar cerca de la sede?"
    )


def venue_reply(text):
    if has_any(text, ["patio", "patio de las artes"]):
        return FAIR_INFO["exhibition_spaces"]["patio"]

    if has_any(text, ["salon", "pierre", "daguet"]):
        return FAIR_INFO["exhibition_spaces"]["salon"]

    return (
        f"{FAIR_INFO['venue_history']} {FAIR_INFO['venue_context']} "
        f"Espacios de exposición: {FAIR_INFO['exhibition_spaces']['patio']} "
        f"{FAIR_INFO['exhibition_spaces']['salon']}"
    )


def visitor_guide_reply():
    return (
        f"Perfecto. Como visitante vas a encontrar {FAIR_INFO['products']} "
        f"También habrá {FAIR_INFO['activities']} "
        f"La galería oficial destaca: {FAIR_INFO['gallery_sections']} "
        "Si quieres hacerte una idea del ambiente, también puedo compartirte fotos de ferias anteriores. "
        "Puedes preguntarme por fecha, ubicación, actividades, productos o espacios de la sede."
    )


def previous_fairs_reply():
    return (
        "¡Claro! Te comparto algunas imágenes para que puedas hacerte una idea del ambiente de la feria.\n\n"
        "Vas a ver espacios pensados para recorrer, descubrir marcas colombianas y vivir una experiencia cercana con el talento local."
    )


def exhibitor_guide_reply():
    return participation_overview_reply()


def participation_overview_reply(memory=None):
    if memory is not None:
        memory["last_intent"] = "exhibitor"
        memory["last_offer"] = "participation_next_step"
        memory["pending_field"] = None
        memory["process_stage"] = "interesado_en_participar"
        memory["lead_stage"] = memory.get("lead_stage") or "interesado"
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_persistent_state()

    return (
        "¡Qué buena noticia! Puedes participar como expositor realizando la preinscripción directamente por aquí.\n\n"
        "Los stands tienen valores entre $3.300.000 y $6.000.000 COP, según zona, medida y tipo de stand.\n\n"
        "¿Empezamos el proceso de preinscripción o quieres ver el plano de ubicación?"
    )


def category_followup_reply(category):
    return (
        f"¡Perfecto! {category} aplica para la feria. Me alegra que ya tengamos clara la categoría. "
        "Si quieres avanzar, puedo tomar tu preinscripción directamente por este chat. "
        "Recuerda que el stand o ubicación queda sujeto a confirmación del equipo organizador."
    )


def product_detail_followup_reply(memory):
    category = memory.get("category") or "la categoría que venimos revisando"
    if memory.get("form_submitted"):
        return (
            f"¡Qué bonito proyecto! Ya tengo claro que va por {category}.\n\n"
            "Como ya reportaste que enviaste la preinscripción, el equipo revisará tu solicitud "
            "y se comunicará contigo para confirmar disponibilidad, inscripción y métodos de pago."
        )
    return (
        f"¡Qué bonito proyecto! Ya tengo claro que va por {category}. "
        "Si ya quieres avanzar, puedo tomar tu preinscripción directamente por este chat. "
        "Si prefieres, también revisamos primero stands disponibles."
    )


def reservation_reply(memory):
    selected_stand = memory.get("selected_stand")
    selected_status = memory.get("selected_stand_status")
    blocked_stand = memory.get("blocked_stand")
    blocked_status = STATUS_LABELS.get(memory.get("blocked_stand_status"), "no disponible")

    if selected_stand and selected_status == "available":
        return (
            f"¡Me alegra que te hayas animado a reservar! Esta es una oportunidad única para darle visibilidad a tu marca. "
            "Puedo tomar tu preinscripción directamente por este chat. "
            f"Recordemos que el stand {selected_stand} aparece disponible por ahora, "
            "pero el número queda sujeto a confirmación final por parte de los organizadores."
        )

    if blocked_stand:
        return (
            f"Te entiendo, pero el stand {blocked_stand} aparece {blocked_status}, así que no debo guiarte a reservarlo. "
            "Dime otro número disponible y te acompaño con el proceso."
        )

    return (
        "¡Claro! Me alegra que quieras avanzar con tu reserva o preinscripción. "
        "Puedo tomar tus datos directamente por este chat. "
        "El número del stand queda sujeto a confirmación final por parte de los organizadores."
    )


def registration_link_reply(memory):
    if memory.get("form_submitted"):
        return form_submitted_reply()
    category = memory.get("category")
    category_note = f" Ya tengo presente tu categoría: {category}." if category else ""
    return (
        "¡Me alegra que te hayas decidido a participar! Feria Origen Colombia 2027 es una oportunidad única "
        "para mostrar tu marca, conectar con visitantes y hacer parte de una experiencia con identidad colombiana. "
        "Puedo tomar tu preinscripción directamente por este chat. "
        "Recuerda que la disponibilidad del stand o ubicación queda sujeta a confirmación del equipo organizador."
        f"{category_note}"
    )


def form_submitted_reply():
    return (
        "¡Qué buena noticia! Ya diste el primer paso para hacer parte de Feria Origen Colombia 2027.\n\n"
        "El equipo revisará tu preinscripción y se comunicará contigo para confirmar disponibilidad, inscripción y métodos de pago.\n\n"
        "Estoy aquí si quieres revisar ubicación, stands, fechas o cualquier otra información de la feria."
    )


def submitted_reservation_reply(memory):
    selected_stand = memory.get("selected_stand")
    stand_note = ""
    if selected_stand:
        stand_note = (
            f"\n\nTengo presente tu interés por el stand {selected_stand}. "
            "Recuerda que el número del stand queda sujeto a confirmación final por parte del equipo organizador."
        )
    return (
        "¡Perfecto! Como ya enviaste la preinscripción, no necesitas volver a llenar el formulario.\n\n"
        "El equipo revisará tu solicitud y se comunicará contigo para confirmar disponibilidad, inscripción y métodos de pago."
        f"{stand_note}"
    )


def preinscription_status_reply():
    return (
        "¡Con gusto! Después de enviar tu preinscripción, el equipo revisará tu solicitud y se comunicará contigo "
        "para confirmar disponibilidad, inscripción y métodos de pago.\n\n"
        "Por ahora no tengo un tiempo exacto oficial. "
        "Te recomiendo estar pendiente del WhatsApp o correo que dejaste en el formulario."
    )


def thanks_reply(memory):
    if memory.get("form_submitted"):
        return (
            "¡Con mucho gusto! El equipo revisará tu preinscripción y se comunicará contigo para confirmar "
            "disponibilidad, inscripción y métodos de pago.\n\n"
            "Estoy aquí si quieres revisar stands, ubicación o cualquier detalle de la feria."
        )

    if memory.get("registration_link_sent_at") or memory.get("process_stage") == "link_preinscripcion_enviado":
        return (
            "¡Con mucho gusto! Cuando completes la preinscripción, el equipo revisará tu solicitud y se comunicará contigo "
            "para confirmar disponibilidad, inscripción y métodos de pago.\n\n"
            "Estoy aquí si quieres revisar stands, precios o ubicación."
        )

    if memory.get("last_intent") in {"booths", "plan", "prices", "stand_includes"} or memory.get("selected_stand"):
        return "¡Con mucho gusto! Si quieres revisar otro stand, precios, medidas o el plano, aquí estoy para ayudarte."

    if memory.get("role") == "visitante":
        return "¡Con mucho gusto! Estoy aquí si quieres revisar ubicación, fecha, actividades o productos de la feria."

    return "Con gusto. Soy Ori y estoy aquí para ayudarte con la feria cuando lo necesites."


def exhibitor_city_reply(memory, city):
    selected_stand = memory.get("selected_stand")
    selected_note = f" y el stand {selected_stand}" if selected_stand else ""
    return (
        f"Perfecto, gracias por contarme que vienes de {city}. "
        f"Lo tengo presente para tu proceso de preinscripción{selected_note}.\n\n"
        "Si ya quieres avanzar, puedo tomar tu preinscripción directamente por este chat.\n\n"
        "¿Necesitas ayuda con algo más?"
    )


def suggestions_reply(memory):
    if memory.get("role") == "expositor":
        return (
            "Puedes preguntarme cosas como: qué stands están disponibles, cuánto mide el stand 21, "
            "qué categorías acepta la feria, qué datos debo enviar para participar o cómo es la sede."
        )

    return (
        "Puedes preguntarme cosas como: dónde es la feria, cuándo se realiza, qué productos encontraré, "
        "qué actividades habrá, cómo es el Convento de San Diego, cómo participar como expositor o qué stands están disponibles."
    )


def products_reply(text):
    if has_any(text, ["categoria", "categorias", "acepta"]):
        return f"Las categorías oficiales de inscripción son: {FAIR_INFO['registration_categories']}"

    category = detect_product_category(text)
    if category:
        category_notes = {
            "Joyería": "piezas artesanales, accesorios, diseños hechos a mano y propuestas con identidad colombiana.",
            "Gastronomía": "sabores locales, productos especiales, café, dulces, bebidas y propuestas para disfrutar durante el recorrido.",
            "Calzado y vestuario": "moda, ropa, calzado, bolsos y accesorios de marcas colombianas con estilo propio.",
            "Decoración": "piezas para el hogar, objetos decorativos y propuestas con diseño local.",
            "Anticuarios": "piezas con historia, objetos especiales y propuestas para quienes disfrutan lo auténtico.",
            "Salud y belleza": "bienestar, cuidado personal, belleza y productos pensados para consentirte.",
            "Artesanía típica": "oficios hechos a mano, piezas tradicionales y creaciones con mucha identidad regional.",
            "Arte": "obras, ilustración, pintura, escultura y propuestas creativas de talento colombiano.",
        }
        return (
            f"¡Qué buena elección! En {category.lower()} podrás encontrar {category_notes.get(category, 'propuestas colombianas con identidad y mucho cuidado en los detalles')}\n\n"
            "Aún no tengo la lista oficial completa de marcas confirmadas para esta edición, "
            "pero si quieres puedo orientarte por categorías o mostrarte imágenes de ferias anteriores."
        )

    return (
        "Encontrarás productos colombianos con mucha identidad: artesanías, joyería, moda, accesorios, gastronomía, "
        "decoración, bienestar, arte y diseño.\n\n"
        "También hay piezas hechas a mano, propuestas locales y artículos inspirados en la cultura colombiana.\n\n"
        "¿Te interesa alguna categoría en especial: gastronomía, joyería, moda o artesanías?"
    )


def confirmed_exhibitors_reply():
    return (
        "Aún no tengo la lista oficial completa de marcas confirmadas para esta edición.\n\n"
        f"Lo que sí puedo contarte es que la feria reúne propuestas de {FAIR_INFO['products']}\n\n"
        "¿Quieres que te hable de alguna categoría en especial, como moda, joyería, gastronomía o artesanías?"
    )


def activities_reply():
    return (
        f"La feria tendrá {FAIR_INFO['activities']} "
        "La programación detallada todavía debe confirmarse, así que por ahora no tengo horas exactas."
    )


def prices_reply(memory, text=""):
    stand_number = extract_stand_number(text) or memory.get("selected_stand")
    if stand_number:
        stand = find_booth(stand_number)
        price = STAND_PRICES.get(stand_number)
        if not stand or not price:
            return (
                f"Aún no tengo precio confirmado para el stand {stand_number}. "
                "Si quieres, puedo mostrarte los stands disponibles con precio."
            )

        status = STATUS_LABELS[stand["status"]]
        zone = ZONE_LABELS[stand["zone"]]
        status_note = ""
        if stand["status"] == "reserved":
            status_note = " Ojo: aparece reservado, así que no debo ofrecerlo como disponible."
        elif stand["status"] == "unavailable":
            status_note = " Ojo: aparece no disponible, así que no debo ofrecerlo como opción."

        return (
            f"Stand {stand_number}: {status}.\n\n"
            f"Zona: {zone}\n"
            f"Medidas: {price['size']}\n"
            f"Tipo: {price['type']}\n"
            f"Precio: {price['price']}{status_note}\n\n"
            "La asignación final queda sujeta a confirmación del equipo organizador."
        )

    if memory.get("role") == "expositor" or memory.get("last_intent") in {"booths", "exhibitor"}:
        memory["last_offer"] = "plan_after_prices"
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_persistent_state()
        return (
            "Claro. Los stands van desde $3.300.000 hasta $6.000.000 COP, según ubicación, medida y tipo.\n\n"
            "Patio de las Artes: desde $3.300.000 COP.\n"
            "Salón Pierre Daguet: desde $5.000.000 COP.\n\n"
            "¿Quieres que te comparta el plano de ubicaciones?"
        )

    memory["last_offer"] = "plan_after_prices"
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_persistent_state()
    return (
        "Claro. Los stands van desde $3.300.000 hasta $6.000.000 COP, según ubicación, medida y tipo.\n\n"
        "Patio de las Artes: desde $3.300.000 COP.\n"
        "Salón Pierre Daguet: desde $5.000.000 COP.\n\n"
        "¿Quieres que te comparta el plano de ubicaciones?"
    )


def ambiguous_value_reply():
    return (
        "¡Hola! Si te refieres a la entrada para visitar la feria, es 100% gratuita.\n\n"
        "Si quieres participar como expositor, los stands tienen valores entre $3.300.000 y $6.000.000 COP, según zona, medida y tipo.\n\n"
        "¿Quieres venir como visitante o estás pensando en participar con tu marca?"
    )


def stand_includes_reply(number=None):
    if number:
        stand = find_booth(number)
        if not stand:
            return (
                f"No encuentro el stand {number} en el plano actual. "
                f"En general, {lower_first(FAIR_INFO['stand_includes'])}"
            )

        zone = ZONE_LABELS[stand["zone"]]
        status = STATUS_LABELS.get(stand["status"], stand["status"])
        price = STAND_PRICES.get(number)
        booth_type = price["type"] if price else "tipo por confirmar"
        price_line = f"\nPrecio: {price['price']}." if price else ""
        walls = "2 muros blancos" if is_corner_stand(number) else "3 muros blancos"
        return (
            f"El stand {number} incluye {walls}, 1 mesa de 120 x 60 cm y 1 estante con 2 puestos de 180 cm.\n\n"
            f"Zona: {zone}.\n"
            f"Medidas: {stand['size']}.\n"
            f"Tipo: {booth_type}.\n"
            f"Estado: {status}."
            f"{price_line}"
        )

    return (
        "Todos los stands incluyen 3 muros blancos, excepto los esquineros que incluyen 2 muros blancos. "
        "También incluyen 1 mesa de 120 x 60 cm y 1 estante con 2 puestos de 180 cm."
    )


def advisor_reply(memory=None):
    memory = memory or {}
    blocked_stand = memory.get("blocked_stand")
    selected_stand = memory.get("selected_stand")
    submitted_note = ""
    if memory.get("form_submitted"):
        submitted_note = (
            " Mientras tanto, te recomiendo estar pendiente del WhatsApp o correo que dejaste en el formulario."
        )

    if blocked_stand:
        blocked_status = STATUS_LABELS.get(memory.get("blocked_stand_status"), "no disponible")
        if selected_stand:
            return (
                f"{FAIR_INFO['human_help']} "
                f"Eso sí: el stand {blocked_stand} aparece {blocked_status}, "
                f"así que no debo tomarlo como disponible. Podemos seguir con el stand {selected_stand} "
                f"o revisar otra opción disponible.{submitted_note}"
            )
        return (
            f"{FAIR_INFO['human_help']} "
            f"Eso sí: el stand {blocked_stand} aparece {blocked_status}, "
            f"así que no debo tomarlo como disponible. Podemos revisar otra opción disponible.{submitted_note}"
        )

    return f"{FAIR_INFO['human_help']}{submitted_note}"


def smart_fallback_reply(message, memory):
    if looks_like_lead(message):
        memory["last_intent"] = "lead"
        return (
            "Gracias, ya tengo una parte de tu información. Para que el equipo pueda revisarla mejor, envía en un solo mensaje: "
            "nombre, marca, producto, ciudad y stand de interés si ya lo tienes."
        )

    if memory.get("last_intent") == "booths":
        return (
            "Sigo contigo en el tema de stands. Puedes escribirme un número, por ejemplo 'stand 21', "
            "o escribir 'stands disponibles' para ver las opciones."
        )

    if memory.get("role") == "expositor":
        return (
            "Creo que tu consulta va por el lado de participación como expositor. "
            "Puedo ayudarte con stands disponibles, medidas y zonas. "
            "Si quieres avanzar, también puedo tomar tu preinscripción directamente por aquí."
        )

    return (
        "Te entiendo. Puedo orientarte sobre evento, fecha, ubicación, productos, actividades y stands. "
        "Pregúntame como lo dirías normalmente, por ejemplo: 'dónde es', 'qué productos encontraré' o 'quiero participar con mi marca'."
    )


def describe_stand(number, memory=None):
    memory = memory or {}
    stand = find_booth(number)
    if not stand:
        return (
            f"No encuentro el stand {number} en el plano actual. "
            "Puedo mostrarte los stands disponibles para revisar una alternativa."
        )

    zone = ZONE_LABELS[stand["zone"]]
    price_text = stand_price_text(number)
    if stand["status"] == "available":
        price = STAND_PRICES.get(stand["number"])
        type_line = f"Tipo: {price['type']}." if price else ""
        price_line = f"Precio: {price['price']}." if price else ""
        if memory.get("form_submitted"):
            return (
                f"¡Perfecto! El stand {stand['number']} está disponible en {zone}.\n\n"
                f"Medidas: {stand['size']}.\n"
                f"{type_line}\n"
                f"{price_line}\n\n"
                "Como ya enviaste el formulario, el equipo revisará tu solicitud y confirmará disponibilidad, "
                "inscripción y métodos de pago.\n\n"
                "¿Necesitas ayuda con algo más?"
            )
        return (
            f"¡Genial elección! El stand {stand['number']} está disponible en {zone}.\n\n"
            f"Medidas: {stand['size']}.\n"
            f"{type_line}\n"
            f"{price_line}\n\n"
            "Si te interesa avanzar, puedo tomar tu preinscripción directamente por este chat.\n\n"
            "El número del stand queda sujeto a confirmación final por parte de los organizadores. "
            "Una vez envíes la preinscripción, el equipo revisará tu solicitud y se pondrá en contacto contigo para confirmar inscripción y métodos de pago.\n\n"
            "¿Necesitas ayuda con algo más?"
        )

    if stand["status"] == "reserved":
        return (
            f"Disculpa, el stand {stand['number']} ya está reservado para otro expositor. "
            f"Zona: {zone}. Medidas: {stand['size']}.{price_text} "
            "No debo tomarlo como disponible, pero puedo sugerirte otro. ¿Qué otro te interesa?"
        )

    return (
        f"Disculpa, el stand {stand['number']} aparece no disponible. "
        f"Zona: {zone}. Medidas: {stand['size']}.{price_text} "
        "No debo ofrecerlo como opción, pero puedo ayudarte a revisar alternativas disponibles."
    )


def available_stands_reply():
    patio = sorted(
        item["number"] for item in iter_booths() if item["status"] == "available" and item["zone"] == "patio"
    )
    salon = sorted(
        item["number"] for item in iter_booths() if item["status"] == "available" and item["zone"] == "salon"
    )

    return (
        "Claro, te comparto el plano actual y estos son los stands disponibles por ahora:\n"
        f"Patio de las Artes: {', '.join(str(item) for item in patio)}.\n"
        f"Salón Pierre Daguet: {', '.join(str(item) for item in salon)}.\n"
        "Si quieres detalle de uno, escríbeme por ejemplo: stand 21."
    )


def stand_type_followup_reply(stand_type):
    return (
        f"Entendido, buscas un stand {stand_type}. "
        "Para recomendarte opciones reales, dime en qué zona prefieres ubicarte: Patio de las Artes o Salón Pierre Daguet."
    )


def matching_stands_reply(stand_type, zone, memory=None):
    matches = []
    for number, price in sorted(STAND_PRICES.items()):
        stand = find_booth(number)
        if not stand or stand["zone"] != zone or stand["status"] != "available":
            continue
        if stand_type not in normalize(price["type"]):
            continue
        matches.append((number, price))

    zone_name = ZONE_LABELS.get(zone, zone)
    if not matches:
        return (
            f"En {zone_name} no veo stands {stand_type} disponibles por ahora. "
            "Puedo sugerirte otra zona o revisar stands especiales/generales disponibles."
        )

    if memory is not None:
        memory["last_suggested_stand"] = matches[0][0]
        memory["last_intent"] = "booths"
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()

    options = ", ".join(f"{number} ({price['price']})" for number, price in matches[:8])
    return (
        f"En {zone_name}, estos stands {stand_type} aparecen disponibles: {options}. "
        "Si alguno te llama la atención, dime el número y revisamos el detalle."
    )


def stand_recommendation_reply(memory):
    zone = recommendation_zone(memory)
    if not zone:
        return (
            "¡Claro! Para recomendarte mejor, dime en qué zona prefieres ubicarte: "
            "Patio de las Artes o Salón Pierre Daguet."
        )

    options = recommended_stands_for_zone(zone, memory.get("desired_stand_type"))
    zone_name = ZONE_LABELS.get(zone, zone)
    if not options:
        return (
            f"En {zone_name} no veo opciones disponibles con ese filtro por ahora. "
            "Puedo revisar otra zona o mostrarte todos los stands disponibles."
        )

    memory["last_suggested_stand"] = options[0]["number"]
    memory["desired_zone"] = zone
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()

    intro = f"Como el stand {memory.get('blocked_stand')} no está disponible, " if memory.get("blocked_stand") else ""
    lines = [
        f"{intro}te recomiendo mirar estas opciones en {zone_name}:",
        "",
    ]
    for option in options[:3]:
        price = STAND_PRICES.get(option["number"], {})
        type_text = price.get("type", "tipo por confirmar")
        price_text = price.get("price", "precio por confirmar")
        lines.append(f"- Stand {option['number']}: {type_text}, {option['size']}, {price_text}.")

    lines.append("")
    lines.append(f"Si quieres, empezamos revisando el stand {options[0]['number']}.")
    return "\n".join(lines)


def recommendation_zone(memory):
    for key in ("desired_zone",):
        if memory.get(key):
            return memory[key]

    for stand_key in ("blocked_stand", "selected_stand", "last_suggested_stand"):
        number = memory.get(stand_key)
        if number:
            stand = find_booth(number)
            if stand:
                return stand["zone"]
    return None


def recommended_stands_for_zone(zone, stand_type=None):
    options = []
    for stand in iter_booths():
        if stand["zone"] != zone or stand["status"] != "available":
            continue
        price = STAND_PRICES.get(stand["number"], {})
        if stand_type and stand_type not in normalize(price.get("type", "")):
            continue
        options.append(stand)

    return sorted(options, key=lambda item: (recommendation_score(item["number"]), item["number"]))


def recommendation_score(number):
    price = STAND_PRICES.get(number, {})
    type_text = normalize(price.get("type", ""))
    if "esquinero premium" in type_text or "delux" in type_text:
        return 0
    if "esquinero" in type_text or "esquina" in type_text:
        return 1
    if "especial" in type_text:
        return 2
    return 3


def remember_stand_interest(memory, number):
    stand = find_booth(number)
    if not stand:
        memory["blocked_stand"] = number
        memory["blocked_stand_status"] = "unavailable"
        memory["lead_stage"] = lead_stage(memory)
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        return

    if stand["status"] == "available":
        memory["selected_stand"] = number
        memory["selected_stand_status"] = "available"
        memory["last_suggested_stand"] = number
        memory["blocked_stand"] = None
        memory["blocked_stand_status"] = None
        memory["lead_stage"] = "preinscrito" if memory.get("form_submitted") else "interesado"
        if not memory.get("form_submitted"):
            memory["process_stage"] = "interesado_en_stand"
        memory["updated_at"] = datetime.now(timezone.utc).isoformat()
        return

    memory["blocked_stand"] = number
    memory["blocked_stand_status"] = stand["status"]
    memory["lead_stage"] = lead_stage(memory)
    memory["updated_at"] = datetime.now(timezone.utc).isoformat()


def detect_intent(text, memory):
    if asks_confirmed_exhibitors(text):
        return "confirmed_exhibitors"

    if wants_to_participate(text):
        return "exhibitor"

    if asks_for_arrival(text):
        return "location"

    if asks_entry_cost(text):
        return "entry_cost"

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
        bool(re.search(r"\b(?:stand|stan|estan|puesto)\s*\d{1,3}\b", text))
        or has_any(text, [
            "prefiero",
            "mejor",
            "reservado",
            "disponible",
            "no disponible",
            "me interesa el",
            "interesado en el",
            "quiero el",
            "elegir el",
            "escoger el",
            "me gustaria elegir",
            "me gustaria escoger",
        ])
        or memory.get("last_intent") in {"booths", "exhibitor", "plan"}
        or memory.get("role") == "expositor"
    )


def should_follow_stand_filters(memory):
    return memory.get("last_intent") in {"booths", "plan", "exhibitor"} or memory.get("role") == "expositor"


def asks_stand_includes(text):
    return has_any(
        text,
        [
            "que incluye",
            "que trae",
            "incluye el stand",
            "incluye un stand",
            "viene con",
            "mobiliario",
            "muros",
            "mesa",
            "estante",
        ],
    )


def detect_stand_type(text):
    if has_any(text, ["esquinero", "esquina"]):
        return "esquinero"
    if has_any(text, ["especial"]):
        return "especial"
    if has_any(text, ["general"]):
        return "general"
    if has_any(text, ["premium", "premiun"]):
        return "premium"
    if has_any(text, ["delux", "deluxe"]):
        return "delux"
    return None


def is_corner_stand(number):
    price = STAND_PRICES.get(number)
    if not price:
        return False
    return has_any(normalize(price["type"]), ["esquina", "esquinero"])


def detect_zone_preference(text):
    if has_any(text, ["salon pierre daguet", "pierre daguet", "salon"]):
        return "salon"
    if has_any(text, ["patio de las artes", "patio"]):
        return "patio"
    return None


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


def asks_to_change_topic(text):
    return has_any(
        text,
        [
            "cambiemos de tema",
            "cambiar de tema",
            "dejemos ese tema",
            "otro tema",
            "ahora quiero",
            "pasemos a",
        ],
    )


def reset_topic_memory(memory):
    memory["pending_field"] = None
    memory["last_offer"] = None
    memory["desired_stand_type"] = None
    memory["desired_zone"] = None


def clear_arrival_context(memory):
    if memory.get("last_intent") in {"arrival", "arrival_cost", "maps_link", "location"}:
        memory["pending_field"] = None
        memory["last_offer"] = None


def is_affirmative_followup(text, memory):
    if memory.get("last_offer") != "maps_link":
        return False
    return has_any(
        text,
        [
            "si",
            "claro",
            "por favor",
            "seria maravilloso",
            "seria excelente",
            "dale",
            "enviala",
            "enviamela",
            "mandala",
            "mandamela",
            "gracias",
        ],
    )


def handle_affirmative_followup(memory):
    if memory.get("last_offer") == "maps_link":
        memory["last_offer"] = None
        memory["pending_field"] = None
        memory["last_intent"] = "maps_link"
        return maps_link_reply()
    return "¡Claro! Con gusto."


def wants_plan_after_prices_offer(text, memory):
    if memory.get("last_offer") != "plan_after_prices":
        return False
    return has_any(
        text,
        [
            "si",
            "claro",
            "por favor",
            "dale",
            "enviamelo",
            "enviame",
            "mandamelo",
            "mandame",
            "plano",
            "ubicacion",
            "ubicaciones",
            "quiero verlo",
            "verlo",
        ],
    )


def wants_to_start_preinscription_after_offer(text, memory):
    if memory.get("last_offer") != "participation_next_step":
        return False
    if asks_for_plan(text):
        return False
    return has_any(
        text,
        [
            "empecemos",
            "empezamos",
            "iniciemos",
            "iniciar",
            "inicia",
            "arranquemos",
            "comencemos",
            "preinscripcion",
            "pre inscripcion",
            "hacer preinscripcion",
            "quiero preinscribirme",
            "quiero inscribirme",
            "si",
            "dale",
        ],
    )


def is_greeting_text(text):
    return has_any(
        text,
        [
            "hola",
            "buenas",
            "buen dia",
            "buenos dias",
            "buenas tardes",
            "buenas noches",
            "menu",
            "ayuda",
            "inicio",
        ],
    )


def wants_to_participate(text):
    if asks_confirmed_exhibitors(text):
        return False

    return has_any(
        text,
        [
            "soy expositor",
            "quiero exponer",
            "quiero vender",
            "quiero participar",
            "como puedo participar",
            "estoy interesado en participar",
            "interesado en participar",
            "tengo una marca",
            "tengo un emprendimiento",
            "quiero un stand",
            "quiero un stan",
            "quiero un estan",
            "reservar un stand",
            "reservar un stan",
            "reservar un estan",
            "separar un stand",
            "separar un stan",
            "separar un estan",
            "quiero reservar",
            "preinscripcion",
            "pre inscripcion",
            "inscribirme como expositor",
        ],
    )


def asks_confirmed_exhibitors(text):
    return has_any(
        text,
        [
            "quienes participan",
            "quienes participaran",
            "quien participa",
            "quien participara",
            "que marcas participan",
            "que marcas participaran",
            "que marcas hay",
            "marcas confirmadas",
            "expositores confirmados",
            "que expositores hay",
            "quienes estaran",
            "quienes vienen",
            "quienes van a estar",
            "quienes van a participar",
        ],
    )


def should_treat_category_as_visitor_product(text, memory):
    if memory.get("pending_field"):
        return False
    if memory.get("role") == "expositor":
        return False
    if wants_to_participate(text):
        return False
    if has_any(text, ["marca", "emprendimiento", "stand", "stands", "inscribir", "inscripcion", "preinscripcion", "vender", "exponer"]):
        return False
    if memory.get("last_intent") in {"products", "event", "visitor", "confirmed_exhibitors", "previous_fairs"}:
        return True
    return len(text.split()) <= 5


def wants_registration_link(text):
    return has_any(
        text,
        [
            "quiero inscribirme",
            "quiero preinscribirme",
            "me quiero inscribir",
            "me quiero preinscribir",
            "como me inscribo",
            "como hago para inscribirme",
            "como hago la preinscripcion",
            "como hago para preinscribirme",
            "mandame el formulario",
            "enviame el formulario",
            "comparteme el formulario",
            "link de inscripcion",
            "link de preinscripcion",
            "formulario de inscripcion",
            "formulario de preinscripcion",
            "quiero llenar el formulario",
        ],
    )


def has_submitted_form(text, memory=None):
    direct = has_any(
        text,
        [
            "ya me registre",
            "ya me registr",
            "ya me registre en el formulario",
            "ya me registre en la pagina",
            "ya me registre en la web",
            "me registre",
            "me registr",
            "ya estoy registrado",
            "ya estoy preinscrito",
            "ya llene el formulario",
            "ya lo llene",
            "ya lo envie",
            "ya lo mande",
            "ya esta lleno",
            "ya llene la preinscripcion",
            "ya diligencie el formulario",
            "ya complete el formulario",
            "ya complete el registro",
            "ya envie el formulario",
            "ya envie la preinscripcion",
            "ya mande el formulario",
            "ya me inscribi",
            "ya me preinscribi",
            "formulario enviado",
            "preinscripcion enviada",
            "inscripcion enviada",
            "listo ya llene",
            "listo ya lo llene",
            "listo ya envie",
            "listo ya lo envie",
        ],
    )
    if direct:
        return True

    if not memory:
        return False

    contextual_reply = has_any(
        text,
        [
            "ya lo hice",
            "ya hice",
            "ya lo complete",
            "ya complete",
            "ya quedo",
            "listo ya",
            "listo ya lo hice",
            "listo ya hice",
        ],
    )
    if not contextual_reply:
        return False

    return bool(
        memory.get("registration_link_sent_at")
        or memory.get("pending_field") == "registration"
        or memory.get("selected_stand")
        or memory.get("last_intent") in {"registration_link", "reservation", "registration_category", "product_detail"}
        or memory.get("process_stage") in {"link_preinscripcion_enviado", "interesado_en_stand"}
    )


def likes_suggested_stand(text, memory):
    if not memory.get("last_suggested_stand"):
        return False
    return has_any(
        text,
        [
            "me gusta ese",
            "me gusta este",
            "quiero ese",
            "quiero este",
            "me quedo con ese",
            "me quedo con este",
            "ese me gusta",
            "este me gusta",
            "ese esta bien",
            "este esta bien",
            "voy con ese",
            "vamos con ese",
        ],
    )


def is_contextual_thanks(text):
    return has_any(text, ["gracias", "listo gracias", "ok gracias", "perfecto gracias", "muchas gracias"])


def asks_for_stand_recommendation(text, memory=None):
    if not has_any(
        text,
        [
            "cual me recomienda",
            "cual recomiendas",
            "que me recomienda",
            "que recomiendas",
            "recomiendame",
            "recomienda",
            "que opcion me sugieres",
            "que opciones me sugieres",
            "que alternativa",
            "alternativas disponibles",
            "opciones disponibles",
            "cual seria mejor",
            "cual es mejor",
        ],
    ):
        return False

    if has_any(text, ["hotel", "restaurante", "comer", "turismo", "llegar", "ruta", "ubicacion"]):
        return False

    if has_any(text, ["stand", "stands", "stan", "estan", "puesto", "puestos"]):
        return True

    memory = memory or {}
    return bool(
        memory.get("role") == "expositor"
        or memory.get("blocked_stand")
        or memory.get("selected_stand")
        or memory.get("last_intent") in {"booths", "prices", "stand_includes", "reservation"}
    )


def asks_preinscription_status(text):
    return has_any(
        text,
        [
            "en cuanto tiempo me dan respuesta",
            "en cuanto tiempo tendria respuesta",
            "en cuanto tiempo tendre respuesta",
            "cuanto tiempo me dan respuesta",
            "cuanto tiempo tendria respuesta",
            "cuanto tiempo tendre respuesta",
            "cuando me dan respuesta",
            "cuando me responden",
            "cuando tendria respuesta",
            "cuando tendre respuesta",
            "cuanto se demoran",
            "cuanto tarda",
            "tiempo de respuesta",
            "tendria respuesta",
            "tendre respuesta",
            "me dan respuesta",
            "respuesta de mi preinscripcion",
            "respuesta de la preinscripcion",
            "cuando me contactan",
            "cuando se comunican",
            "que sigue con mi preinscripcion",
            "que pasa despues de la preinscripcion",
            "despues de enviar el formulario",
            "despues de llenar el formulario",
        ],
    )


def wants_to_reserve(text):
    return has_any(
        text,
        [
            "como hago la reserva",
            "como hago para reservar",
            "como hago para reserva",
            "como reservo",
            "quiero reservar",
            "quiero separarlo",
            "quiero separar",
            "reservar ese stand",
            "reservar este stand",
            "reservar el stand",
            "separar ese stand",
            "separar este stand",
            "separar el stand",
            "hacer la reserva",
            "proceso de reserva",
        ],
    )


def asks_for_plan(text):
    return has_any(
        text,
        [
            "plano",
            "plano de la feria",
            "plano del evento",
            "plano del envento",
            "plano de stands",
            "mapa de la feria",
            "mapa de stands",
            "compartir el plano",
            "comparteme el plano",
            "compartirme el plano",
            "ver el plano",
            "ver plano",
        ],
    )


def asks_for_fair_images(text):
    return has_any(
        text,
        [
            "imagenes de la feria",
            "imagen de la feria",
            "fotos de la feria",
            "foto de la feria",
            "quiero ver imagenes",
            "quiero ver fotos",
            "ver imagenes",
            "ver fotos",
            "muestrame imagenes",
            "muestrame fotos",
            "mostrar imagenes",
            "mostrar fotos",
            "mandame imagenes",
            "mandame fotos",
            "enviame imagenes",
            "enviame fotos",
            "comparteme imagenes",
            "comparteme fotos",
            "imagenes de ferias anteriores",
            "fotos de ferias anteriores",
            "ferias anteriores",
            "ediciones anteriores",
            "como se ve la feria",
            "como ha sido la feria",
        ],
    )


def asks_for_route(text):
    return has_any(
        text,
        [
            "como llego",
            "como llegar",
            "llegar a la feria",
            "llego a la feria",
            "como voy",
            "ruta",
            "indicaciones para llegar",
            "por donde llego",
        ],
    )


def asks_for_maps_link(text):
    return has_any(
        text,
        [
            "ruta en google maps",
            "link de google maps",
            "enlace de google maps",
            "mandame la ruta",
            "enviame la ruta",
            "comparteme la ruta",
            "enviar la ruta",
            "enviarme la ruta",
            "mandame la ubicacion",
            "enviame la ubicacion",
            "comparteme la ubicacion",
            "ubicacion en maps",
            "ubicacion en google",
            "google maps",
            "maps",
        ],
    )


def asks_for_arrival(text):
    return has_any(
        text,
        [
            "como llego",
            "como llegar",
            "llegar a la feria",
            "llego a la feria",
            "direccion",
            "ubicacion",
            "donde queda",
            "donde es",
            "como voy",
        ],
    )


def is_arrival_followup(text, memory):
    if memory.get("last_intent") not in {"arrival", "arrival_cost", "location"}:
        return False
    if memory.get("pending_field") not in {"arrival_origin", None}:
        return False
    return detect_arrival_origin(text) is not None


def detect_arrival_origin(text):
    if has_any(text, ["aeropuerto", "rafael nunez", "rafael nuñez"]):
        return "aeropuerto"
    if has_any(text, ["terminal", "terminal de transporte"]):
        return "terminal"
    if has_any(text, ["bocagrande"]):
        return "bocagrande"
    if has_any(text, ["getsemani", "getsemani"]):
        return "getsemani"
    if has_any(text, ["ciudad amurallada", "amurallada"]):
        return "ciudad_amurallada"
    if has_any(text, ["centro historico", "centro"]):
        return "centro"
    if has_any(text, ["crespo"]):
        return "crespo"
    if has_any(text, ["estoy en cartagena", "ya estoy en cartagena", "desde cartagena", "en cartagena", "cartagena"]):
        return "cartagena"
    if has_any(text, ["otra ciudad", "pereira", "bogota", "medellin", "cali", "barranquilla", "santa marta"]):
        return "otra_ciudad"
    return None


def detect_city_origin(text):
    match = re.search(r"\b(?:vengo|voy|soy|salgo)\s+de\s+([a-z ]{3,40})\b", text)
    if not match:
        return None
    raw_city = match.group(1).strip()
    raw_city = re.split(r"\b(?:y|pero|porque|para|con)\b", raw_city, maxsplit=1)[0].strip()
    if not raw_city:
        return None
    return " ".join(part.capitalize() for part in raw_city.split())


def asks_entry_cost(text):
    return has_any(
        text,
        [
            "tiene algun costo",
            "tiene costo",
            "hay costo",
            "costo de entrada",
            "valor de entrada",
            "precio de entrada",
            "cuanto cuesta entrar",
            "cuanto vale entrar",
            "hay que pagar",
            "pagar entrada",
            "entrada tiene costo",
            "entrada libre",
            "es gratis",
            "gratis",
        ],
    )


def asks_stand_price(text):
    return has_any(
        text,
        [
            "precio",
            "precios",
            "valor",
            "cuanto cuesta",
            "cuanto vale",
            "costo",
            "tarifa",
            "vale",
        ],
    )


def asks_ambiguous_value_question(text):
    if not has_any(text, ["valor", "cuanto vale", "cuanto cuesta", "costo", "precio"]):
        return False
    if has_any(
        text,
        [
            "entrada",
            "entrar",
            "ingreso",
            "visitante",
            "visitar",
            "asistir",
            "stand",
            "stands",
            "puesto",
            "puestos",
            "participar",
            "expositor",
            "exponer",
            "marca",
            "emprendimiento",
            "reservar",
            "reserva",
            "inscribir",
            "preinscripcion",
        ],
    ):
        return False
    return True


def has_no_value_context(memory):
    if memory.get("role"):
        return False
    if memory.get("selected_stand") or memory.get("desired_stand_type") or memory.get("desired_zone"):
        return False
    if memory.get("last_intent") not in {None, "greeting"}:
        return False
    relevant_history = [
        item
        for item in memory.get("history", [])
        if normalize((item or {}).get("user")) not in {"", "hola", "buenas", "buenos dias", "buenas tardes"}
    ]
    return not relevant_history


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
    category_aliases = [
        ("Joyería", ["joyeria", "joyero", "joyera", "joyeros", "joyeras", "joria", "joyas", "bisuteria", "aretes", "collares", "pulseras", "anillos", "reloj", "relojes"]),
        ("Gastronomía", ["gastronomia", "comida", "cafe", "chocolate", "dulces", "bebidas"]),
        ("Calzado y vestuario", ["calzado", "zapatos", "sandalias", "vestuario", "ropa", "moda", "bolsos", "bolso"]),
        ("Decoración", ["decoracion", "hogar", "muebles", "deco"]),
        ("Anticuarios", ["anticuarios", "antiguedades"]),
        ("Salud y belleza", ["salud", "belleza", "cosmetica", "cosmeticos", "bienestar", "cuidado personal"]),
        ("Artesanía típica", ["artesania", "artesanias", "artesania tipica", "artesanal", "artesanales", "manualidades"]),
        ("Arte", ["arte", "pintura", "ilustracion", "escultura"]),
    ]
    for category, aliases in category_aliases:
        if has_category_alias(text, aliases):
            return category
    return None


def base_booth(number):
    return next((item for item in BOOTHS if item["number"] == number), None)


def find_booth(number):
    booth = base_booth(number)
    if not booth:
        return None

    current = dict(booth)
    assignment = admin_stand_assignment(number)
    if assignment:
        current["status"] = "reserved"
        current["confirmed_brand"] = assignment.get("brand")
    return current


def iter_booths():
    for booth in BOOTHS:
        yield find_booth(booth["number"])


def stand_price_text(number):
    price = STAND_PRICES.get(number)
    if not price:
        return ""
    return f" Precio: {price['price']} ({price['type']} de {price['size']})."


def keep_required_details(base_reply, polished_reply):
    final_reply = str(polished_reply or "").strip()
    if not final_reply:
        return base_reply

    base_text = normalize(base_reply)
    final_text = normalize(final_reply)

    final_reply = soften_repeated_plan_phrase(base_reply, final_reply)
    final_text = normalize(final_reply)

    if "tengo precios" in base_text and "no tengo precios" in final_text:
        return base_reply

    if (
        ("ya esta reservado" in base_text or "aparece no disponible" in base_text)
        and ("genial eleccion" in final_text or "esta disponible" in final_text)
    ):
        return base_reply

    if ("no tengo un asesor disponible" in base_text or "no hay asesor disponible" in base_text) and (
        "google maps" in final_text or "maps google" in final_text or "preinscripcion para el stand" in final_text
    ):
        return base_reply

    if "tiempo exacto oficial" in base_text and (
        "google maps" in final_text or "maps google" in final_text or "llena el formulario" in final_text
    ):
        return base_reply

    if "ya diste el primer paso" in base_text and (
        "llena el formulario" in final_text or "llenes el formulario" in final_text
    ):
        return base_reply

    urls = re.findall(r"https?://\\S+", base_reply)
    missing_urls = [url for url in urls if url not in final_reply]
    if missing_urls:
        final_reply = f"{final_reply}\n\nFormulario oficial: {missing_urls[0]}"

    return final_reply


def soften_repeated_plan_phrase(base_reply, final_reply):
    base_text = normalize(base_reply)
    if "revisa el plano nuevamente" in base_text:
        return final_reply

    cleaned = re.sub(
        r"(?i)\b(revisa|mira|consulta)\s+el\s+plano\s+nuevamente,?\s*",
        "",
        str(final_reply or ""),
    ).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned or final_reply


def remember_turn(memory, user_message, reply):
    history = memory.setdefault("history", [])
    now = datetime.now(timezone.utc).isoformat()
    history.append({"user": user_message, "ori": reply, "created_at": now})
    del history[:-30]
    memory["updated_at"] = now
    internal_message = is_internal_history_message(user_message) or is_admin_session_active(memory.get("phone"))
    if not internal_message:
        memory["last_customer_message"] = user_message
        memory["last_customer_at"] = now
    append_conversation_log(memory, user_message, reply, now, internal_message)
    save_persistent_state()


def append_conversation_log(memory, user_message, reply, created_at, internal_message=False):
    path = Path(os.getenv("ORI_CONVERSATION_LOG_PATH", "memoria_revisable/conversaciones_todas.jsonl"))
    record = {
        "created_at": created_at,
        "phone": memory.get("phone"),
        "user_message": user_message,
        "reply": reply,
        "internal": bool(internal_message),
        "role": memory.get("role"),
        "brand": memory.get("brand"),
        "category": memory.get("category"),
        "product": memory.get("product"),
        "city": memory.get("city"),
        "lead_stage": memory.get("lead_stage"),
        "selected_stand": memory.get("selected_stand"),
        "confirmed_stand": memory.get("confirmed_stand"),
        "form_submitted": memory.get("form_submitted"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"No se pudo guardar historial completo de conversaciones: {error}", flush=True)


def save_review_memory_if_needed(user_message, base_reply, final_reply, memory, used_groq):
    reason = review_reason(user_message, base_reply, final_reply, memory, used_groq)
    if not reason:
        return

    path = Path(os.getenv("ORI_REVIEW_MEMORY_PATH", "memoria_revisable/conversaciones.jsonl"))
    record = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "user_message": user_message,
        "base_reply": base_reply,
        "final_reply": final_reply,
        "used_groq": used_groq,
        "memory": {
            "role": memory.get("role"),
            "last_intent": memory.get("last_intent"),
            "selected_stand": memory.get("selected_stand"),
            "selected_stand_status": memory.get("selected_stand_status"),
            "blocked_stand": memory.get("blocked_stand"),
            "blocked_stand_status": memory.get("blocked_stand_status"),
            "category": memory.get("category"),
            "city": memory.get("city"),
            "form_submitted": memory.get("form_submitted"),
        },
    }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as error:
        print(f"No se pudo guardar memoria revisable: {error}", flush=True)


def review_reason(user_message, base_reply, final_reply, memory, used_groq):
    text = normalize(user_message)
    triggers = []

    if used_groq:
        triggers.append("groq_intervino")
    if has_submitted_form(text):
        triggers.append("formulario_ya_enviado")
    if asks_to_change_topic(text):
        triggers.append("cambio_de_tema")
    if is_affirmative_followup(text, memory):
        triggers.append("respuesta_afirmativa")
    if wants_registration_link(text) or wants_to_reserve(text):
        triggers.append("intencion_comercial")
    if normalize(base_reply) != normalize(final_reply):
        triggers.append("respuesta_reescrita")

    return ", ".join(dict.fromkeys(triggers))


def lower_first(value):
    if not value:
        return value
    return value[0].lower() + value[1:]


def extract_stand_number(text):
    explicit = re.search(r"\b(?:stand|stan|estan|puesto)\s*(\d{1,3})\b", text)
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


def has_whole_phrase(text, phrase):
    normalized_phrase = normalize(phrase)
    pattern = r"\b" + re.escape(normalized_phrase).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text))


def has_category_alias(text, aliases):
    for alias in aliases:
        normalized_alias = normalize(alias)
        pattern = r"\b" + re.escape(normalized_alias).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pattern, text):
            return True
    return False


def normalize(value):
    normalized = unicodedata.normalize("NFD", str(value).lower())
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    cleaned = re.sub(r"[?¿!¡.,;:()]", " ", without_accents)
    return re.sub(r"\s+", " ", cleaned).strip()


def build_feria_context():
    available_patio = sorted(
        item["number"] for item in iter_booths() if item["status"] == "available" and item["zone"] == "patio"
    )
    available_salon = sorted(
        item["number"] for item in iter_booths() if item["status"] == "available" and item["zone"] == "salon"
    )
    reserved = sorted(item["number"] for item in iter_booths() if item["status"] == "reserved")
    unavailable = sorted(item["number"] for item in iter_booths() if item["status"] == "unavailable")

    return (
        f"Nombre: {FAIR_INFO['name']}\n"
        f"Fechas: {FAIR_INFO['dates']}\n"
        f"Sede: {FAIR_INFO['venue']}\n"
        f"Proposito: {FAIR_INFO['purpose']}\n"
        f"Mision de Ori: {FAIR_INFO['ori_mission']}\n"
        f"Modo visitante: {FAIR_INFO['visitor_mode']}\n"
        f"Modo comercial: {FAIR_INFO['sales_mode']}\n"
        f"Web oficial: {FAIR_INFO['official_site']}\n"
        f"Trayectoria: {FAIR_INFO['experience_years']}; {FAIR_INFO['total_fairs']}; "
        f"{FAIR_INFO['total_exhibitors']}; {FAIR_INFO['visitors_per_event']}\n"
        f"Ferias publicadas: {FAIR_INFO['official_fairs']}\n"
        f"Nota pública de ferias activas: {FAIR_INFO['active_fair_public_note']}\n"
        f"Formulario oficial de inscripción: {FAIR_INFO['registration_form_url']}\n"
        f"Nota del formulario: {FAIR_INFO['registration_form_note']}\n"
        f"Resumen visitantes: {FAIR_INFO['visitor_summary']}\n"
        f"Fotos para visitantes: {FAIR_INFO['visitor_photo_invite']}\n"
        f"Ferias anteriores: {FAIR_INFO['previous_fairs_summary']}\n"
        f"Resumen expositores: {FAIR_INFO['exhibitor_summary']}\n"
        f"Expositores confirmados: {FAIR_INFO['confirmed_exhibitors_note']}\n"
        f"Productos y servicios: {FAIR_INFO['products']}\n"
        f"Categorías oficiales de inscripción: {FAIR_INFO['registration_categories']}\n"
        f"Datos solicitados en inscripción: {FAIR_INFO['registration_fields']}\n"
        f"Actividades: {FAIR_INFO['activities']}\n"
        f"Ubicación: {FAIR_INFO['location']}\n"
        f"Cómo llegar: {FAIR_INFO['arrival_tip']}\n"
        f"Guía de llegada: {FAIR_INFO['arrival_guide']}\n"
        f"Google Maps oficial: {FAIR_INFO['google_maps_url']}\n"
        f"Costo de entrada visitantes: {FAIR_INFO['entry_cost']}\n"
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
