"""Desenvuelto de la salida cruda de un LLM: el cercado ```...``` que suele agregar
y, cuando corresponde, el parseo a JSON."""
import json
import re


def strip_markdown(content: str) -> str:
    """Quita el cercado ```...``` (con prefijo json/cypher) que el LLM suele añadir."""
    if "```" in content:
        partes = content.split("```")
        content = partes[1] if len(partes) > 1 else content
        if content.startswith("json"):
            content = content[4:]
        elif content.startswith("cypher"):
            content = content[6:]
    return content.strip()


def json_del_llm(content: str) -> dict | None:
    """Desenvuelve el markdown y parsea JSON. Si el LLM agregó texto extra alrededor
    del objeto, cae a extraer el primer bloque {...}. None si no se puede parsear."""
    texto = strip_markdown(content)
    if (m := re.search(r"\{.*\}", texto, re.DOTALL)):
        texto = m.group(0)
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return None
