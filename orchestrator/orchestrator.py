from __future__ import annotations

import inspect
import time
import uuid
from typing import Any, Callable

from orchestrator.interpreter import Interpretation, interpret_work_order
from orchestrator.logging_setup import Tracer, setup_logging
from orchestrator.planner import plan_actions
from orchestrator.report import build_report
from orchestrator.retry import PermanentError, TransientError, backoff_delay, should_retry
from orchestrator.state import ActionResult, FinalReport, PlannedAction, WorkOrder
from orchestrator.platform import get_store
from orchestrator.public_apis import (
    default_public_tool_args,
    detect_public_tools,
    disabled_tool_fact,
)
from orchestrator.tools import PUBLIC_TOOL_META, PUBLIC_TOOLS, build_tool_handlers

PUBLIC_DECISION_LABEL = {item["name"]: item["label"].lower() for item in PUBLIC_TOOL_META}


def _call_args_for(handler: Callable[..., Any], args: dict[str, Any]) -> dict[str, Any]:
    sig = inspect.signature(handler)
    names = [
        name
        for name, param in sig.parameters.items()
        if param.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    ]
    if names:
        return {key: args[key] for key in names if key in args}
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()):
        return dict(args)
    return {}


def _extract_agent_id(output: Any) -> str | None:
    if not isinstance(output, dict):
        return None
    agent = output.get("agent")
    if isinstance(agent, dict) and agent.get("id"):
        return str(agent["id"])
    if output.get("agent_id"):
        return str(output["agent_id"])
    return None


def _fill_args(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    filled: dict[str, Any] = {}
    for key, value in args.items():
        if value in ("$agent_id", "{{agent_id}}", None) and key == "agent_id":
            filled[key] = context.get("agent_id")
        elif value == "$agent_id":
            filled[key] = context.get("agent_id")
        else:
            filled[key] = value
    if "agent_id" in filled and not filled["agent_id"] and context.get("agent_id"):
        filled["agent_id"] = context["agent_id"]
    return filled


class WorkOrderOrchestrator:
    def __init__(
        self,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        run_id: str | None = None,
    ) -> None:
        setup_logging()
        self.run_id = run_id or uuid.uuid4().hex[:10]
        self.tracer = Tracer(self.run_id, on_event=on_event)
        self.store = get_store()
        self.handlers = build_tool_handlers(self.store)
        self.context: dict[str, Any] = {}
        self.actions: list[ActionResult] = []
        self._handoff_steps: list[PlannedAction] = []

    def run(self, work_order: WorkOrder) -> FinalReport:
        interpretation = self._interpret(work_order)
        if not interpretation.can_proceed:
            return self._finish(
                work_order,
                interpretation,
                missing=interpretation.missing_fields,
                reason=(
                    "Faltan datos críticos: "
                    + ", ".join(interpretation.missing_fields or ["detalle del cliente"])
                    + ". Pedirlos al requester y reenviar."
                ),
            )

        plan = self._plan(interpretation)
        if not plan:
            return self._finish(
                work_order,
                interpretation,
                missing=interpretation.missing_fields,
                reason="El planner no produjo acciones ejecutables.",
            )

        queue = self._commit_queue(plan, interpretation, work_order)
        replans = 0
        while queue:
            step = queue.pop(0)
            decision = self._execute_step(step)
            if self._handoff_steps:
                queue = self._handoff_steps + queue
                self._handoff_steps = []
            if decision == "stop":
                break
            if decision == "replan":
                if replans >= 1:
                    break
                replans += 1
                observation = (
                    f"Contexto actual: {self.context}. "
                    f"Última acción: {self.actions[-1] if self.actions else None}."
                )
                queue = self._commit_queue(
                    self._plan(interpretation, extra_observation=observation),
                    interpretation,
                    work_order,
                )

        return self._finish(work_order, interpretation, missing=interpretation.missing_fields)

    def _interpret(self, work_order: WorkOrder) -> Interpretation:
        self.tracer.emit(
            "interpret",
            thought="Interpretando el work order con el modelo",
        )
        interpretation = interpret_work_order(
            work_order, roster=self.store.list_roster()
        )
        interpretation = self._route_geo(work_order, interpretation)
        self.tracer.emit(
            "interpret",
            thought=interpretation.goal,
            result={
                "entities": interpretation.entities,
                "missing_fields": interpretation.missing_fields,
                "can_proceed": interpretation.can_proceed,
                "notes": interpretation.notes,
                "activate_agent_id": interpretation.activate_agent_id,
                "activate_reason": interpretation.activate_reason,
            },
        )
        candidate = (interpretation.activate_agent_id or "").strip()
        entity_agent = str((interpretation.entities or {}).get("agent_id") or "").strip()
        if candidate:
            self.context["pending_activate_id"] = candidate
            self.context["agent_id"] = candidate
        elif entity_agent:
            self.context["agent_id"] = entity_agent
        if interpretation.can_proceed:
            self.tracer.emit(
                "validate",
                thought="Validación de parámetros exitosa",
                decision="continue",
            )
        else:
            self.tracer.emit(
                "validate",
                thought="Faltan datos críticos",
                result={"missing_fields": interpretation.missing_fields},
                decision="stop",
            )
        return interpretation

    def _plan(
        self, interpretation: Interpretation, extra_observation: str = ""
    ) -> list[PlannedAction]:
        self.tracer.emit("plan", thought="Generando plan de acciones")
        candidate = (interpretation.activate_agent_id or "").strip()
        return plan_actions(
            interpretation,
            extra_observation=extra_observation,
            agent_is_active=self._is_active(candidate),
        )

    def _commit_queue(
        self,
        plan: list[PlannedAction],
        interpretation: Interpretation,
        work_order: WorkOrder,
    ) -> list[PlannedAction]:
        queue = self._with_geo_venues(
            self._with_activation(
                self._with_public_apis(list(plan), interpretation, work_order)
            ),
            work_order,
            interpretation,
        )
        self._emit_decided_plan(queue)
        return queue

    def _agent_label(self, agent_id: str) -> str:
        key = (agent_id or "").strip()
        if not key or key.startswith("$"):
            key = self._attention_agent_id()
        if not key:
            return ""
        try:
            agent = self.store.get_agent(key)
            return str(agent.get("name") or key)
        except PermanentError:
            return key

    def _describe_step(self, step: PlannedAction) -> str:
        if step.tool in PUBLIC_DECISION_LABEL:
            label = PUBLIC_DECISION_LABEL[step.tool]
            if not self.store.is_public_tool_enabled(step.tool):
                return (
                    f"Intentar {label} en {step.tool} "
                    "(desactivada: se avisa al resolutor y el flujo sigue)"
                )
            return f"Conseguir {label} en {step.tool}"
        if step.tool == "activate_agent":
            name = self._agent_label(str((step.args or {}).get("agent_id") or ""))
            if str((step.args or {}).get("role") or "") == "venue":
                text = "No hay locales activos; se habilita uno de reserva para que Dónde Comer recomiende"
                return f"{text} ({name})" if name else text
            text = (
                "Se encontró un recurso en reserva disponible para operar; será habilitado"
            )
            return f"{text} ({name})" if name else text
        if step.tool == "lookup_agent":
            target = str((step.args or {}).get("name_or_id") or "").strip()
            return (
                f"Buscar el agente {target} en lookup_agent"
                if target
                else "Buscar el agente en lookup_agent"
            )
        if step.tool == "execute_agent":
            agent_id = str((step.args or {}).get("agent_id") or "")
            name = self._agent_label(agent_id)
            kind = ""
            key = agent_id if agent_id and not agent_id.startswith("$") else self._attention_agent_id()
            if key:
                try:
                    kind = str(self.store.get_agent(key).get("type") or "")
                except PermanentError:
                    kind = ""
            if kind == "geo":
                text = "Dónde Comer elige el local y redirige el flujo"
                return f"{text} ({name})" if name else text
            if kind == "menu":
                text = "Atender el pedido con el agente de menú"
                return f"{text} ({name})" if name else text
            return "Atender el pedido con el agente resolutor en execute_agent"
        if step.tool == "create_support_ticket":
            return "Escalar a ticket de soporte"
        if step.why:
            return f"{step.why} ({step.tool})"
        return f"Ejecutar {step.tool}"

    def _emit_decided_plan(self, queue: list[PlannedAction]) -> None:
        decisions = [self._describe_step(step) for step in queue]
        self.tracer.emit(
            "plan",
            thought="Plan de acción decidido",
            result={
                "decisions": decisions,
                "actions": [
                    {
                        "tool": step.tool,
                        "args": self._display_args(step),
                        "why": step.why,
                    }
                    for step in queue
                ],
            },
        )

    def _display_args(self, step: PlannedAction) -> dict[str, Any]:
        args = dict(step.args or {})
        agent_id = str(args.get("agent_id") or "").strip()
        name = self._agent_label(agent_id)
        if name:
            args["agent_name"] = name
        return args

    def _attention_agent_id(self, args: dict[str, Any] | None = None) -> str:
        payload = args or {}
        for key in (
            payload.get("agent_id"),
            self.context.get("agent_id"),
            self.context.get("pending_activate_id"),
        ):
            value = (key or "").strip()
            if value:
                return value
        return ""

    def _is_active(self, agent_id: str) -> bool:
        if not agent_id:
            return False
        try:
            return self.store.agent_status(agent_id) == "active"
        except PermanentError:
            return False

    def _public_api_scan_text(
        self, work_order: WorkOrder, interpretation: Interpretation
    ) -> str:
        entities = interpretation.entities or {}
        return " ".join(
            part
            for part in (
                work_order.title,
                work_order.description,
                interpretation.goal,
                str(entities.get("test_message") or ""),
                str(entities.get("client_name") or ""),
            )
            if part
        )

    def _with_public_apis(
        self,
        plan: list[PlannedAction],
        interpretation: Interpretation,
        work_order: WorkOrder,
    ) -> list[PlannedAction]:
        others = [step for step in plan if step.tool not in PUBLIC_TOOLS]
        has_resolver = any(
            step.tool in {"execute_agent", "activate_agent"} for step in others
        )
        if not has_resolver:
            return plan

        text = self._public_api_scan_text(work_order, interpretation)
        agent_id = self._attention_agent_id()
        agent_type = ""
        if agent_id:
            try:
                agent_type = str(self.store.get_agent(agent_id).get("type") or "")
            except PermanentError:
                agent_type = ""

        detected = detect_public_tools(text, agent_type=agent_type)
        planned_public = [step for step in plan if step.tool in PUBLIC_TOOLS]
        planned_names = {step.tool for step in planned_public}
        injected: list[PlannedAction] = []
        for tool in detected:
            if tool in planned_names:
                continue
            disabled = not self.store.is_public_tool_enabled(tool)
            injected.append(
                PlannedAction(
                    tool=tool,
                    args=default_public_tool_args(tool, text, agent_id=agent_id),
                    why=(
                        "Tool desactivada; se informa al resolutor y se continúa"
                        if disabled
                        else "Contexto en vivo para el agente resolutor"
                    ),
                )
            )

        public_steps = planned_public + injected
        if not public_steps:
            return others

        out: list[PlannedAction] = []
        inserted = False
        for step in others:
            if step.tool in {"execute_agent", "activate_agent"} and not inserted:
                out.extend(public_steps)
                inserted = True
            out.append(step)
        if not inserted:
            out.extend(public_steps)
        return out

    def _with_activation(self, plan: list[PlannedAction]) -> list[PlannedAction]:
        attention = self._attention_agent_id()
        out: list[PlannedAction] = []
        inserted = False
        for step in plan:
            if step.tool == "activate_agent":
                args = _fill_args(step.args, self.context)
                agent_id = str((args or {}).get("agent_id") or "").strip() or attention
                if self._is_active(agent_id):
                    continue
                out.append(step)
                if agent_id == attention or not (args or {}).get("role"):
                    inserted = True
                continue
            if step.tool == "execute_agent" and not inserted:
                args = _fill_args(step.args, self.context)
                agent_id = self._attention_agent_id(args)
                if not self._is_active(agent_id):
                    out.append(
                        PlannedAction(
                            tool="activate_agent",
                            args={"agent_id": agent_id or "$agent_id"},
                            why="No hay agente activo; activar al candidato de reserva antes de la atención",
                        )
                    )
                inserted = True
            out.append(step)
        return out

    def _suggestion_text(
        self, work_order: WorkOrder, interpretation: Interpretation
    ) -> str:
        entities = interpretation.entities or {}
        return " ".join(
            part
            for part in (
                work_order.title,
                work_order.description,
                interpretation.goal,
                str(entities.get("test_message") or ""),
            )
            if part
        )

    def _names_specific_venue(self, text: str) -> bool:
        body = (text or "").lower()
        return any(
            name in body
            for name in ("sakura", "lima de barrio", "café andino", "cafe andino", "agt_sakura", "agt_lima", "agt_andino")
        )

    def _is_suggestion_request(self, text: str) -> bool:
        body = (text or "").lower()
        hints = (
            "dónde comer",
            "donde comer",
            "sugerencia",
            "sugeri",
            "recomenda",
            "no sé dónde",
            "no se donde",
            "no se que comer",
            "no sé qué comer",
            "qué local",
            "que local",
            "donde almuerzo",
            "dónde almuerzo",
        )
        return any(hint in body for hint in hints) or "agt_geo" in body

    def _route_geo(
        self, work_order: WorkOrder, interpretation: Interpretation
    ) -> Interpretation:
        geo = self.store.find_by_type("geo")
        if not geo:
            return interpretation
        text = self._suggestion_text(work_order, interpretation)
        already_geo = (interpretation.activate_agent_id or "") == geo["id"]
        wants = self._is_suggestion_request(text)
        if not wants and not already_geo:
            return interpretation
        if (
            self._names_specific_venue(text)
            and not wants
            and not already_geo
        ):
            return interpretation
        interpretation.activate_agent_id = geo["id"]
        interpretation.activate_reason = (
            interpretation.activate_reason
            or "Pedido de sugerencia: Dónde Comer elige un local activo"
        )
        entities = dict(interpretation.entities or {})
        entities["agent_id"] = geo["id"]
        interpretation.entities = entities
        self.context["pending_activate_id"] = geo["id"]
        self.context["agent_id"] = geo["id"]
        return interpretation

    def _targets_geo(self, args: dict[str, Any] | None = None) -> bool:
        agent_id = self._attention_agent_id(args)
        if not agent_id:
            return False
        try:
            return str(self.store.get_agent(agent_id).get("type") or "") == "geo"
        except PermanentError:
            return False

    def _with_geo_venues(
        self,
        plan: list[PlannedAction],
        work_order: WorkOrder,
        interpretation: Interpretation,
    ) -> list[PlannedAction]:
        if not self._targets_geo():
            return plan
        if self.store.list_venues(status="active"):
            return plan
        pick = self.store.pick_reserve_venue(
            self._suggestion_text(work_order, interpretation)
        )
        if not pick:
            return plan
        if any(
            step.tool == "activate_agent"
            and str((step.args or {}).get("agent_id") or "") == pick["id"]
            for step in plan
        ):
            return plan
        injected = PlannedAction(
            tool="activate_agent",
            args={"agent_id": pick["id"], "role": "venue"},
            why="No hay locales activos; habilitar uno de reserva para el flujo de Dónde Comer",
        )
        out: list[PlannedAction] = []
        inserted = False
        for step in plan:
            if (
                not inserted
                and step.tool in {"execute_agent", "activate_agent"}
            ):
                out.append(injected)
                inserted = True
            out.append(step)
        if not inserted:
            out.append(injected)
        return out

    def _match_venue(
        self, venues: list[dict[str, str]], *, agent_id: str, name: str, reply: str
    ) -> dict[str, str] | None:
        wanted_id = (agent_id or "").strip()
        wanted_name = (name or "").strip().lower()
        body = (reply or "").lower()
        for item in venues:
            if wanted_id and item["id"] == wanted_id:
                return item
        for item in venues:
            label = item["name"].lower()
            if wanted_name and (label == wanted_name or wanted_name in label):
                return item
        for item in venues:
            label = item["name"].lower()
            if label and label in body:
                return item
        return None

    def _resolve_menu_handoff(self, output: dict[str, Any]) -> dict[str, str] | None:
        wanted_id = str(output.get("handoff_agent_id") or "").strip()
        wanted_name = str(
            output.get("handoff_agent_name") or output.get("venue_name") or ""
        ).strip()
        reply = str(output.get("reply") or "")
        active = self.store.list_venues(status="active")
        all_venues = self.store.list_venues()
        picked = self._match_venue(
            active, agent_id=wanted_id, name=wanted_name, reply=reply
        ) or self._match_venue(
            all_venues, agent_id=wanted_id, name=wanted_name, reply=reply
        )
        if picked:
            return picked
        if active:
            return active[0]
        return self.store.pick_reserve_venue(" ".join(part for part in (reply, wanted_name) if part))

    def _queue_menu_handoff(
        self, step: PlannedAction, args: dict[str, Any], output: Any
    ) -> bool:
        if step.tool != "execute_agent":
            return False
        if self.context.get("geo_handoff_done"):
            return False
        if not self._targets_geo(args):
            return False
        if not isinstance(output, dict) or not output.get("delivered"):
            return False
        venue = self._resolve_menu_handoff(output)
        if not venue:
            return False
        self.context["geo_handoff_done"] = True
        self.context["agent_id"] = venue["id"]
        steps: list[PlannedAction] = []
        if not self._is_active(venue["id"]):
            steps.append(
                PlannedAction(
                    tool="activate_agent",
                    args={"agent_id": venue["id"]},
                    why=f"Dónde Comer redirige a {venue['name']}; habilitar el local de menú",
                )
            )
        message = str((args or {}).get("message") or "").strip()
        self.context.setdefault("live_facts", []).append(
            {
                "tool": "geo_handoff",
                "ok": True,
                "source": "agt_geo",
                "data": {
                    "from_agent": "Dónde Comer",
                    "venue_id": venue["id"],
                    "venue_name": venue["name"],
                    "reason": str(output.get("reply") or ""),
                },
                "agent_hint": (
                    f"Dónde Comer te derivó este pedido a {venue['name']}. "
                    "Atendé la carta; no redirijas de nuevo."
                ),
            }
        )
        steps.append(
            PlannedAction(
                tool="execute_agent",
                args={"agent_id": venue["id"], "message": message},
                why=f"Redirigir el flujo al agente de menú {venue['name']}",
            )
        )
        self._handoff_steps = steps
        return True

    def _is_venue_role(self, args: dict[str, Any] | None) -> bool:
        return str((args or {}).get("role") or "") == "venue"

    def _execute_activate(self, step: PlannedAction, args: dict[str, Any]) -> str:
        error = "no hay agente activo para la atención"
        is_venue = self._is_venue_role(args)
        agent_id = str((args or {}).get("agent_id") or "").strip()
        if not is_venue:
            agent_id = self._attention_agent_id(args)
        self.tracer.emit(
            "execute",
            thought=step.why or "Activar agente de reserva",
            tool="activate_agent",
            args=args,
        )
        if not agent_id:
            self.tracer.emit(
                "observe",
                thought="Fallo en la atención: no hay agente activo",
                tool="activate_agent",
                args=args,
                error=error,
                decision="fallback",
            )
            self.actions.append(
                ActionResult(tool="activate_agent", args=args, ok=False, error=error)
            )
            return self._fallback(step, args, error, attempts=1, already_recorded=True)

        if self._is_active(agent_id):
            agent = self.store.get_agent(agent_id)
            if not is_venue:
                self.context["agent_id"] = agent["id"]
            self.actions.append(
                ActionResult(
                    tool="activate_agent",
                    args=args,
                    ok=True,
                    output={"agent_id": agent["id"], "agent_name": agent["name"], "status": "active", "role": args.get("role")},
                )
            )
            self.tracer.emit(
                "observe",
                thought=f"{agent['name']} ya estaba activo",
                tool="activate_agent",
                result={"agent_id": agent["id"], "agent_name": agent["name"], "status": "active"},
            )
            self.tracer.emit("decide", thought="Seguir con el siguiente paso", decision="continue")
            return "continue"

        self._activate(
            agent_id,
            (
                "local de reserva para que Dónde Comer pueda recomendar"
                if is_venue
                else "estaba en reserva; se habilita para la atención"
            ),
            as_resolver=not is_venue,
        )
        if not self._is_active(agent_id):
            self.actions.append(
                ActionResult(tool="activate_agent", args=args, ok=False, error=error)
            )
            self.tracer.emit(
                "observe",
                thought="No se pudo activar un agente de reserva",
                tool="activate_agent",
                args=args,
                error=error,
                decision="fallback",
            )
            return self._fallback(step, args, error, attempts=1, already_recorded=True)

        agent = self.store.get_agent(agent_id)
        role = "venue" if is_venue else args.get("role")
        self.actions.append(
            ActionResult(
                tool="activate_agent",
                args=args,
                ok=True,
                output={"agent_id": agent["id"], "agent_name": agent["name"], "status": "active", "role": role},
            )
        )
        self.tracer.emit(
            "observe",
            thought=(
                f"Local de reserva listo: {agent['name']}"
                if is_venue
                else f"{agent['name']} pasó de reserva a activo"
            ),
            tool="activate_agent",
            result={"agent_id": agent["id"], "agent_name": agent["name"], "status": "active", "role": role},
        )
        self.tracer.emit(
            "decide",
            thought="Seguir con Dónde Comer" if is_venue else "Seguir con execute_agent",
            decision="continue",
        )
        return "continue"

    def _activate(
        self, agent_id: str | None, reason: str = "", *, as_resolver: bool = True
    ) -> None:
        key = (agent_id or "").strip()
        if not key:
            return
        try:
            already = self.store.agent_status(key) == "active"
            agent = self.store.activate_agent(key)
        except PermanentError:
            return
        if as_resolver:
            self.context["agent_id"] = agent["id"]
        if already:
            return
        self.context["contained"] = True
        detail = f". {reason}" if reason else ""
        self.tracer.emit(
            "observe",
            thought=f"pasó a activo: {agent['name']}{detail}",
            result={
                "agent_id": agent["id"],
                "name": agent["name"],
                "agent_name": agent["name"],
                "status": "active",
                "reason": reason,
            },
            decision="continue",
        )

    def _execute_step(self, step: PlannedAction) -> str:
        args = _fill_args(step.args, self.context)
        if step.tool in {
            "execute_agent",
            "activate_agent",
            "lookup_agent",
            "enable_capability",
            "attach_knowledge",
            "create_or_update_agent",
        }:
            name = self._agent_label(str((args or {}).get("agent_id") or ""))
            if name:
                args = {**args, "agent_name": name}
        if step.tool in PUBLIC_TOOLS and not self.store.is_public_tool_enabled(step.tool):
            label = PUBLIC_DECISION_LABEL.get(step.tool, step.tool)
            unavailable = disabled_tool_fact(step.tool)
            self.context.setdefault("live_facts", []).append(
                {"tool": step.tool, **unavailable}
            )
            self.actions.append(
                ActionResult(
                    tool=step.tool,
                    args=args,
                    ok=False,
                    error=str(unavailable["error"]),
                    output=unavailable,
                )
            )
            self.tracer.emit(
                "execute",
                thought=f"{step.tool} está desactivada",
                tool=step.tool,
                args=args,
            )
            self.tracer.emit(
                "observe",
                thought=f"No se pudo obtener {label}: tool desactivada. El flujo continúa.",
                tool=step.tool,
                args=args,
                error=str(unavailable["error"]),
                result=unavailable,
                decision="continue",
            )
            self.tracer.emit(
                "decide",
                thought="Seguir y avisar al agente resolutor que falta esa porción",
                decision="continue",
            )
            return "continue"
        if step.tool == "activate_agent":
            return self._execute_activate(step, args)
        handler = self.handlers.get(step.tool)
        if handler is None:
            result = ActionResult(
                tool=step.tool,
                args=args,
                ok=False,
                error=f"tool desconocida: {step.tool}",
            )
            self.actions.append(result)
            self.tracer.emit(
                "execute",
                thought=step.why,
                tool=step.tool,
                args=args,
                error=result.error,
                decision="stop",
            )
            return "stop"

        if step.tool == "execute_agent":
            live = list(self.context.get("live_facts") or [])
            if self._targets_geo(args):
                venues = self.store.list_venues(status="active")
                names = ", ".join(item["name"] for item in venues) or "(ninguno)"
                live.append(
                    {
                        "tool": "venue_roster",
                        "ok": True,
                        "source": "duty",
                        "data": {
                            "active_venues": [
                                {
                                    "id": item["id"],
                                    "name": item["name"],
                                    "goal": item.get("goal") or "",
                                }
                                for item in venues
                            ],
                            "rule": (
                                "Recomendá UN solo local de esta lista. "
                                "No inventes restaurantes ni uses locales en reserva."
                            ),
                        },
                        "agent_hint": f"Locales activos para recomendar: {names}",
                    }
                )
            args = {**args, "live_context": live}

        self.tracer.emit(
            "execute",
            thought=step.why or f"Ejecutando {step.tool}",
            tool=step.tool,
            args=args,
        )

        if step.tool == "execute_agent":
            agent_id = self._attention_agent_id(args)
            if agent_id and not self._is_active(agent_id):
                self._activate(agent_id, "estaba en reserva; se habilita para ejecutar")
            if not self._is_active(agent_id):
                error = "no hay agente activo para la atención"
                self.tracer.emit(
                    "observe",
                    thought="Fallo en la atención: no hay agente activo ni en reserva",
                    tool=step.tool,
                    args=args,
                    error=error,
                    decision="fallback",
                )
                self.actions.append(
                    ActionResult(tool=step.tool, args=args, ok=False, error=error)
                )
                return self._fallback(
                    step, args, error, attempts=1, already_recorded=True
                )

        call_args = _call_args_for(handler, args)
        max_attempts = 3
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                output = handler(**call_args)
                action = ActionResult(
                    tool=step.tool,
                    args=args,
                    ok=True,
                    output=output,
                    attempts=attempt,
                )
                self.actions.append(action)
                if step.tool in PUBLIC_TOOLS and isinstance(output, dict):
                    facts = self.context.setdefault("live_facts", [])
                    facts.append({"tool": step.tool, **output})
                agent_id = _extract_agent_id(output)
                handed_off = self._queue_menu_handoff(step, args, output)
                if agent_id and not handed_off:
                    self.context["agent_id"] = agent_id
                    if step.tool == "create_or_update_agent" or (
                        step.tool == "lookup_agent"
                        and isinstance(output, dict)
                        and output.get("found")
                    ):
                        self.context["pending_activate_id"] = agent_id
                self.tracer.emit(
                    "observe",
                    thought=f"{step.tool} ok en {attempt} intento(s)",
                    tool=step.tool,
                    args=args,
                    result=output,
                )
                if (
                    step.tool == "lookup_agent"
                    and isinstance(output, dict)
                    and not output.get("found")
                ):
                    self.tracer.emit(
                        "decide",
                        thought="El agente no existe; el resto del plan debe crear uno",
                        tool=step.tool,
                        result=output,
                        decision="replan",
                    )
                    return "replan"
                if handed_off:
                    venue_id = str(self.context.get("agent_id") or "")
                    venue_name = self._agent_label(venue_id) or venue_id
                    self.tracer.emit(
                        "decide",
                        thought=f"Dónde Comer redirige el flujo a {venue_name}",
                        decision="continue",
                        result={"handoff_agent_id": venue_id},
                    )
                    return "continue"
                self.tracer.emit(
                    "decide", thought="Seguir con el siguiente paso", decision="continue"
                )
                return "continue"
            except Exception as exc:
                last_error = exc
                retryable = should_retry(exc) and attempt < max_attempts
                self.tracer.emit(
                    "observe",
                    thought=(
                        f"Intento {attempt}/{max_attempts} falló; reintento"
                        if retryable
                        else f"Intento {attempt}/{max_attempts} falló"
                    ),
                    tool=step.tool,
                    args=args,
                    error=str(exc),
                    decision="retry" if retryable else None,
                )
                if retryable:
                    time.sleep(backoff_delay(attempt + 1))
                    continue
                break

        assert last_error is not None
        if isinstance(last_error, TransientError):
            return self._fallback(step, args, str(last_error), attempts=max_attempts)
        action = ActionResult(
            tool=step.tool,
            args=args,
            ok=False,
            error=str(last_error),
        )
        self.actions.append(action)
        if step.tool in {"execute_agent", "enable_capability", "attach_knowledge"}:
            return self._fallback(step, args, str(last_error), attempts=1, already_recorded=True)
        self.tracer.emit("decide", thought="Abortar: error permanente", decision="stop")
        return "stop"

    def _fallback(
        self,
        step: PlannedAction,
        args: dict[str, Any],
        error: str,
        *,
        attempts: int,
        already_recorded: bool = False,
    ) -> str:
        self.tracer.emit(
            "observe",
            thought="Falla persistente: se degrada el paso y el escalado queda para el final",
            tool=step.tool,
            args=args,
            error=error,
            decision="fallback",
        )
        if not already_recorded:
            self.actions.append(
                ActionResult(
                    tool=step.tool,
                    args=args,
                    ok=False,
                    error=error,
                    attempts=attempts,
                    used_fallback=True,
                )
            )
        else:
            self.actions[-1].used_fallback = True
        self.tracer.emit(
            "decide",
            thought="Continuar; si el reporte interno tiene fallo se abre un ticket al cierre",
            decision="continue",
        )
        return "continue"

    def _has_support_ticket(self) -> bool:
        return any(action.tool == "create_support_ticket" for action in self.actions)

    def _escalate_to_support(
        self, report: FinalReport, *, contained: bool = False
    ) -> None:
        if self._has_support_ticket():
            return
        if contained and report.status == "success":
            summary = (
                f"Notificación de contención del work order {report.work_order_id}: "
                "se habilitó un agente que estaba en reserva para completar la atención."
            )
            thought = "Hubo contención; se notifica a soporte con un ticket ficticio"
        else:
            failures = [
                action
                for action in self.actions
                if not action.ok and not action.recovered
            ]
            details = [f"{action.tool}: {action.error or 'fallo'}" for action in failures]
            if report.missing_data:
                details.append("datos faltantes: " + ", ".join(report.missing_data))
            if contained:
                details.append("contención: se activó un agente de reserva")
            summary = (
                f"Escalado automático del work order {report.work_order_id} "
                f"(estado {report.status}). "
                + ("; ".join(details) or report.recommendation)
            )
            thought = "El reporte interno tuvo un fallo; se escala a soporte"
        ticket_args = {
            "summary": summary,
            "agent_id": self.context.get("agent_id"),
        }
        self.tracer.emit(
            "execute",
            thought=thought,
            tool="create_support_ticket",
            args=ticket_args,
        )
        ticket = self.handlers["create_support_ticket"](**ticket_args)
        self.actions.append(
            ActionResult(
                tool="create_support_ticket",
                args=ticket_args,
                ok=True,
                output=ticket,
                used_fallback=True,
            )
        )
        self.tracer.emit(
            "observe",
            thought=f"Ticket ficticio {ticket.get('id')} abierto. El flujo cierra con este escalado.",
            tool="create_support_ticket",
            args=ticket_args,
            result=ticket,
            decision="continue",
        )
        self.tracer.emit(
            "decide",
            thought="Escalado de soporte listo; emitir el reporte final",
            decision="continue",
        )

    def _finish(
        self,
        work_order: WorkOrder,
        interpretation: Interpretation,
        *,
        missing: list[str],
        reason: str = "",
    ) -> FinalReport:
        contained = bool(self.context.get("contained"))
        report = build_report(
            run_id=self.run_id,
            work_order_id=work_order.id,
            goal=interpretation.goal,
            actions=self.actions,
            missing_data=missing or [],
            events=[],
            stopped_reason=reason,
            contained=contained,
        )
        if report.status in {"failed", "partial"} or contained:
            self._escalate_to_support(report, contained=contained)
            report = build_report(
                run_id=self.run_id,
                work_order_id=work_order.id,
                goal=interpretation.goal,
                actions=self.actions,
                missing_data=missing or [],
                events=[],
                stopped_reason=reason,
                contained=contained,
            )
        payload = report.to_dict()
        payload.pop("events", None)
        self.tracer.emit(
            "report",
            thought=report.headline or f"Estado final: {report.status}",
            result=payload,
            decision="stop",
        )
        report.events = list(self.tracer.events)
        return report
