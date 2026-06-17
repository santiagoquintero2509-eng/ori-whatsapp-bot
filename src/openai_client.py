import json
import os
import urllib.error
import urllib.request


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIClientError(RuntimeError):
    pass


def is_openai_enabled():
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    return bool(api_key) and not api_key.startswith("pega_aqui")


def ask_chatgpt(user_message, feria_context):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key.startswith("pega_aqui"):
        raise OpenAIClientError("OPENAI_API_KEY no esta configurada")

    model = os.getenv("OPENAI_MODEL", "gpt-5.5").strip()
    timeout = int(os.getenv("OPENAI_TIMEOUT", "20"))

    payload = {
        "model": model,
        "store": False,
        "max_output_tokens": 220,
        "instructions": build_instructions(feria_context),
        "input": user_message,
    }

    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise OpenAIClientError(f"OpenAI respondio {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise OpenAIClientError(f"No se pudo conectar con OpenAI: {error}") from error

    text = extract_response_text(data)
    if not text:
        raise OpenAIClientError("OpenAI no devolvio texto")

    return text.strip()


def build_instructions(feria_context):
    return f"""
Eres Ori, asistente virtual de Feria Origen Colombia.
Tu tono es calido, cercano, colombiano, claro y profesional.
Responde siempre en espanol.
Responde como mensaje de WhatsApp: breve, util y facil de leer.
No uses markdown complejo.
No inventes precios, horarios, direcciones exactas, telefonos ni agenda detallada si no estan en el contexto.
Si falta un dato, dilo con naturalidad y ofrece escribir "asesor".
Si preguntan por stands, usa la disponibilidad del contexto.
Si preguntan por participar como expositor, pide nombre, marca, producto y stand de interes.
No digas que eres ChatGPT; eres Ori.

Contexto confirmado de la feria:
{feria_context}
""".strip()


def extract_response_text(data):
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    fragments = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                fragments.append(content["text"])

    return "\n".join(fragments).strip()
