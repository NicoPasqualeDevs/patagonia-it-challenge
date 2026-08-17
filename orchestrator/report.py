from __future__ import annotations

from orchestrator.state import ActionResult, FinalReport, Status

HEADLINE: dict[Status, str] = {
    "success": "Cerrado con éxito.",
    "partial": "Cerrado con observaciones.",
    "failed": "No se pudo completar.",
    "running": "En curso.",
}

CONTAINED_HEADLINE = "Cerrado con contención."

STATUS_PHRASE: dict[Status, str] = {
    "success": "se completó con éxito",
    "partial": "se completó en forma parcial",
    "failed": "no se pudo completar",
    "running": "sigue en curso",
}

ACTION_LABEL = {
    "get_weather": "el clima",
    "get_dollar": "el dólar",
    "get_holidays": "los feriados",
    "get_local_time": "la hora local",
    "lookup_food": "los datos del alimento",
    "geocode_address": "la ubicación",
    "execute_agent": "la ejecución del agente",
    "activate_agent": "la activación del agente",
    "create_support_ticket": "un ticket de soporte",
    "lookup_agent": "la búsqueda del agente",
    "create_or_update_agent": "la creación del agente",
    "attach_knowledge": "la carga de conocimiento",
    "enable_capability": "la habilitación de una capacidad",
}


def _is_disabled_skip(action: ActionResult) -> bool:
    output = action.output
    return isinstance(output, dict) and bool(
        output.get("skipped") or output.get("disabled")
    )


def _has_support_ticket(actions: list[ActionResult]) -> bool:
    return any(action.tool == "create_support_ticket" for action in actions)


def _action_phrase(action: ActionResult) -> str:
    label = ACTION_LABEL.get(action.tool, action.tool)
    if _is_disabled_skip(action):
        return f"no se pudo consultar {label} porque esa API está desactivada"
    if action.tool == "create_support_ticket" and action.ok:
        ticket_id = ""
        if isinstance(action.output, dict) and action.output.get("id"):
            ticket_id = f" ({action.output['id']})"
        return f"se abrió {label}{ticket_id} para seguimiento"
    if action.ok:
        return f"se resolvió {label}"
    return f"{label} falló ({action.error or 'error'})"


def compose_summary(
    *,
    status: Status,
    actions: list[ActionResult],
    missing_data: list[str],
) -> str:
    parts: list[str] = [f"El pedido {STATUS_PHRASE.get(status, status)}."]
    phrases = [_action_phrase(action) for action in actions]
    if phrases:
        joined = "; ".join(phrases)
        parts.append(joined[0].upper() + joined[1:] + ".")
    if missing_data:
        parts.append("Faltan datos: " + ", ".join(missing_data) + ".")
    return " ".join(parts)


def build_report(
    *,
    run_id: str,
    work_order_id: str,
    goal: str,
    actions: list[ActionResult],
    missing_data: list[str],
    events: list[dict],
    stopped_reason: str = "",
    contained: bool = False,
) -> FinalReport:
    used_fallback = any(
        a.used_fallback and a.tool != "create_support_ticket" for a in actions
    )
    opened_ticket = _has_support_ticket(actions)
    skipped_actions = [a for a in actions if _is_disabled_skip(a)]
    failed_actions = [
        a
        for a in actions
        if not a.ok and not a.recovered and not _is_disabled_skip(a)
    ]
    status: Status
    recommendation: str
    ticket_note = " Se abrió un ticket de soporte ficticio para seguimiento."

    if missing_data and not [a for a in actions if a.tool != "create_support_ticket"]:
        status = "failed"
        recommendation = (
            stopped_reason
            or "Pedir al requester los datos faltantes y reenviar el work order."
        )
        if opened_ticket:
            recommendation += ticket_note
    elif missing_data and actions:
        status = "partial"
        recommendation = (
            stopped_reason
            or "Completar los datos faltantes y reejecutar los pasos pendientes."
        )
        if opened_ticket:
            recommendation += ticket_note
    elif failed_actions:
        status = "failed"
        recommendation = (
            stopped_reason
            or "Revisar los errores de las acciones fallidas y reintentar el work order."
        )
        if opened_ticket:
            recommendation += ticket_note
    elif skipped_actions:
        status = "partial"
        recommendation = (
            stopped_reason
            or "Alguna API pública estaba desactivada. El resolutor pidió disculpas "
            "por esa porción y continuó con el resto."
        )
        if opened_ticket:
            recommendation += ticket_note
    elif used_fallback:
        status = "partial"
        recommendation = (
            "Hay un ticket de soporte abierto por una falla persistente. "
            "Seguir ese ticket antes de reintentar el paso degradado."
        )
    elif not actions:
        status = "failed"
        recommendation = stopped_reason or "No se planificaron acciones."
    else:
        status = "success"
        recommendation = "No hay siguiente paso operativo. El work order quedó cerrado."

    headline = HEADLINE.get(status, "Listo.")
    if contained and status == "success":
        headline = CONTAINED_HEADLINE
        recommendation = (
            "Se habilitó un agente de reserva (contención). "
            "Soporte queda notificado con un ticket ficticio."
        )
        if opened_ticket:
            recommendation += ticket_note
    elif contained:
        recommendation += " Hubo contención: se activó un agente de reserva."
        if opened_ticket and ticket_note.strip() not in recommendation:
            recommendation += ticket_note

    return FinalReport(
        run_id=run_id,
        work_order_id=work_order_id,
        status=status,
        goal=goal,
        actions=actions,
        missing_data=missing_data,
        recommendation=recommendation,
        summary=compose_summary(
            status=status,
            actions=actions,
            missing_data=missing_data,
        ),
        headline=headline,
        contained=contained,
        events=events,
    )
