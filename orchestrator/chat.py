from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from orchestrator.instructions import resolve_instructions
from orchestrator.llm import get_llm
from orchestrator.platform import PlatformStore
from orchestrator.public_apis import (
    detect_public_tools,
    disabled_tool_fact,
    fetch_live_facts,
    format_live_facts,
)
from orchestrator.rag import retriever
from orchestrator.retry import PermanentError


class GeoChoice(BaseModel):
    reply: str = Field(
        description="Derivación breve en español: qué local y por qué. No armes la carta."
    )
    venue_agent_id: str = Field(
        description="Id del agente de menú elegido, copiado de venue_roster"
    )
    venue_name: str = Field(description="Nombre del local elegido")


def chat_with_agent(
    store: PlatformStore,
    agent_id: str,
    message: str,
    live_context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    text = (message or "").strip()
    if not text:
        raise PermanentError("el mensaje no puede estar vacío")
    agent = store.get_agent(agent_id)
    ktags = store.collect_rag_ktags(agent["id"])
    hits = retriever.retrieve(text, ktags)
    context = _format_context(hits)
    disabled = store.disabled_public_tools()
    kept = [
        item
        for item in (live_context or [])
        if item.get("tool")
    ]
    kept_tools = {str(item.get("tool") or "") for item in kept}
    skip = kept_tools | disabled
    disabled_facts = [
        {"tool": tool, **disabled_tool_fact(tool)}
        for tool in detect_public_tools(text, agent_type=str(agent.get("type") or ""))
        if tool in disabled and tool not in kept_tools
    ]
    live_facts = list(kept) + disabled_facts + fetch_live_facts(agent, text, skip=skip)
    live = format_live_facts(live_facts)
    prompt = resolve_instructions(agent)
    agent_type = str(agent.get("type") or "")
    user_content = f"Conocimiento recuperado:\n{context or '(vacío)'}\n\n"
    if live:
        user_content += (
            "Datos en vivo (APIs públicas, no son la carta del local):\n"
            f"{live}\n\n"
        )
    if agent_type == "geo":
        user_content += (
            "Instrucción: elegí UN venue_agent_id de venue_roster. "
            "El orquestador redirige el flujo a ese agente de menú. "
            "Tu reply es la derivación breve (local + por qué), no la carta. "
            "No recomiendes locales en reserva ni inventes otros.\n\n"
        )
    if agent_type == "menu" and any(item.get("tool") == "geo_handoff" for item in live_facts):
        user_content += (
            "Instrucción: Dónde Comer te derivó este cliente. "
            "Atendé el pedido con la carta de este local.\n\n"
        )
    if any(not item.get("ok") for item in live_facts):
        user_content += (
            "Instrucción: falta alguna porción de datos en vivo. "
            "Pedí disculpas breves por esa información, no la inventes, "
            "y respondé el resto con el conocimiento recuperado.\n\n"
        )
    user_content += f"Mensaje del usuario:\n{text}"
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_content},
    ]
    handoff_agent_id = ""
    handoff_agent_name = ""
    if agent_type == "geo":
        choice: GeoChoice = get_llm(temperature=0.2).with_structured_output(
            GeoChoice, method="function_calling"
        ).invoke(messages)
        content = choice.reply.strip()
        handoff_agent_id = (choice.venue_agent_id or "").strip()
        handoff_agent_name = (choice.venue_name or "").strip()
    else:
        reply = get_llm(temperature=0.2).invoke(messages)
        content = reply.content if isinstance(reply.content, str) else str(reply.content)
        content = content.strip()
    citations = [
        {"name": hit["name"], "score": hit["score"], "source_agent": hit.get("source_agent")}
        for hit in hits
    ]
    for item in live_facts:
        source = item.get("source") or item.get("tool")
        if source:
            citations.append({"name": str(source), "score": 1.0, "source_agent": "api"})
    return {
        "agent_id": agent["id"],
        "agent_name": agent["name"],
        "reply": content,
        "handoff_agent_id": handoff_agent_id,
        "handoff_agent_name": handoff_agent_name,
        "citations": citations,
        "context": [
            {
                "name": str(hit.get("name") or ""),
                "value": str(hit.get("value") or ""),
                "score": hit.get("score"),
                "source_agent": hit.get("source_agent"),
            }
            for hit in hits
            if hit.get("name") or hit.get("value")
        ],
        "live_facts": [
            {
                "tool": item.get("tool") or item.get("source"),
                "ok": bool(item.get("ok")),
                "detail": _live_fact_detail(item),
            }
            for item in live_facts
            if item.get("tool") or item.get("source")
        ],
        "live_sources": [
            item.get("tool") or item.get("source")
            for item in live_facts
            if item.get("ok")
        ],
    }


def _format_context(hits: list[dict[str, Any]]) -> str:
    blocks = []
    for hit in hits:
        source = hit.get("source_agent") or ""
        header = hit["name"] if not source else f"{hit['name']}"
        blocks.append(f"### {header}\n{hit.get('value', '')}")
    return "\n\n".join(blocks)


def _live_fact_detail(item: dict[str, Any]) -> str:
    hint = item.get("agent_hint") or item.get("error")
    if hint:
        return str(hint)
    data = item.get("data")
    if isinstance(data, dict):
        bits = [f"{key}: {value}" for key, value in list(data.items())[:4]]
        return "; ".join(bits)
    if data is not None:
        return str(data)
    return ""
