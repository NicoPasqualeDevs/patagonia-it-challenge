from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from orchestrator.llm import get_llm
from orchestrator.state import WorkOrder
from orchestrator.tools import catalog_for_prompt


class Interpretation(BaseModel):
    goal: str = Field(description="Objetivo operativo en una frase")
    entities: dict[str, Any] = Field(
        default_factory=dict,
        description="Entidades extraídas: client_name, agent_id, capabilities, topics, test_message, etc.",
    )
    missing_fields: list[str] = Field(default_factory=list)
    can_proceed: bool = Field(
        description="False si faltan datos críticos para ejecutar cualquier acción útil"
    )
    notes: str = ""
    activate_agent_id: str | None = Field(
        default=None,
        description="Id de un agente del roster a promover a activo, o null si ninguno encaja",
    )
    activate_reason: str = Field(
        default="",
        description="Por qué el nombre o el goal del agente matchea el work order",
    )


INTERPRET_SYSTEM = """Sos un analista de operaciones de una plataforma de agentes de atención.
Interpretá el work order y extraé un objetivo claro y entidades concretas.
No inventes ids ni nombres de cliente que no estén en el texto.
Datos críticos para proceder: al menos un nombre de cliente/agente, o un agent_id, o suficiente detalle para crear un agente nuevo.
Si el pedido es habilitar algo (reservas, carrito, contacto) sin identificar a quién, can_proceed=false y listá missing_fields.

Hay un pool de agentes. Cada uno tiene id, name, goal, type (menu, nutrition, geo) y status (active|reserve).
Si el usuario no sabe dónde comer, pide sugerencia, recomendación de local o similar —
y NO nombra un local concreto — activate_agent_id debe ser el agente type=geo (Dónde Comer).
Ese agente elige entre locales de menú activos.
Si el work order nombra un local o encaja con UN agente de menú/nutrición, usá ese id.
Si ninguno encaja, activate_agent_id=null; el flujo podrá crear uno nuevo.
Respondé solo con el schema pedido."""


def interpret_work_order(
    work_order: WorkOrder,
    roster: list[dict[str, Any]] | None = None,
) -> Interpretation:
    llm = get_llm().with_structured_output(Interpretation, method="function_calling")
    payload = {
        "id": work_order.id,
        "title": work_order.title,
        "description": work_order.description,
        "requester": work_order.requester,
        "priority": work_order.priority,
        "context": work_order.context,
        "reserve_roster": roster or [],
        "tools": catalog_for_prompt(),
    }
    return llm.invoke(
        [
            {"role": "system", "content": INTERPRET_SYSTEM},
            {"role": "user", "content": str(payload)},
        ]
    )
