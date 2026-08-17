from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any

from orchestrator.retry import PermanentError
from orchestrator.seed import seed_agents
from orchestrator.instructions import default_instructions

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "platform.json"
AGENT_TYPES = ("menu", "nutrition", "geo")
INITIAL_RESERVE_IDS = frozenset({"agt_lima", "agt_andino"})


def normalize_ktag_name(name: str) -> str:
    cleaned = (name or "").strip().replace(" ", "_")
    if not cleaned:
        raise PermanentError("el ktag requiere name")
    return cleaned


def new_ktag(name: str, value: str, ktag_id: str | None = None) -> dict[str, str]:
    return {
        "id": ktag_id or f"kt_{uuid.uuid4().hex[:8]}",
        "name": normalize_ktag_name(name),
        "value": (value or "").strip(),
    }


def _knowledge_names(agent: dict[str, Any]) -> list[str]:
    return [k["name"] for k in agent.get("ktags") or []]


def public_agent(agent: dict[str, Any], *, status: str | None = None) -> dict[str, Any]:
    payload = {
        "id": agent["id"],
        "name": agent["name"],
        "type": agent.get("type") or "menu",
        "goal": agent.get("goal") or "",
        "personality": agent.get("personality") or "",
        "instructions": agent.get("instructions") or "",
        "capabilities": list(agent.get("capabilities") or []),
        "ktags": [dict(k) for k in agent.get("ktags") or []],
        "knowledge": _knowledge_names(agent),
    }
    if status is not None:
        payload["status"] = status
    return payload


class PlatformStore:
    """Registro de agentes y ktags, persistido en JSON y compartido por API y orquestador."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DATA_PATH
        self._lock = threading.Lock()
        self.agents: dict[str, dict[str, Any]] = {}
        self.tickets: list[dict[str, Any]] = []
        self._ktag_listeners: list[Any] = []
        self._active_ids: set[str] = set()
        self.public_tools: dict[str, bool] = {}
        self._load_or_seed()

    def on_ktags_changed(self, callback: Any) -> None:
        self._ktag_listeners.append(callback)

    def _notify_ktags(self) -> None:
        for callback in self._ktag_listeners:
            callback()

    def _load_or_seed(self) -> None:
        seeded = seed_agents()
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            loaded = raw.get("agents") or {}
            self.agents = {aid: self._migrate_agent(agent) for aid, agent in loaded.items()}
            self.tickets = list(raw.get("tickets") or [])
            self.public_tools = self._normalize_public_tools(raw.get("public_tools"))
            for aid, agent in seeded.items():
                if aid not in self.agents:
                    self.agents[aid] = agent
            self._active_ids = self._default_active_ids()
            self._save()
            return
        self.agents = seeded
        self.tickets = []
        self.public_tools = self._default_public_tools()
        self._active_ids = self._default_active_ids()
        self._save()

    def _migrate_agent(self, agent: dict[str, Any]) -> dict[str, Any]:
        migrated = dict(agent)
        migrated.setdefault("type", "menu")
        migrated.setdefault("goal", "")
        migrated.setdefault("personality", "")
        if not (migrated.get("instructions") or "").strip():
            migrated["instructions"] = default_instructions(
                name=str(migrated.get("name") or ""),
                agent_type=str(migrated.get("type") or "menu"),
                personality=str(migrated.get("personality") or ""),
            )
        migrated.setdefault("capabilities", [])
        migrated.pop("status", None)
        if "ktags" not in migrated:
            topics = migrated.get("knowledge") or []
            migrated["ktags"] = [
                new_ktag(str(topic), str(topic)) for topic in topics if topic
            ]
        migrated["knowledge"] = _knowledge_names(migrated)
        return migrated

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "agents": {aid: public_agent(agent) for aid, agent in self.agents.items()},
            "tickets": self.tickets,
            "public_tools": dict(self.public_tools),
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _default_public_tools(self) -> dict[str, bool]:
        from orchestrator.tools import PUBLIC_TOOLS

        return {name: True for name in PUBLIC_TOOLS}

    def _normalize_public_tools(self, raw: Any) -> dict[str, bool]:
        flags = self._default_public_tools()
        if isinstance(raw, dict):
            for key, value in raw.items():
                name = str(key).strip()
                if name in flags:
                    flags[name] = bool(value)
        return flags

    def disabled_public_tools(self) -> set[str]:
        with self._lock:
            return {name for name, enabled in self.public_tools.items() if not enabled}

    def is_public_tool_enabled(self, name: str) -> bool:
        key = (name or "").strip()
        with self._lock:
            return bool(self.public_tools.get(key, True))

    def set_public_tool_enabled(self, name: str, enabled: bool) -> dict[str, bool]:
        key = (name or "").strip()
        if not key:
            raise PermanentError("la tool requiere name")
        with self._lock:
            self.public_tools[key] = bool(enabled)
            self._save()
            return dict(self.public_tools)

    def list_roster(self) -> list[dict[str, str]]:
        with self._lock:
            items = [
                {
                    "id": agent["id"],
                    "name": agent["name"],
                    "goal": agent.get("goal") or "",
                    "type": str(agent.get("type") or "menu"),
                    "status": self._status_unlocked(agent["id"]),
                }
                for agent in self.agents.values()
            ]
        items.sort(key=lambda a: a["name"].lower())
        return items

    def find_by_type(self, agent_type: str) -> dict[str, Any] | None:
        wanted = (agent_type or "").strip().lower()
        with self._lock:
            for agent in self.agents.values():
                if str(agent.get("type") or "").lower() == wanted:
                    return self._public(agent)
        return None

    def list_venues(self, *, status: str | None = None) -> list[dict[str, str]]:
        with self._lock:
            items = []
            for agent in self.agents.values():
                if str(agent.get("type") or "menu") != "menu":
                    continue
                current = self._status_unlocked(agent["id"])
                if status and current != status:
                    continue
                items.append(
                    {
                        "id": agent["id"],
                        "name": agent["name"],
                        "goal": str(agent.get("goal") or ""),
                        "status": current,
                    }
                )
            return items

    def pick_reserve_venue(self, hint: str = "") -> dict[str, str] | None:
        reserved = self.list_venues(status="reserve")
        if not reserved:
            return None
        body = (hint or "").lower()
        keyed = {item["id"]: item for item in reserved}
        if any(word in body for word in ("peru", "lima", "ceviche", "causa")) and "agt_lima" in keyed:
            return keyed["agt_lima"]
        if any(word in body for word in ("japon", "sushi", "ramen", "sakura", "nigiri")) and "agt_sakura" in keyed:
            return keyed["agt_sakura"]
        if any(word in body for word in ("cafe", "café", "andino", "medialuna")) and "agt_andino" in keyed:
            return keyed["agt_andino"]
        return reserved[0]

    def _default_active_ids(self) -> set[str]:
        return {aid for aid in self.agents if aid not in INITIAL_RESERVE_IDS}

    def reset_duty(self) -> None:
        with self._lock:
            self._active_ids = self._default_active_ids()

    def activate_agent(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            self._active_ids.add(agent["id"])
            return public_agent(agent, status="active")

    def deactivate_agent(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            self._active_ids.discard(agent["id"])
            return public_agent(agent, status="reserve")

    def update_agent(
        self,
        agent_id: str,
        *,
        goal: str | None = None,
        instructions: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            profile_changed = False
            if goal is not None:
                cleaned = goal.strip()
                if not cleaned:
                    raise PermanentError("la descripción no puede estar vacía")
                agent["goal"] = cleaned
                profile_changed = True
            if instructions is not None:
                cleaned = instructions.strip()
                if not cleaned:
                    raise PermanentError("las instrucciones no pueden estar vacías")
                agent["instructions"] = cleaned
            self._save()
            snapshot = self._public(agent)
        if profile_changed:
            self._notify_ktags()
        return snapshot

    def agent_status(self, agent_id: str) -> str:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            return self._status_unlocked(agent["id"])

    def require_active(self, agent_id: str) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        if agent.get("status") != "active":
            raise PermanentError(
                f"{agent['name']} está en reserva. "
                "Ejecutá un work order que lo active para poder chatear."
            )
        return agent

    def _status_unlocked(self, agent_id: str) -> str:
        return "active" if agent_id in self._active_ids else "reserve"

    def _public(self, agent: dict[str, Any]) -> dict[str, Any]:
        return public_agent(agent, status=self._status_unlocked(agent["id"]))

    def list_agents(self) -> list[dict[str, Any]]:
        with self._lock:
            items = [self._public(agent) for agent in self.agents.values()]
        order = {"menu": 0, "nutrition": 1, "geo": 2}
        items.sort(key=lambda a: (order.get(a["type"], 9), a["name"].lower()))
        return [
            {
                "id": a["id"],
                "name": a["name"],
                "type": a["type"],
                "goal": a["goal"],
                "personality": a["personality"],
                "ktag_count": len(a["ktags"]),
                "capabilities": a["capabilities"],
                "status": a["status"],
            }
            for a in items
        ]

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        with self._lock:
            return self._public(self._require_agent_unlocked(agent_id))

    def lookup_agent(self, name_or_id: str) -> dict[str, Any]:
        key = (name_or_id or "").strip()
        if not key:
            raise PermanentError("lookup_agent requiere name_or_id")
        with self._lock:
            if key in self.agents:
                return {"found": True, "agent": self._public(self.agents[key])}
            lowered = key.lower()
            for agent in self.agents.values():
                if agent["name"].lower() == lowered:
                    return {"found": True, "agent": self._public(agent)}
        return {"found": False, "agent": None, "query": key}

    def create_or_update_agent(
        self,
        name: str,
        goal: str = "",
        personality: str = "",
        type: str = "",
        agent_type: str = "",
    ) -> dict[str, Any]:
        if not (name or "").strip():
            raise PermanentError("create_or_update_agent requiere name")
        resolved_type = (type or agent_type or "menu").strip().lower()
        if resolved_type not in AGENT_TYPES:
            raise PermanentError(f"type inválido: {resolved_type}. Usar {list(AGENT_TYPES)}")
        existing = self.lookup_agent(name)
        with self._lock:
            if existing.get("found"):
                agent = self.agents[existing["agent"]["id"]]
                if goal:
                    agent["goal"] = goal
                if personality:
                    agent["personality"] = personality
                if type or agent_type:
                    agent["type"] = resolved_type
                self._save()
                return {"created": False, "agent": self._public(agent)}
            agent_id = f"agt_{uuid.uuid4().hex[:8]}"
            agent = {
                "id": agent_id,
                "name": name.strip(),
                "type": resolved_type,
                "goal": goal or "Atender consultas del cliente",
                "personality": personality or "profesional y breve",
                "instructions": default_instructions(
                    name.strip(),
                    resolved_type,
                    personality or "profesional y breve",
                ),
                "ktags": [],
                "capabilities": [],
            }
            self.agents[agent_id] = agent
            self._active_ids.add(agent_id)
            self._save()
            return {"created": True, "agent": self._public(agent)}

    def attach_knowledge(
        self,
        agent_id: str,
        topics: list[Any] | None = None,
        ktags: list[Any] | None = None,
    ) -> dict[str, Any]:
        items = list(ktags or []) + list(topics or [])
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            for item in items:
                if item in (None, ""):
                    continue
                if isinstance(item, str):
                    name = item
                    value = item
                elif isinstance(item, dict):
                    name = str(item.get("name") or "")
                    value = str(item.get("value") or item.get("name") or "")
                else:
                    continue
                self._upsert_ktag_unlocked(agent, name, value)
            self._save()
            snapshot = public_agent(agent)
        self._notify_ktags()
        return {
            "agent_id": snapshot["id"],
            "ktags": snapshot["ktags"],
            "knowledge": snapshot["knowledge"],
        }

    def add_ktag(self, agent_id: str, name: str, value: str) -> dict[str, str]:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            ktag = self._upsert_ktag_unlocked(agent, name, value, replace_value=True)
            self._save()
        self._notify_ktags()
        return dict(ktag)

    def update_ktag(
        self,
        agent_id: str,
        ktag_id: str,
        name: str | None = None,
        value: str | None = None,
    ) -> dict[str, str]:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            ktag = self._find_ktag_unlocked(agent, ktag_id)
            if name is not None:
                new_name = normalize_ktag_name(name)
                for other in agent["ktags"]:
                    if other["id"] != ktag_id and other["name"] == new_name:
                        raise PermanentError(f'El ktag "{new_name}" está duplicado.')
                ktag["name"] = new_name
            if value is not None:
                ktag["value"] = value
            self._save()
            snapshot = dict(ktag)
        self._notify_ktags()
        return snapshot

    def delete_ktag(self, agent_id: str, ktag_id: str) -> None:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            before = len(agent["ktags"])
            agent["ktags"] = [k for k in agent["ktags"] if k["id"] != ktag_id]
            if len(agent["ktags"]) == before:
                raise PermanentError(f"ktag no encontrado: {ktag_id}")
            self._save()
        self._notify_ktags()

    def enable_capability(self, agent_id: str, capability: str) -> dict[str, Any]:
        allowed = {"cart", "reservation", "contact"}
        cap = (capability or "").strip().lower()
        if cap not in allowed:
            raise PermanentError(f"capability inválida: {capability}. Usar {sorted(allowed)}")
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            if cap not in agent["capabilities"]:
                agent["capabilities"].append(cap)
            self._save()
            return {"agent_id": agent["id"], "capabilities": list(agent["capabilities"])}

    def create_support_ticket(self, summary: str, agent_id: str | None = None) -> dict[str, Any]:
        if not (summary or "").strip():
            raise PermanentError("create_support_ticket requiere summary")
        ticket = {
            "id": f"tkt_{uuid.uuid4().hex[:8]}",
            "summary": summary.strip(),
            "agent_id": agent_id,
            "status": "open",
        }
        with self._lock:
            self.tickets.append(ticket)
            self._save()
        return ticket

    def collect_rag_ktags(self, agent_id: str) -> list[dict[str, str]]:
        with self._lock:
            agent = self._require_agent_unlocked(agent_id)
            name = agent["name"]
            goal = (agent.get("goal") or "").strip()
            profile = {
                "id": f"kt_perfil_{agent['id']}",
                "name": "perfil",
                "value": f"{name}. {goal}".strip(". "),
                "source_agent": name,
            }
            own = [
                {
                    "id": k["id"],
                    "name": k["name"],
                    "value": k["value"],
                    "source_agent": name,
                }
                for k in agent.get("ktags") or []
            ]
            agent_type = agent.get("type") or "menu"
            extras: list[dict[str, str]] = []
            if agent_type in {"nutrition", "geo"}:
                skip_nutrition = {"ubicacion", "horarios", "promos"}
                for other in self.agents.values():
                    if other.get("type") != "menu" or other["id"] == agent_id:
                        continue
                    if agent_type == "geo" and other["id"] not in self._active_ids:
                        continue
                    for ktag in other.get("ktags") or []:
                        name = ktag["name"]
                        if agent_type == "geo" and name != "ubicacion":
                            continue
                        if agent_type == "nutrition" and name in skip_nutrition:
                            continue
                        extras.append(
                            {
                                "id": ktag["id"],
                                "name": f"{other['name']}:{name}",
                                "value": ktag["value"],
                                "source_agent": other["name"],
                            }
                        )
            return [profile] + own + extras

    def _require_agent_unlocked(self, agent_id: str) -> dict[str, Any]:
        if not agent_id:
            raise PermanentError("falta agent_id")
        if agent_id in self.agents:
            return self.agents[agent_id]
        lowered = agent_id.lower()
        for agent in self.agents.values():
            if agent["name"].lower() == lowered:
                return agent
        raise PermanentError(f"agente no encontrado: {agent_id}")

    def _find_ktag_unlocked(self, agent: dict[str, Any], ktag_id: str) -> dict[str, str]:
        for ktag in agent.get("ktags") or []:
            if ktag["id"] == ktag_id:
                return ktag
        raise PermanentError(f"ktag no encontrado: {ktag_id}")

    def _upsert_ktag_unlocked(
        self,
        agent: dict[str, Any],
        name: str,
        value: str,
        *,
        replace_value: bool = False,
    ) -> dict[str, str]:
        normalized = normalize_ktag_name(name)
        for ktag in agent.setdefault("ktags", []):
            if ktag["name"] == normalized:
                if replace_value or value:
                    ktag["value"] = value
                return ktag
        ktag = new_ktag(normalized, value)
        agent["ktags"].append(ktag)
        return ktag


_store: PlatformStore | None = None
_store_lock = threading.Lock()


def get_store() -> PlatformStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = PlatformStore()
            from orchestrator.rag import retriever

            _store.on_ktags_changed(retriever.invalidate)
        return _store
