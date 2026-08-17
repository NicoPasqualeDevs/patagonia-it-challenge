from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable

from orchestrator.state import TraceEvent, utc_now

logger = logging.getLogger("orchestrator")


def setup_logging() -> None:
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


class Tracer:
    def __init__(
        self,
        run_id: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        traces_dir: Path | None = None,
    ) -> None:
        self.run_id = run_id
        self.on_event = on_event
        self.events: list[dict[str, Any]] = []
        traces_dir = traces_dir or Path("traces")
        traces_dir.mkdir(parents=True, exist_ok=True)
        self._path = traces_dir / f"run-{run_id}.jsonl"

    def emit(
        self,
        phase: str,
        *,
        thought: str = "",
        tool: str | None = None,
        args: dict[str, Any] | None = None,
        result: Any = None,
        error: str | None = None,
        decision: str | None = None,
    ) -> dict[str, Any]:
        event = TraceEvent(
            ts=utc_now(),
            run_id=self.run_id,
            phase=phase,
            thought=thought,
            tool=tool,
            args=args,
            result=result,
            error=error,
            decision=decision,
        ).to_dict()
        self.events.append(event)
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
        logger.info(
            "%s | %s%s",
            phase,
            thought or error or decision or "",
            f" [{tool}]" if tool else "",
        )
        if self.on_event:
            self.on_event(event)
        return event
