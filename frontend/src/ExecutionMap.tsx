import { useEffect, useMemo, useRef, useState } from "react";
import {
  NODE_STATUS_LABEL,
  actorOf,
  buildExecutionGraph,
  pretty,
  type EdgeKind,
  type GraphNode,
  type TraceEvent,
} from "./executionGraph";

const NODE_W = 176;
const NODE_H = 90;
const COL_GAP = 64;
const LANE_GAP = 72;
const PAD_X = 36;
const PAD_Y = 40;
const MIN_NODE_W = 132;
const MIN_COL_GAP = 28;

type MapLayout = {
  nodeW: number;
  nodeH: number;
  colGap: number;
  laneGap: number;
  padX: number;
  padY: number;
};

function fitLayout(cols: number, availableW: number): MapLayout {
  const maxCol = Math.max(cols - 1, 0);
  const widthOf = (nodeW: number, colGap: number, padX: number) =>
    padX * 2 + cols * nodeW + maxCol * colGap;

  if (availableW <= 0 || widthOf(NODE_W, COL_GAP, PAD_X) <= availableW) {
    return {
      nodeW: NODE_W,
      nodeH: NODE_H,
      colGap: COL_GAP,
      laneGap: LANE_GAP,
      padX: PAD_X,
      padY: PAD_Y,
    };
  }

  const padX = 20;
  if (widthOf(NODE_W, MIN_COL_GAP, padX) <= availableW) {
    return {
      nodeW: NODE_W,
      nodeH: NODE_H,
      colGap: maxCol > 0 ? (availableW - padX * 2 - cols * NODE_W) / maxCol : MIN_COL_GAP,
      laneGap: LANE_GAP,
      padX,
      padY: PAD_Y,
    };
  }

  return {
    nodeW: Math.max(MIN_NODE_W, (availableW - padX * 2 - maxCol * MIN_COL_GAP) / Math.max(cols, 1)),
    nodeH: NODE_H,
    colGap: MIN_COL_GAP,
    laneGap: LANE_GAP,
    padX,
    padY: PAD_Y,
  };
}

function nodePoint(
  node: GraphNode,
  layout: MapLayout,
  anchor: "in" | "out" | "bottom" | "top"
): { x: number; y: number } {
  const x = layout.padX + node.column * (layout.nodeW + layout.colGap);
  const y = layout.padY + node.lane * (layout.nodeH + layout.laneGap);
  if (anchor === "in") return { x, y: y + layout.nodeH / 2 };
  if (anchor === "out") return { x: x + layout.nodeW, y: y + layout.nodeH / 2 };
  if (anchor === "bottom") return { x: x + layout.nodeW / 2, y: y + layout.nodeH };
  return { x: x + layout.nodeW / 2, y };
}

function nodeBox(node: GraphNode, layout: MapLayout): { x: number; y: number } {
  return {
    x: layout.padX + node.column * (layout.nodeW + layout.colGap),
    y: layout.padY + node.lane * (layout.nodeH + layout.laneGap),
  };
}

function edgeLabelOf(
  from: GraphNode,
  to: GraphNode,
  kind: EdgeKind
): string | null {
  if (kind === "fallback") return "fallback";
  if (kind === "containment") return "contención";
  if (kind === "detour" && from.lane < to.lane) return "contexto";
  return null;
}

function edgeLabelPoint(
  from: GraphNode,
  to: GraphNode,
  layout: MapLayout
): { x: number; y: number; anchor: "middle" | "start" } {
  const start =
    from.lane < to.lane
      ? nodePoint(from, layout, "bottom")
      : nodePoint(from, layout, "out");
  const end =
    from.lane < to.lane
      ? nodePoint(to, layout, "top")
      : nodePoint(to, layout, "in");
  if (from.lane === to.lane) {
    return {
      x: (start.x + end.x) / 2,
      y: nodeBox(from, layout).y - 10,
      anchor: "middle",
    };
  }
  return {
    x: (start.x + end.x) / 2 + 12,
    y: (start.y + end.y) / 2 + 4,
    anchor: "start",
  };
}

function edgePath(from: GraphNode, to: GraphNode, _kind: EdgeKind, layout: MapLayout): string {
  if (from.lane === to.lane) {
    const a = nodePoint(from, layout, "out");
    const b = nodePoint(to, layout, "in");
    const dx = Math.max(24, (b.x - a.x) / 2);
    return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
  }
  if (from.lane < to.lane) {
    const a = nodePoint(from, layout, "bottom");
    const b = nodePoint(to, layout, "top");
    const mid = (a.y + b.y) / 2;
    return `M ${a.x} ${a.y} C ${a.x} ${mid}, ${b.x} ${mid}, ${b.x} ${b.y}`;
  }
  const a = nodePoint(from, layout, "out");
  const b = nodePoint(to, layout, "in");
  const dx = Math.max(28, (b.x - a.x) / 2);
  const lift = a.y - layout.nodeH * 0.35;
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${lift}, ${b.x} ${b.y}`;
}

export default function ExecutionMap({ events }: { events: TraceEvent[] }) {
  const graph = useMemo(() => buildExecutionGraph(events), [events]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [viewW, setViewW] = useState(0);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  const byId = useMemo(() => {
    const map = new Map(graph.nodes.map((n) => [n.id, n]));
    return map;
  }, [graph.nodes]);

  const selected = selectedId ? byId.get(selectedId) ?? null : null;
  const running = graph.nodes.find((n) => n.status === "running");
  const maxCol = graph.nodes.reduce((m, n) => Math.max(m, n.column), 0);
  const maxLane = graph.nodes.reduce((m, n) => Math.max(m, n.lane), 0);
  const cols = maxCol + 1;
  const layout = useMemo(() => fitLayout(cols, viewW), [cols, viewW]);
  const canvasW = layout.padX * 2 + cols * layout.nodeW + maxCol * layout.colGap;
  const canvasH = layout.padY * 2 + (maxLane + 1) * layout.nodeH + maxLane * layout.laneGap;
  const scale = viewW > 0 ? Math.min(1, viewW / canvasW) : 1;

  useEffect(() => {
    setSelectedId(null);
  }, [events[0]?.run_id]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const update = () => setViewW(el.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [events.length]);

  useEffect(() => {
    if (!running) return;
    const scroller = scrollerRef.current;
    const nodeEl = scroller?.querySelector(`[data-node-id="${running.id}"]`);
    if (!(scroller instanceof HTMLElement) || !(nodeEl instanceof HTMLElement)) return;
    const left = nodeEl.offsetLeft * scale;
    const width = nodeEl.offsetWidth * scale;
    const target = left - (scroller.clientWidth - width) / 2;
    scroller.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
  }, [running?.id, scale]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const onWheel = (e: globalThis.WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth) return;
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      el.scrollLeft += e.deltaY;
      e.preventDefault();
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [events.length, scale]);

  if (events.length === 0) {
    return <p className="empty">Ejecutá un work order para ver el mapa de nodos.</p>;
  }

  return (
    <div className="exec-map">
      <div
        className="exec-map-scroll"
        ref={scrollerRef}
        onClick={() => setSelectedId(null)}
      >
        <div
          className="exec-map-fit"
          style={{ width: canvasW * scale, height: canvasH * scale }}
        >
          <div
            className="exec-map-canvas"
            style={{
              width: canvasW,
              height: canvasH,
              transform: `scale(${scale})`,
            }}
          >
            <svg className="exec-map-edges" width={canvasW} height={canvasH}>
              {graph.edges.map((edge) => {
                const from = byId.get(edge.from);
                const to = byId.get(edge.to);
                if (!from || !to) return null;
                const start =
                  from.lane < to.lane
                    ? nodePoint(from, layout, "bottom")
                    : nodePoint(from, layout, "out");
                const end =
                  from.lane < to.lane
                    ? nodePoint(to, layout, "top")
                    : nodePoint(to, layout, "in");
                const mid = { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 };
                return (
                  <g key={edge.id} className={`exec-edge ${edge.kind}`}>
                    <path d={edgePath(from, to, edge.kind, layout)} />
                    <circle cx={mid.x} cy={mid.y} r="4" />
                  </g>
                );
              })}
            </svg>
            {graph.nodes.map((node) => {
              const box = nodeBox(node, layout);
              const active = selectedId === node.id;
              return (
                <button
                  key={node.id}
                  type="button"
                  data-node-id={node.id}
                  className={`exec-node ${node.kind} ${node.status}${node.contained ? " contained" : ""}${active ? " selected" : ""}`}
                  style={{
                    left: box.x,
                    top: box.y,
                    width: layout.nodeW,
                    height: layout.nodeH,
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedId((current) => (current === node.id ? null : node.id));
                  }}
                >
                  <span className="exec-node-top">
                    <span className="exec-node-kind">{node.kind === "phase" ? "fase" : "tool"}</span>
                    <span className="exec-node-actor">{actorOf(node)}</span>
                  </span>
                  <strong>{node.label}</strong>
                  <span className="exec-node-status">
                    {node.contained && node.id === "report"
                      ? "contención"
                      : NODE_STATUS_LABEL[node.status]}
                    {node.attempts > 1 ? ` · ${node.attempts}` : ""}
                  </span>
                </button>
              );
            })}
            <svg className="exec-map-edge-labels" width={canvasW} height={canvasH}>
              {graph.edges.map((edge) => {
                const from = byId.get(edge.from);
                const to = byId.get(edge.to);
                if (!from || !to) return null;
                const label = edgeLabelOf(from, to, edge.kind);
                if (!label) return null;
                const point = edgeLabelPoint(from, to, layout);
                return (
                  <g key={`label:${edge.id}`} className={`exec-edge ${edge.kind}`}>
                    <text x={point.x} y={point.y} textAnchor={point.anchor}>
                      {label}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>
      </div>
      {selected ? (
        <NodeInspector node={selected} onClose={() => setSelectedId(null)} />
      ) : (
        <p className="exec-map-hint">Click en un nodo para ver el detalle de ese paso.</p>
      )}
    </div>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isReportResult(value: unknown): value is Record<string, unknown> {
  return isRecord(value) && typeof value.status === "string" && (
    typeof value.summary === "string" ||
    typeof value.recommendation === "string" ||
    typeof value.goal === "string"
  );
}

const REPORT_STATUS_LABEL: Record<string, string> = {
  running: "en curso",
  success: "éxito",
  partial: "parcial",
  failed: "fallo",
};

const ACTION_LABEL: Record<string, string> = {
  get_weather: "Clima",
  get_dollar: "Dólar",
  get_holidays: "Feriados",
  get_local_time: "Hora local",
  lookup_food: "Alimentos",
  geocode_address: "Ubicación",
  execute_agent: "Ejecutar agente",
  activate_agent: "Activación del agente",
  create_support_ticket: "Ticket de soporte",
  lookup_agent: "Búsqueda del agente",
  create_or_update_agent: "Alta o actualización del agente",
  attach_knowledge: "Conocimiento",
  enable_capability: "Capacidad",
};

function actionLine(action: unknown): string {
  if (!isRecord(action) || typeof action.tool !== "string") return "";
  const label = ACTION_LABEL[action.tool] ?? action.tool;
  const output = isRecord(action.output) ? action.output : null;
  if (output?.skipped === true || output?.disabled === true) {
    return `${label}: no disponible (desactivada)`;
  }
  if (action.ok === true) {
    if (action.tool === "create_support_ticket" && output && typeof output.id === "string") {
      return `${label}: abierto (${output.id})`;
    }
    return `${label}: ok`;
  }
  const error = typeof action.error === "string" && action.error ? action.error : "falló";
  return `${label}: ${error}`;
}

function formatTs(ts?: string): string {
  if (!ts) return "";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return ts;
  return date.toLocaleTimeString("es-AR", { hour12: false });
}

function agentContextOf(result: unknown): {
  items: Array<{ title: string; body: string; kind: "knowledge" | "live" }>;
} | null {
  if (!isRecord(result)) return null;
  const items: Array<{ title: string; body: string; kind: "knowledge" | "live" }> = [];
  const context = Array.isArray(result.context) ? result.context : [];
  for (const hit of context) {
    if (!isRecord(hit)) continue;
    const title = typeof hit.name === "string" ? hit.name : "";
    const body = typeof hit.value === "string" ? hit.value : "";
    if (!title && !body) continue;
    const source = typeof hit.source_agent === "string" && hit.source_agent ? hit.source_agent : "";
    items.push({
      title: source && title ? `${title} · ${source}` : title || "conocimiento",
      body,
      kind: "knowledge",
    });
  }
  const facts = Array.isArray(result.live_facts) ? result.live_facts : [];
  for (const fact of facts) {
    if (!isRecord(fact)) continue;
    const tool = typeof fact.tool === "string" ? fact.tool : "api";
    const detail = typeof fact.detail === "string" ? fact.detail : "";
    items.push({
      title: ACTION_LABEL[tool] ?? tool,
      body: detail || (fact.ok === true ? "dato en vivo disponible" : "dato no disponible"),
      kind: "live",
    });
  }
  return items.length ? { items } : null;
}

function planActionsOf(result: unknown): unknown {
  if (result && typeof result === "object" && !Array.isArray(result) && "actions" in result) {
    return (result as { actions: unknown }).actions;
  }
  return null;
}

function NodeInspector({
  node,
  onClose,
}: {
  node: GraphNode;
  onClose: () => void;
}) {
  const report = isReportResult(node.result) ? node.result : null;
  const agentContext =
    node.tool === "execute_agent" ? agentContextOf(node.result) : null;
  const planActions = report ? null : planActionsOf(node.result);
  const hasArgs = node.args != null && pretty(node.args) !== "" && pretty(node.args) !== "{}";
  const hasResult = node.result != null && planActions == null && !report;
  const pending = node.status === "pending" && node.events.length === 0;
  const reportActions = Array.isArray(report?.actions) ? report.actions : [];
  const missing = Array.isArray(report?.missing_data)
    ? report.missing_data.filter((item): item is string => typeof item === "string")
    : [];
  const [techOpen, setTechOpen] = useState(false);

  useEffect(() => {
    setTechOpen(false);
  }, [node.id]);

  return (
    <aside className="exec-inspector">
      <header>
        <div>
          <span className="exec-inspector-kind">
            <span className="phase">{node.kind === "phase" ? "fase" : "tool"}</span>
            <span className="exec-node-actor">{actorOf(node)}</span>
          </span>
          <h3>{node.label}</h3>
        </div>
        <p className="exec-inspector-meta">
          <span className={`badge node-${node.status}${node.contained ? " contained" : ""}`}>
            {node.contained && node.id === "report"
              ? "contención"
              : NODE_STATUS_LABEL[node.status]}
          </span>
          {node.decision && <span className="decision">{node.decision}</span>}
          {node.attempts > 0 && <span className="decision">{node.attempts} intento{node.attempts === 1 ? "" : "s"}</span>}
        </p>
        <button type="button" onClick={onClose} aria-label="Cerrar detalle">
          ×
        </button>
      </header>
      {pending && (
        <p className="empty">Este paso todavía no se ejecutó.</p>
      )}
      {node.why && <p className="exec-why">{node.why}</p>}
      {!report && node.thought && <p>{node.thought}</p>}
      {report && (
        <section className="exec-report-summary">
          <span className="phase">resumen</span>
          {typeof report.status === "string" && (
            <p className="exec-report-status">
              <span className={`badge ${report.contained === true ? "contained" : report.status}`}>
                {report.contained === true
                  ? "contención"
                  : REPORT_STATUS_LABEL[String(report.status)] ?? String(report.status)}
              </span>
            </p>
          )}
          {typeof report.goal === "string" && report.goal && (
            <p className="exec-report-goal">{report.goal}</p>
          )}
          <p className="exec-report-lead">
            {typeof report.summary === "string" && report.summary
              ? report.summary
              : node.thought}
          </p>
          {missing.length > 0 && (
            <p className="exec-report-missing">Datos faltantes: {missing.join(", ")}</p>
          )}
          {reportActions.length > 0 && (
            <ul>
              {reportActions.map((action, i) => {
                const line = actionLine(action);
                if (!line) return null;
                const ok = isRecord(action) && action.ok === true;
                const skipped =
                  isRecord(action) &&
                  isRecord(action.output) &&
                  (action.output.skipped === true || action.output.disabled === true);
                return (
                  <li key={i} className={skipped ? "warn" : ok ? "ok" : "bad"}>
                    {line}
                  </li>
                );
              })}
            </ul>
          )}
          {typeof report.headline === "string" && report.headline && (
            <p className="exec-report-next">{report.headline}</p>
          )}
        </section>
      )}
      {agentContext && (
        <section className="exec-agent-context">
          <span className="phase">contexto del agente</span>
          {agentContext.items.map((item, i) => (
            <article key={`${item.kind}-${item.title}-${i}`}>
              <strong>
                {item.title}
                <span className="exec-context-kind">
                  {item.kind === "live" ? "api" : "conocimiento"}
                </span>
              </strong>
              {item.body && <p>{item.body}</p>}
            </article>
          ))}
        </section>
      )}
      {!!node.decisions?.length && (
        <section className="exec-plan-decisions">
          <span className="phase">plan de acción</span>
          <ul>
            {node.decisions.map((item, i) => (
              <li key={`${item}-${i}`}>{item}</li>
            ))}
          </ul>
        </section>
      )}
      {node.error && <pre className="err">{node.error}</pre>}
      <div className="exec-inspector-grid">
        {hasArgs && (
          <section>
            <span className="phase">entrada</span>
            <pre>{pretty(node.args)}</pre>
          </section>
        )}
        {hasResult && (
          <section>
            <span className="phase">salida</span>
            <pre>{pretty(node.result)}</pre>
          </section>
        )}
        {report && (
          <section className={`exec-tech${techOpen ? " open" : ""}`}>
            <button
              type="button"
              className="exec-tech-toggle"
              aria-expanded={techOpen}
              onClick={() => setTechOpen((open) => !open)}
            >
              <span className="phase">detalle técnico</span>
              <span className="exec-tech-arrow" aria-hidden="true">
                ▼
              </span>
            </button>
            {techOpen && <pre>{pretty(node.result)}</pre>}
          </section>
        )}
        {planActions != null && (
          <section>
            <span className="phase">acciones</span>
            <pre>{pretty(planActions)}</pre>
          </section>
        )}
      </div>
      {node.events.length > 0 && (
        <section className="exec-inspector-events">
          <span className="phase">eventos del paso</span>
          {node.events.map((event, i) => (
            <article key={`${event.ts}-${event.phase}-${i}`} className={`card ${event.phase}`}>
              <header>
                <span className="phase">{event.phase}</span>
                {event.tool && <code>{event.tool}</code>}
                {event.decision && <span className="decision">{event.decision}</span>}
                {event.ts && <span className="exec-ts">{formatTs(event.ts)}</span>}
              </header>
              {event.thought && !report && <p>{event.thought}</p>}
              {event.error && <pre className="err">{event.error}</pre>}
            </article>
          ))}
        </section>
      )}
    </aside>
  );
}
