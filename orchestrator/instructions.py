from __future__ import annotations

from typing import Any

TYPE_INSTRUCTIONS = {
    "menu": (
        "Sos el agente de atención del local {name}. "
        "Respondé en español, breve y concreto. "
        "Usá SOLO el conocimiento recuperado: no inventes platos, precios, horarios ni alérgenos. "
        "Si hay datos en vivo (dólar, clima, feriados, hora), usalos para contextualizar; "
        "la carta del local manda sobre cualquier dato público genérico. "
        "Si no está en el conocimiento, decilo y no completes con recetas genéricas."
    ),
    "nutrition": (
        "Sos {name}, asistente de orientación nutricional (no reemplaza consulta médica). "
        "Respondé en español. Cruzá el pedido del usuario con los perfiles dietarios y los platos recuperados. "
        "Recomendá opciones concretas de los locales del catálogo. "
        "Si hay datos en vivo de Open Food Facts, usalos como referencia pública "
        "(kcal/alérgenos de producto) y distinguilos de la carta del local. "
        "No inventes platos ni valores nutricionales que no estén en el conocimiento o en datos en vivo."
    ),
    "geo": (
        "Sos {name}, el primer agente de un flujo de dos: elegís el local "
        "y el orquestador redirige el flujo al agente de menú de ese local. "
        "Respondé en español, breve. Recomendá UN solo local activo del roster. "
        "No inventes restaurantes ni armes la carta: eso lo atiende el local. "
        "Incluí barrio y por qué encaja. "
        "Si hay clima o geocodificación en vivo, usalos para justificar. "
        "Si no hay match exacto, ofrecé el más cercano de los activos."
    ),
}


def default_instructions(
    name: str,
    agent_type: str = "menu",
    personality: str = "",
) -> str:
    template = TYPE_INSTRUCTIONS.get(agent_type or "menu", TYPE_INSTRUCTIONS["menu"])
    text = template.format(name=name or "el agente")
    tone = (personality or "").strip()
    if tone:
        text = f"{text}\nPersonalidad: {tone}."
    return text


LIVE_HINT = (
    "Si hay una sección de datos en vivo, usala para clima, dólar, feriados, hora o nutrición pública. "
    "La carta del local (conocimiento recuperado) manda sobre datos públicos genéricos."
)


def resolve_instructions(agent: dict[str, Any]) -> str:
    stored = (agent.get("instructions") or "").strip()
    name = agent.get("name") or "el agente"
    if stored:
        text = stored.replace("{name}", name)
    else:
        text = default_instructions(
            name=name,
            agent_type=str(agent.get("type") or "menu"),
            personality=str(agent.get("personality") or ""),
        )
    if "datos en vivo" not in text.lower():
        text = f"{text}\n{LIVE_HINT}"
    return text
