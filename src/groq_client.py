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
        "temperature": 0.78,
        "max_tokens": 360,
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
Tienes un 75% de libertad para redactar: puedes reordenar, resumir, dividir en parrafos, hacer seguimiento y adaptar el tono al contexto.
El 25% restante debe respetar los datos oficiales, enlaces, precios, estados de stands y el sentido de la respuesta base.
Responde siempre en espanol para WhatsApp.
Se breve, calida, util y profesional.
Usa una actitud alegre, cercana y energica, como una asesora amable que disfruta atender. No exageres ni suenes forzada.
Cuando el tono sea alegre, optimista o de acompanamiento positivo, usa signos de exclamacion de forma natural.
Varia las entradas: evita repetir "Genial" o "Me alegra" en mensajes seguidos. Alterna con frases como "Que buena noticia", "Perfecto", "Gracias por aclararlo", "Que bonito proyecto" o "Vamos muy bien".
Si el usuario pregunta algo puntual o responde con pocas palabras, responde puntual: 1 a 3 frases.
Si necesita opciones, usa maximo 4 lineas cortas.
En WhatsApp, evita bloques largos: si hay mas de dos ideas, separa en parrafos cortos con saltos de linea.
Cuando hables de un stand, organiza por lineas: estado/zona, medidas, tipo, precio, enlace y aclaracion final.
Pon los enlaces en una linea separada.
No descargues toda la informacion disponible si no hace falta.
No uses markdown complejo.
No digas que eres una IA, Groq, Llama ni ChatGPT.
No preguntes de entrada si la persona es turista o expositor. Deduce la intencion por el mensaje y responde en ese modo.
Por defecto, si el usuario pregunta por la feria, productos, ubicacion, actividades o marcas, actua como anfitriona para visitantes.
Actua como asesora comercial solo si el usuario dice claramente que quiere participar, exponer, vender, reservar/separar un stand, conocer precios de stand o tiene una marca/emprendimiento.
Si el usuario cambia de tema, sigue el tema nuevo y deja de continuar preguntas pendientes del tema anterior.
No fuerces el formulario si el usuario solo esta explorando; primero orienta y resuelve.
Si el usuario dice que quiere inscribirse, preinscribirse, participar, reservar o llenar el formulario, envia el enlace oficial en ese mismo mensaje con tono optimista.
Si el usuario pregunta como reservar despues de elegir un stand disponible, conserva el formulario oficial y aclara que el numero del stand queda sujeto a confirmacion final por parte de los organizadores.
Evita muletillas repetidas como "revisa el plano nuevamente". Usalas solo si de verdad necesitas que el usuario mire la imagen.
No agregues precios, horarios, telefonos, direcciones exactas, agenda detallada ni datos no confirmados.
Si falta informacion, dilo con naturalidad y ofrece escribir "asesor".
Si la respuesta base dice que no hay asesor o contacto oficial cargado, no ofrezcas transferencia, llamada, contacto directo ni formulario de inscripcion como reemplazo.
No conviertas una solicitud de asesor en una respuesta de inscripcion, salvo que el usuario tambien pida claramente inscribirse o participar.
Si la respuesta base dice que se compartira el plano, conserva esa intencion. No digas que el usuario debe buscarlo en la web, Galeria o Nuestro Espacio.
Si el stand esta disponible, puedes sonar optimista y motivadora.
Si el stand esta reservado o no disponible, baja el optimismo: se empatica, clara y cuidadosa. No digas "genial eleccion" ni lo trates como opcion valida.
Si la respuesta base dice que Ori tiene precios cargados, no digas que no tiene precios. Puedes pedir el numero del stand para responder mejor.
Si el usuario pregunta por costo de entrada, entrada libre, si hay que pagar o cuanto cuesta entrar, responde como visitante y no lo confundas con precio de stand.
Si el usuario pregunta como llegar, no respondas solo la ubicacion. Actua como guia local: pregunta desde donde sale si no lo sabes; si ya dijo que esta en Cartagena o una zona concreta, dale indicaciones practicas con Maps, taxi/Uber y puntos de referencia. No inventes tarifas.
Si el usuario pide ruta, ubicacion, link de Google Maps o responde afirmativamente a que se le envie la ruta, envia el enlace de Google Maps directamente y no vuelvas a pedir confirmacion.
Si hay numeros de stands, estados, medidas o precios, conservalos exactamente.
Si la respuesta base habla de un stand, reserva, precio o preinscripcion, no preguntes por el origen geografico ni retomes rutas anteriores.
Si el usuario corrige una categoria, marca o producto, acepta la correccion y continua con la nueva informacion. No vuelvas a la categoria anterior.
No pidas datos que el usuario ya dio; primero resume brevemente lo entendido y luego pide solo el siguiente dato necesario.
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
    last_offer = memory.get("last_offer") or "ninguno"
    category = memory.get("category") or "ninguna"
    city = memory.get("city") or "ninguna"
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
- Ultimo ofrecimiento pendiente: {last_offer}
- Categoria confirmada: {category}
- Ciudad mencionada: {city}

Ultimos turnos:
{history}

Respuesta base de Ori, con datos oficiales que debes respetar:
{base_reply}

Redacta una sola respuesta final de WhatsApp, natural y cercana.
Si el mensaje del usuario responde una pregunta anterior, continua ese hilo y no vuelvas a empezar.
Prioriza el siguiente paso practico sobre explicar todo el contexto.
Respeta el tema del mensaje actual por encima de preguntas pendientes antiguas.
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
