from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.chat import chat_with_agent
from orchestrator.orchestrator import WorkOrderOrchestrator
from orchestrator.platform import get_store
from orchestrator.retry import PermanentError
from orchestrator.state import WorkOrder, utc_now
from orchestrator.tools import PUBLIC_TOOLS, list_public_tools

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT / "examples"

app = FastAPI(title="Work Order Orchestrator")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunHub:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._lock = threading.Lock()
        self.loop: asyncio.AbstractEventLoop | None = None

    def create(self, work_order: dict[str, Any]) -> dict[str, Any]:
        run_id = __import__("uuid").uuid4().hex[:10]
        record = {
            "id": run_id,
            "created_at": utc_now(),
            "status": "running",
            "goal": "",
            "work_order": work_order,
            "events": [],
            "report": None,
        }
        with self._lock:
            self.runs[run_id] = record
            self._queues[run_id] = []
        return record

    def subscribe(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._queues.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            queues = self._queues.get(run_id, [])
            if queue in queues:
                queues.remove(queue)

    def emit(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            run = self.runs.get(run_id)
            if run is None:
                return
            run["events"].append(event)
            if event.get("phase") == "interpret" and isinstance(event.get("result"), dict):
                pass
            if event.get("phase") == "report" and isinstance(event.get("result"), dict):
                run["report"] = event["result"]
                run["status"] = event["result"].get("status", "failed")
                run["goal"] = event["result"].get("goal") or run["goal"]
            queues = list(self._queues.get(run_id, []))
        loop = self.loop
        if loop and loop.is_running():
            for queue in queues:
                loop.call_soon_threadsafe(queue.put_nowait, event)

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self.runs.values())
        items.sort(key=lambda r: r["created_at"], reverse=True)
        return [
            {
                "id": r["id"],
                "created_at": r["created_at"],
                "status": r["status"],
                "goal": r["goal"],
                "title": (r.get("work_order") or {}).get("title", ""),
            }
            for r in items
        ]

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self.runs.get(run_id)
            return dict(run) if run else None


hub = RunHub()


@app.on_event("startup")
async def _startup() -> None:
    hub.loop = asyncio.get_running_loop()
    get_store()


def _http_error(exc: PermanentError) -> HTTPException:
    message = str(exc)
    if "reserva" in message:
        code = 409
    elif "no encontrado" in message:
        code = 404
    else:
        code = 400
    return HTTPException(status_code=code, detail=message)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/examples")
def list_examples() -> list[dict[str, Any]]:
    items = []
    if not EXAMPLES_DIR.exists():
        return items
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        items.append({"id": path.stem, "filename": path.name, "work_order": data})
    return items


@app.get("/tools/public")
def get_public_tools() -> list[dict[str, Any]]:
    return list_public_tools()


@app.put("/tools/public/{tool_name}")
def update_public_tool(tool_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    name = (tool_name or "").strip()
    if name not in PUBLIC_TOOLS:
        raise HTTPException(status_code=404, detail=f"tool desconocida: {name}")
    if "enabled" not in payload:
        raise HTTPException(status_code=400, detail="falta enabled")
    try:
        get_store().set_public_tool_enabled(name, bool(payload.get("enabled")))
    except PermanentError as exc:
        raise _http_error(exc) from exc
    return list_public_tools()


@app.get("/agents")
def list_agents() -> list[dict[str, Any]]:
    return get_store().list_agents()


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str) -> dict[str, Any]:
    try:
        return get_store().get_agent(agent_id)
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.post("/agents/{agent_id}/activate")
def activate_agent(agent_id: str) -> dict[str, Any]:
    try:
        return get_store().activate_agent(agent_id)
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.post("/agents/{agent_id}/deactivate")
def deactivate_agent(agent_id: str) -> dict[str, Any]:
    try:
        return get_store().deactivate_agent(agent_id)
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.put("/agents/{agent_id}")
def update_agent(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_store().update_agent(
            agent_id,
            goal=payload.get("goal"),
            instructions=payload.get("instructions"),
        )
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.post("/agents/{agent_id}/ktags")
def create_ktag(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name") or "")
    value = str(payload.get("value") or "")
    try:
        return get_store().add_ktag(agent_id, name, value)
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.put("/agents/{agent_id}/ktags/{ktag_id}")
def update_ktag(agent_id: str, ktag_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return get_store().update_ktag(
            agent_id,
            ktag_id,
            name=payload.get("name"),
            value=payload.get("value"),
        )
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.delete("/agents/{agent_id}/ktags/{ktag_id}")
def delete_ktag(agent_id: str, ktag_id: str) -> dict[str, Any]:
    try:
        get_store().delete_ktag(agent_id, ktag_id)
        return {"ok": True}
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.post("/agents/{agent_id}/chat")
def chat_agent(agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    message = str(payload.get("message") or "")
    try:
        store = get_store()
        store.require_active(agent_id)
        return chat_with_agent(store, agent_id, message)
    except PermanentError as exc:
        raise _http_error(exc) from exc


@app.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    return hub.list_runs()


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = hub.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run no encontrado")
    return run


@app.post("/runs")
async def start_run(payload: dict[str, Any]) -> dict[str, Any]:
    work_order_data = payload.get("work_order") if "work_order" in payload else payload
    if not isinstance(work_order_data, dict):
        raise HTTPException(status_code=400, detail="work order inválido")
    record = hub.create(work_order_data)
    asyncio.create_task(_run_orchestrator(record["id"], work_order_data))
    return {"id": record["id"], "status": "running"}


@app.websocket("/ws/runs/{run_id}")
async def ws_run(websocket: WebSocket, run_id: str) -> None:
    await websocket.accept()
    run = hub.get(run_id)
    if run is None:
        await websocket.close(code=4404)
        return
    for event in run.get("events") or []:
        await websocket.send_json(event)
    if run.get("status") != "running":
        await websocket.send_json({"phase": "done", "run_id": run_id, "status": run["status"]})
        return
    queue = hub.subscribe(run_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
            if event.get("phase") == "report":
                await websocket.send_json(
                    {"phase": "done", "run_id": run_id, "status": event.get("result", {}).get("status")}
                )
                break
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(run_id, queue)


async def _run_orchestrator(run_id: str, work_order_data: dict[str, Any]) -> None:
    def _job() -> None:
        def on_event(event: dict[str, Any]) -> None:
            hub.emit(run_id, event)
            if event.get("phase") == "interpret" and isinstance(event.get("result"), dict):
                with hub._lock:
                    run = hub.runs.get(run_id)
                    if run:
                        run["goal"] = event.get("thought") or run["goal"]

        try:
            WorkOrderOrchestrator(on_event=on_event, run_id=run_id).run(
                WorkOrder.from_dict(work_order_data)
            )
        except Exception as exc:
            hub.emit(
                run_id,
                {
                    "ts": utc_now(),
                    "run_id": run_id,
                    "phase": "report",
                    "thought": "El orquestador terminó con error interno",
                    "error": str(exc),
                    "result": {
                        "status": "failed",
                        "goal": "",
                        "actions": [],
                        "missing_data": [],
                        "recommendation": str(exc),
                        "summary": "El pedido no se pudo completar por un error interno.",
                    },
                    "decision": "stop",
                },
            )

    await asyncio.to_thread(_job)
