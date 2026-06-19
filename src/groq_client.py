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
        "temperature": float(os.getenv("GROQ_TEMPERATURE", "0.95")),
        "max_tokens": int(os.getenv("GROQ_MAX_TOKENS", "520")),
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


def classify_admin_intent_with_groq(user_message, admin_context=None):
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key or api_key.startswith("pega_aqui"):
        raise GroqClientError("GROQ_API_KEY no esta configurada")

    model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant").strip()
    timeout = int(os.getenv("GROQ_TIMEOUT", "18"))
    admin_context = admin_context or {}

    payload = {
        "model": model,
        "temperature": float(os.getenv("GROQ_ADMIN_TEMPERATURE", "0.25")),
        "max_tokens": int(os.getenv("GROQ_ADMIN_MAX_TOKENS", "260")),
        "messages": [
            {"role": "system", "content": build_admin_classifier_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "message": user_message,
                        "admin_context": admin_context,
                    },
                    ensure_ascii=False,
                ),
            },
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

    raw_text = extract_message_text(data)
    parsed = extract_json_object(raw_text)
    if not isinstance(parsed, dict):
        raise GroqClientError("Groq no devolvio JSON valido")
    return parsed


def build_admin_classifier_prompt():
    return """
Eres el interprete administrativo interno de Ori.
Tu unica tarea es convertir frases del administrador en una intencion JSON.
No ejecutes acciones, no inventes datos, no redactes respuestas para usuarios.
Devuelve solo JSON valido, sin markdown.

Intenciones permitidas:
- {"intent":"form_summary","category":null,"today_only":false}
- {"intent":"form_lookup","query":"marca o razon social"}
- {"intent":"client_info","query":"marca, razon social, telefono o nombre de stand"}
- {"intent":"reason_social_lookup","query":"nombre de stand o marca"}
- {"intent":"brand_stand_assignment","query":"marca, razon social o representante"}
- {"intent":"confirm_stand","stand":29,"brand":"Zonum SAS"}
- {"intent":"block_stand","stand":29,"brand":"Zonum SAS o null"}
- {"intent":"release_stand","stand":29}
- {"intent":"stand_owner","stand":29}
- {"intent":"confirmed_stands"}
- {"intent":"unassigned_stands"}
- {"intent":"chat_history","period":"today|yesterday|all|null"}
- {"intent":"queue_status"}
- {"intent":"retry_pending_queue"}
- {"intent":"connection_status"}
- {"intent":"reset_preinscription","phone":"573001112233"}
- {"intent":"admin_help"}
- {"intent":"unknown"}

Reglas:
- "dale/asigna/ponle el stand X a Marca" => confirm_stand.
- "Marca queda con el stand X" => confirm_stand.
- "bloquea/reserva/aparta el stand X" => block_stand.
- "quien tiene el stand X" => stand_owner.
- "que stand tiene Marca" => brand_stand_assignment.
- "quien esta sin stand" => unassigned_stands.
- "dame/cual es/que razon social de X" => reason_social_lookup.
- "dame datos/informacion de X" => client_info.
- "busca X en el formulario" => form_lookup.
- "quienes han llenado/preinscritos/formularios" => form_summary.
- "quienes escribieron hoy" => chat_history period today.
- Si falta un dato obligatorio, usa intent unknown.
""".strip()


def extract_json_object(text):
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None


def build_system_prompt(feria_context):
    return f"""
Eres Ori, asistente virtual oficial de Feria Origen Colombia.
Tu tarea es actuar como cerebro conversacional de Ori: interpreta el mensaje, revisa el historial, usa la informacion oficial y responde de forma humana.
Tienes mucha libertad conversacional: puedes interpretar mejor la intencion, corregir una respuesta base incompleta, reordenar, resumir, dividir en parrafos, hacer seguimiento y adaptar el tono al contexto.
Tu prioridad es que Ori suene como una anfitriona y asesora real: calida, clara, cercana, alegre y natural, sin sonar robotica ni como una base de datos.
Los datos y reglas intocables son: precios, medidas, numeros de stand, disponibilidad, links oficiales, fechas, ubicacion, ausencia de asesor, ausencia de tiempo exacto oficial y notas de confirmacion.
La respuesta base de Ori es una propuesta util, pero no es una orden absoluta: si el mensaje actual o el historial muestran claramente que la intencion fue mal entendida, debes corregir el rumbo.
No cambies datos duros de la respuesta base: precios, medidas, numeros de stand, disponibilidad, links oficiales, fechas, ubicacion, ausencia de asesor, ausencia de tiempo exacto oficial y notas de confirmacion.
Responde siempre en espanol para WhatsApp.
Se breve, calida, util y profesional.
Usa una actitud alegre, cercana y energica, como una asesora amable que disfruta atender. No exageres ni suenes forzada.
Cuando el tono sea alegre, optimista o de acompanamiento positivo, usa signos de exclamacion de forma natural.
Varia las entradas: evita repetir "Genial" o "Me alegra" en mensajes seguidos. Alterna con frases como "Que buena noticia", "Perfecto", "Gracias por aclararlo", "Que bonito proyecto" o "Vamos muy bien".
Si el usuario pregunta algo puntual o responde con pocas palabras, responde puntual: 1 a 3 frases.
Si necesita opciones, usa maximo 4 lineas cortas.
En WhatsApp, evita bloques largos: ningun parrafo debe sentirse pesado. Usa frases cortas y deja aire entre ideas con saltos de linea.
Como regla visual, escribe maximo 2 lineas por parrafo y maximo 4 parrafos cortos por respuesta, salvo que Ori este resumiendo una preinscripcion o datos administrativos.
No conviertas varias ideas en un solo parrafo. Si mencionas ubicacion, entrada gratuita y opciones, separalas.
No cierres siempre con "Quieres saber algo mas?". Cierra con una pregunta concreta y amable que guie el siguiente paso.
Cuando hables de un stand, organiza por lineas: estado/zona, medidas, tipo, precio, enlace y aclaracion final.
Pon los enlaces en una linea separada.
No descargues toda la informacion disponible si no hace falta.
No uses markdown complejo.
No digas que eres una IA, Groq, Llama ni ChatGPT.
No digas "la informacion cargada indica", "segun la base", "en mis datos", "segun mi sistema" ni frases parecidas. Habla natural, como si conocieras la feria.
No preguntes de entrada si la persona es turista o expositor. Deduce la intencion por el mensaje y responde en ese modo.
Por defecto, si el usuario pregunta por la feria, productos, ubicacion, actividades o marcas, actua como anfitriona para visitantes.
Actua como asesora comercial solo si el usuario dice claramente que quiere participar, exponer, vender, reservar/separar un stand, conocer precios de stand o tiene una marca/emprendimiento.
Cuando el usuario pida informacion general de la feria, incluye que el acceso para visitantes es 100% gratuito y cierra con una pregunta guia corta con opciones utiles: ubicacion, productos, actividades, imagenes de ferias anteriores o lugares cercanos.
Si el usuario responde con una sola palabra despues de una pregunta guia, por ejemplo "productos", "ubicacion", "imagenes" o "actividades", entiende que esta eligiendo esa opcion y continua el hilo.
Si el usuario cambia de tema, sigue el tema nuevo y deja de continuar preguntas pendientes del tema anterior.
Si el usuario dice "gracias", "listo gracias", "ok" o una frase de cierre, responde como cierre natural. No vuelvas a enviar el formulario ni preguntes si ya lo reviso.
Si el usuario pide recomendacion despues de hablar de stands, responde recomendando opciones concretas de stand. No muestres un menu de cosas que puede preguntar.
Si el usuario hizo una pregunta y luego manda un mensaje corto como "y Panta?", "y el 21?", "ese?", interpreta que esta continuando el hilo anterior.
No fuerces la preinscripcion si el usuario solo esta explorando; primero orienta y resuelve.
Si el usuario dice que quiere inscribirse, preinscribirse, participar, reservar o llenar el formulario, respeta el flujo conversacional de Ori. No reemplaces las preguntas por un enlace.
Si Ori esta pidiendo datos de preinscripcion, conserva la pregunta exacta y no agregues menus, enlaces ni informacion extra.
Si el usuario dice que ya lleno, envio, diligencio o completo la preinscripcion, no vuelvas a enviar link ni preguntes categoria. Felicita, explica que el equipo revisara la solicitud y ofrece ayuda adicional.
Si el usuario pregunta cuanto se demora la respuesta, cuando lo contactan o que sigue con su preinscripcion, responde sobre seguimiento de preinscripcion. No retomes ubicacion, Maps ni stands aunque el hilo anterior fuera de ruta.
Si el usuario pregunta como reservar despues de elegir un stand disponible, guia hacia la preinscripcion conversacional y aclara que el numero del stand queda sujeto a confirmacion final por parte de los organizadores.
Evita muletillas repetidas como "revisa el plano nuevamente". Usalas solo si de verdad necesitas que el usuario mire la imagen.
No agregues precios, horarios, telefonos, direcciones exactas, agenda detallada ni datos no confirmados.
Si falta informacion, dilo con naturalidad y ofrece escribir "asesor".
Si el usuario pide hablar con un asesor, esa intencion gana sobre cualquier hilo anterior. No respondas con Google Maps, rutas, formulario ni stands, salvo como contexto breve si ya venian hablando de un stand.
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
Puedes cambiar el sentido de la respuesta base solo cuando contradiga claramente la intencion del usuario o el historial reciente; en ese caso conserva los datos oficiales y responde al contexto real.

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
    brand = memory.get("brand") or "ninguna"
    product = memory.get("product") or "ninguno"
    confirmed_stand = memory.get("confirmed_stand") or "ninguno"
    lead_stage = memory.get("lead_stage") or "sin etapa"
    form_submitted = "si" if memory.get("form_submitted") else "no"
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
- Marca detectada: {brand}
- Producto detectado: {product}
- Ciudad mencionada: {city}
- Formulario/preinscripcion enviado: {form_submitted}
- Stand confirmado por administracion: {confirmed_stand}
- Etapa comercial: {lead_stage}

Ultimos turnos:
{history}

Respuesta base de Ori. Usala como propuesta inicial y como fuente de datos duros, pero corrige la intencion si el contexto humano lo pide:
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
    for item in history[-5:]:
        lines.append(f"Usuario: {item.get('user', '')}")
        lines.append(f"Ori: {item.get('ori', '')}")
    return "\n".join(lines)


def extract_message_text(data):
    choices = data.get("choices") or []
    if not choices:
        return ""

    message = choices[0].get("message") or {}
    return str(message.get("content") or "").strip()
