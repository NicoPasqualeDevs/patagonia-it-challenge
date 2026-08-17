from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from orchestrator.orchestrator import WorkOrderOrchestrator
from orchestrator.state import WorkOrder


def load_work_order(path: Path) -> WorkOrder:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("El work order debe ser un objeto JSON")
    return WorkOrder.from_dict(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Orquestador de work orders (planificar → ejecutar → observar → decidir)."
    )
    parser.add_argument("work_order", type=Path, help="Ruta a un JSON de work order")
    parser.add_argument(
        "--text",
        action="store_true",
        help="Imprimir el reporte en texto en vez de JSON",
    )
    args = parser.parse_args(argv)

    if not args.work_order.exists():
        print(f"No existe el archivo: {args.work_order}", file=sys.stderr)
        return 2

    work_order = load_work_order(args.work_order)
    report = WorkOrderOrchestrator().run(work_order)
    payload = report.to_dict()
    if args.text:
        print(f"estado: {payload['status']}")
        print(f"objetivo: {payload['goal']}")
        print("acciones:")
        for action in payload["actions"]:
            flag = "ok" if action["ok"] else "error"
            print(f"  - {action['tool']} [{flag}] {action.get('error') or ''}")
        if payload["missing_data"]:
            print(f"faltantes: {', '.join(payload['missing_data'])}")
        print(f"siguiente paso: {payload['recommendation']}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
