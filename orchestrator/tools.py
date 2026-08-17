from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from orchestrator.chat import chat_with_agent
from orchestrator.platform import PlatformStore, get_store
from orchestrator.public_apis import (
    geocode_address,
    get_dollar,
    get_holidays,
    get_local_time,
    get_weather,
    lookup_food,
)
from orchestrator.retry import PermanentError


PUBLIC_TOOL_META = (
    {
        "name": "get_weather",
        "label": "Clima",
        "source": "Open-Meteo",
        "description": "Clima actual por barrio o local.",
    },
    {
        "name": "get_dollar",
        "label": "Dólar",
        "source": "DolarAPI",
        "description": "Cotización del dólar.",
    },
    {
        "name": "get_holidays",
        "label": "Feriados",
        "source": "ArgentinaDatos",
        "description": "Feriados argentinos del año.",
    },
    {
        "name": "get_local_time",
        "label": "Hora local",
        "source": "WorldTimeAPI",
        "description": "Hora actual en Buenos Aires.",
    },
    {
        "name": "lookup_food",
        "label": "Alimentos",
        "source": "Open Food Facts",
        "description": "kcal, proteínas, sal y alérgenos públicos.",
    },
    {
        "name": "geocode_address",
        "label": "Geocodificación",
        "source": "USIG",
        "description": "Normaliza una dirección de CABA.",
    },
)
PUBLIC_TOOLS = {item["name"] for item in PUBLIC_TOOL_META}
PUBLIC_API_HINTS = {
    "get_weather": "clima / lluvia / frío / calor → get_weather(place del barrio o local)",
    "get_dollar": "dólar / USD / cotización → get_dollar",
    "get_holidays": "feriado / si abre hoy → get_holidays y get_local_time",
    "get_local_time": "hora / último pedido / ¿llego? → get_local_time",
    "lookup_food": "kcal / alérgenos públicos / Open Food Facts → lookup_food",
    "geocode_address": "dirección / geocodificar CABA → geocode_address",
}

TOOL_CATALOG = [
    {
        "name": "lookup_agent",
        "description": "Busca un agente por nombre o id en el registro interno.",
        "args": {"name_or_id": "string"},
    },
    {
        "name": "create_or_update_agent",
        "description": "Crea o actualiza un agente de atención. type opcional: menu, nutrition o geo.",
        "args": {
            "name": "string",
            "goal": "string",
            "personality": "string",
            "type": "menu|nutrition|geo?",
        },
    },
    {
        "name": "attach_knowledge",
        "description": (
            "Asocia ktags (name/value) a un agente. "
            "topics puede ser lista de strings o de objetos {name, value}."
        ),
        "args": {"agent_id": "string", "topics": "list[string|{name,value}]"},
    },
    {
        "name": "enable_capability",
        "description": "Habilita una capacidad del agente: cart, reservation o contact.",
        "args": {"agent_id": "string", "capability": "cart|reservation|contact"},
    },
    {
        "name": "get_weather",
        "description": (
            "Clima actual sin API key (Open-Meteo). "
            "place: palermo, belgrano, recoleta, caba o el nombre del local."
        ),
        "args": {"place": "palermo|belgrano|recoleta|caba|sakura|lima|andino"},
    },
    {
        "name": "get_dollar",
        "description": "Cotización del dólar en Argentina sin API key (DolarAPI).",
        "args": {"casa": "all|oficial|bolsa?"},
    },
    {
        "name": "get_holidays",
        "description": "Feriados argentinos sin API key (ArgentinaDatos). year opcional.",
        "args": {"year": "int?"},
    },
    {
        "name": "get_local_time",
        "description": "Hora actual en Buenos Aires sin API key (WorldTimeAPI).",
        "args": {},
    },
    {
        "name": "lookup_food",
        "description": (
            "Busca un alimento en Open Food Facts (sin API key): kcal, proteínas, sal, alérgenos. "
            "No reemplaza la carta del local."
        ),
        "args": {"query": "string"},
    },
    {
        "name": "geocode_address",
        "description": "Normaliza una dirección de CABA sin API key (USIG). Ej: Honduras 4780.",
        "args": {"address": "string"},
    },
    {
        "name": "execute_agent",
        "description": (
            "Ejecuta un agente ya activo: le envía el mensaje y responde con RAG. "
            "Si el plan ya llamó APIs públicas, el runtime inyecta esos datos en vivo. "
            "No usar si el agente está en reserva: primero hay que activarlo."
        ),
        "args": {"agent_id": "string", "message": "string"},
    },
    {
        "name": "create_support_ticket",
        "description": "Abre un ticket de soporte. Usar como fallback si una acción crítica falla.",
        "args": {"summary": "string", "agent_id": "string?"},
    },
]


def execute_agent(
    agent_id: str,
    message: str,
    live_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    store = get_store()
    if not (message or "").strip():
        raise PermanentError("execute_agent requiere message")
    agent = store.get_agent(agent_id)
    if store.agent_status(agent["id"]) != "active":
        raise PermanentError("execute_agent requiere un agente activo")
    answer = chat_with_agent(store, agent["id"], message, live_context=live_context)
    payload = {
        "agent_id": agent["id"],
        "agent_name": answer.get("agent_name"),
        "delivered": True,
        "reply": answer["reply"],
        "citations": answer["citations"],
        "context": answer.get("context") or [],
        "live_facts": answer.get("live_facts") or [],
        "live_sources": answer.get("live_sources") or [],
    }
    if answer.get("handoff_agent_id"):
        payload["handoff_agent_id"] = answer["handoff_agent_id"]
        payload["handoff_agent_name"] = answer.get("handoff_agent_name") or ""
    return payload


def _guard_public(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if name in disabled_public_tools():
            raise PermanentError(f"la tool {name} está desactivada")
        return fn(*args, **kwargs)

    return wrapped


def build_tool_handlers(store: PlatformStore | None = None) -> dict[str, Callable[..., Any]]:
    platform = store or get_store()
    return {
        "lookup_agent": platform.lookup_agent,
        "create_or_update_agent": platform.create_or_update_agent,
        "attach_knowledge": platform.attach_knowledge,
        "enable_capability": platform.enable_capability,
        "get_weather": _guard_public("get_weather", get_weather),
        "get_dollar": _guard_public("get_dollar", get_dollar),
        "get_holidays": _guard_public("get_holidays", get_holidays),
        "get_local_time": _guard_public("get_local_time", get_local_time),
        "lookup_food": _guard_public("lookup_food", lookup_food),
        "geocode_address": _guard_public("geocode_address", geocode_address),
        "execute_agent": execute_agent,
        "create_support_ticket": platform.create_support_ticket,
    }


def disabled_public_tools() -> set[str]:
    return get_store().disabled_public_tools()


def list_public_tools() -> list[dict[str, Any]]:
    disabled = disabled_public_tools()
    return [
        {**dict(item), "enabled": item["name"] not in disabled}
        for item in PUBLIC_TOOL_META
    ]


def catalog_for_prompt() -> str:
    disabled = disabled_public_tools()
    lines = []
    for tool in TOOL_CATALOG:
        args = ", ".join(f"{k}: {v}" for k, v in tool["args"].items())
        signature = f"{tool['name']}({args})" if args else f"{tool['name']}()"
        note = " (desactivada: el runtime falla el nodo y sigue)" if tool["name"] in disabled else ""
        lines.append(f"- {signature}: {tool['description']}{note}")
    return "\n".join(lines)
