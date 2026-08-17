from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from orchestrator.interpreter import Interpretation
from orchestrator.llm import get_llm
from orchestrator.state import PlannedAction
from orchestrator.tools import PUBLIC_API_HINTS, PUBLIC_TOOL_META, catalog_for_prompt, disabled_public_tools


class PlannedActionModel(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    why: str = ""


class PlanModel(BaseModel):
    rationale: str = ""
    actions: list[PlannedActionModel]


PLAN_SYSTEM = """Sos el planner de un orquestador de acciones.
Dado un work order interpretado y el catálogo de tools, devolvé una lista ORDENADA de acciones.
Reglas:
- Usá SOLO tools del catálogo.
- Si hay que crear un agente y después operar sobre él, primero create_or_update_agent.
- En pasos posteriores usá agent_id="$agent_id" para que el runtime inyecte el id resuelto.
- Si el cliente ya podría existir (se menciona un nombre conocido o un id), primero lookup_agent.
- Si activated_agent_id está presente, usá ese agente y no crees un duplicado.
- Si agent_is_active es true, ese agente ya está de turno: NO agregues activate_agent.
- execute_agent SOLO va a un agente activo. Si agent_is_active es false, no lo pongas como primer paso: el runtime activará antes de atender.
- Si activated_agent_id es un agente type=geo (Dónde Comer), un solo execute_agent va a ESE agente.
  El runtime redirige después al local de menú elegido. No planées un segundo execute_agent.
{api_rules}
- El runtime inyecta esos resultados al chat; no hace falta copiarlos en el message.
- No agregues create_support_ticket en el plan inicial; es fallback del runtime.
- No inventes agent_id concretos salvo que vengan en las entidades o en activated_agent_id.
- Sé concreto y corto: el mínimo de pasos para cumplir el objetivo."""


def _api_rules() -> str:
    disabled = disabled_public_tools()
    hints = [
        PUBLIC_API_HINTS[item["name"]]
        for item in PUBLIC_TOOL_META
        if item["name"] not in disabled and item["name"] in PUBLIC_API_HINTS
    ]
    lines = [
        "- APIs públicas (sin key): llamalas ANTES de execute_agent si el pedido lo pide "
        "y la tool está en el catálogo."
    ]
    lines.extend(f"  * {hint}" for hint in hints)
    if disabled:
        names = ", ".join(sorted(disabled))
        lines.append(
            f"- Estas APIs están desactivadas: {names}. "
            "Si el pedido las necesita, incluí igual el paso. "
            "El runtime fallará ese nodo, avisará al resolutor y seguirá."
        )
    if not hints and not disabled:
        return (
            "- No hay APIs públicas habilitadas. No las llames aunque el pedido las pida."
        )
    return "\n".join(lines)


def plan_actions(
    interpretation: Interpretation,
    extra_observation: str = "",
    *,
    agent_is_active: bool = False,
) -> list[PlannedAction]:
    llm = get_llm().with_structured_output(PlanModel, method="function_calling")
    user = {
        "goal": interpretation.goal,
        "entities": interpretation.entities,
        "notes": interpretation.notes,
        "activated_agent_id": interpretation.activate_agent_id,
        "activate_reason": interpretation.activate_reason,
        "agent_is_active": agent_is_active,
        "tools": catalog_for_prompt(),
        "observation": extra_observation or None,
    }
    plan: PlanModel = llm.invoke(
        [
            {"role": "system", "content": PLAN_SYSTEM.format(api_rules=_api_rules())},
            {"role": "user", "content": str(user)},
        ]
    )
    return [
        PlannedAction(tool=a.tool, args=dict(a.args or {}), why=a.why)
        for a in plan.actions
    ]
