from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


Status = Literal["success", "partial", "failed", "running"]
Decision = Literal["continue", "retry", "replan", "fallback", "stop"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class WorkOrder:
    id: str
    title: str
    description: str
    requester: str = ""
    priority: str = "normal"
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkOrder:
        return cls(
            id=str(data.get("id") or "WO-unknown"),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            requester=str(data.get("requester") or ""),
            priority=str(data.get("priority") or "normal"),
            context=dict(data.get("context") or {}),
        )


@dataclass
class PlannedAction:
    tool: str
    args: dict[str, Any]
    why: str = ""


@dataclass
class ActionResult:
    tool: str
    args: dict[str, Any]
    ok: bool
    output: Any = None
    error: str | None = None
    attempts: int = 1
    used_fallback: bool = False
    recovered: bool = False


@dataclass
class TraceEvent:
    ts: str
    run_id: str
    phase: str
    thought: str = ""
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: Any = None
    error: str | None = None
    decision: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "phase": self.phase,
            "thought": self.thought,
            "tool": self.tool,
            "args": self.args,
            "result": self.result,
            "error": self.error,
            "decision": self.decision,
        }


@dataclass
class FinalReport:
    run_id: str
    work_order_id: str
    status: Status
    goal: str
    actions: list[ActionResult]
    missing_data: list[str]
    recommendation: str
    summary: str = ""
    headline: str = ""
    contained: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "work_order_id": self.work_order_id,
            "status": self.status,
            "goal": self.goal,
            "actions": [
                {
                    "tool": a.tool,
                    "args": a.args,
                    "ok": a.ok,
                    "output": a.output,
                    "error": a.error,
                    "attempts": a.attempts,
                    "used_fallback": a.used_fallback,
                    "recovered": a.recovered,
                }
                for a in self.actions
            ],
            "missing_data": self.missing_data,
            "recommendation": self.recommendation,
            "summary": self.summary,
            "headline": self.headline,
            "contained": self.contained,
            "events": list(self.events),
        }
