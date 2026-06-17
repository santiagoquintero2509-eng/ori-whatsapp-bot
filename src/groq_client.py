import json
import os
import urllib.error
import urllib.request


GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


class GroqClientError(RuntimeError):
    pass


def is_groq_enabled():
    use_groq = os.getenv("USE_GROQ", "false").strip().lower()
    if use_groq not in {"1", "true", "yes", "si"}:
        return False

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    return bool(api_key) and not api_key.startswith("pega_aqui")


def polish_with_groq(user_message, base_reply, feria_context, memory=None):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key.startswith("pega_aqui"):
        raise GroqClientError("GROQ_API_KEY no esta configurada")

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
    timeout = int(os.getenv("GROQ_TIMEOUT", "18"))

    payload = {
        "model": model,
        "temperature": 0.65,
        "max_tokens": 230,
        "messages": [
            {"role": "system", "content": build_system_prompt(feria_context)},
            {"role": "user", "content": build_user_prompt(user_message, base_reply, memory or {})},
        ],
    }

    request = urllib.request.Request(
        GROQ_CHAT_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "OriWhatsAppBot/1.0",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise GroqClientError(f"Groq respondio {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise GroqClientError(f"No se pudo conectar con Groq: {error}") from error

    text = extract_message_text(data)
    if not text:
        raise GroqClientError("Groq no devolvio texto")

    return text.strip()


def build_system_prompt(feria_context):
    return f"""
Eres Ori, asistente virtual oficial de Feria Origen Colombia.
Tu tarea es conversar de forma mas humana, clara y contextual, usando la respuesta base como verdad principal.
Tienes un 60% de libertad para redactar: puedes reordenar, resumir, preguntar mejor, hacer seguimiento y adaptar el tono al contexto.
El 40% restante debe respetar los datos oficiales y el sentido de la respuesta base.
Responde siempre en espanol para WhatsApp.
Se breve, calida, util y profesional.
Si el usuario pregunta algo puntual o responde con pocas palabras, responde puntual: 1 a 3 frases.
Si necesita opciones, usa maximo 4 lineas cortas.
No descargues toda la informacion disponible si no hace falta.
No uses markdown complejo.
No digas que eres una IA, Groq, Llama ni ChatGPT.
No agregues precios, horarios, telefonos, direcciones exactas, agenda detallada ni datos no confirmados.
Si falta informacion, dilo con naturalidad y ofrece escribir "asesor".
Si la respuesta base dice que no hay asesor o contacto oficial cargado, no ofrezcas transferencia, llamada, contacto directo ni formulario de inscripcion como reemplazo.
No conviertas una solicitud de asesor en una respuesta de inscripcion, salvo que el usuario tambien pida claramente inscribirse o participar.
Si la respuesta base dice que se compartira el plano, conserva esa intencion. No digas que el usuario debe buscarlo en la web, Galeria o Nuestro Espacio.
Si el stand esta disponible, puedes sonar optimista y motivadora.
Si el stand esta reservado o no disponible, baja el optimismo: se empatica, clara y cuidadosa. No digas "genial eleccion" ni lo trates como opcion valida.
Si hay numeros de stands, estados, medidas o precios, conservalos exactamente.
Si la respuesta base incluye un enlace, debes conservarlo.
No cambies el sentido de la respuesta base.

Contexto oficial cargado en Ori:
{feria_context}
""".strip()


def build_user_prompt(user_message, base_reply, memory):
    role = memory.get("role") or "sin rol definido"
    last_intent = memory.get("last_intent") or "sin intencion previa"
    selected_stand = memory.get("selected_stand") or "ninguno"
    selected_stand_status = memory.get("selected_stand_status") or "ninguno"
    blocked_stand = memory.get("blocked_stand") or "ninguno"
    blocked_stand_status = memory.get("blocked_stand_status") or "ninguno"
    pending_field = memory.get("pending_field") or "ninguno"
    category = memory.get("category") or "ninguna"
    history = format_history(memory.get("history", []))

    return f"""
Mensaje recibido:
{user_message}

Contexto de conversacion:
- Rol detectado: {role}
- Intencion previa: {last_intent}
- Stand seleccionado: {selected_stand}
- Estado del stand seleccionado: {selected_stand_status}
- Stand mencionado pero no disponible/reservado: {blocked_stand}
- Estado del stand bloqueado: {blocked_stand_status}
- Pregunta o dato pendiente: {pending_field}
- Categoria confirmada: {category}

Ultimos turnos:
{history}

Respuesta base de Ori, con datos oficiales que debes respetar:
{base_reply}

Redacta una sola respuesta final de WhatsApp, natural y cercana.
Si el mensaje del usuario responde una pregunta anterior, continua ese hilo y no vuelvas a empezar.
Prioriza el siguiente paso practico sobre explicar todo el contexto.
""".strip()


def format_history(history):
    if not history:
        return "Sin historial reciente."

    lines = []
    for item in history[-3:]:
        lines.append(f"Usuario: {item.get('user', '')}")
        lines.append(f"Ori: {item.get('ori', '')}")
    return "\n".join(lines)


def extract_message_text(data):
    choices = data.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()
