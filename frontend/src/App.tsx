import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AgentsView from "./AgentsView";
import ExecutionMap from "./ExecutionMap";
import { pretty, type Status, type TraceEvent } from "./executionGraph";

type View = "orchestrator" | "agents";
type ProcessView = "log" | "map";

type RunSummary = {
  id: string;
  created_at: string;
  status: Status;
  goal: string;
  title: string;
};

type Example = {
  id: string;
  filename: string;
  work_order: Record<string, unknown>;
};

type Report = {
  status: Status;
  goal?: string;
  summary?: string;
  headline?: string;
  contained?: boolean;
  missing_data?: string[];
  recommendation?: string;
  actions?: Array<{
    tool: string;
    ok: boolean;
    error?: string | null;
    used_fallback?: boolean;
    attempts?: number;
  }>;
};

const STATUS_LABEL: Record<Status, string> = {
  running: "en curso",
  success: "éxito",
  partial: "parcial",
  failed: "fallo",
};

function ViewSwitch({
  view,
  onChange,
}: {
  view: View;
  onChange: (view: View) => void;
}) {
  return (
    <>
      <header className="brand">
        <span className="mark">WO</span>
        <div>
          <strong>Orquestador</strong>
          <p>historial y agentes RAG</p>
        </div>
      </header>
      <nav className="view-switch">
        <button
          type="button"
          className={view === "orchestrator" ? "active" : ""}
          onClick={() => onChange("orchestrator")}
        >
          Orquestador
        </button>
        <button
          type="button"
          className={view === "agents" ? "active" : ""}
          onClick={() => onChange("agents")}
        >
          Agentes
        </button>
      </nav>
    </>
  );
}

export default function App() {
  const [view, setView] = useState<View>("orchestrator");
  const [examples, setExamples] = useState<Example[]>([]);
  const [draft, setDraft] = useState("{\n  \n}");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [processView, setProcessView] = useState<ProcessView>("map");
  const socketRef = useRef<WebSocket | null>(null);
  const timelineRef = useRef<HTMLDivElement | null>(null);

  const loadRuns = useCallback(async () => {
    const res = await fetch("/runs");
    if (!res.ok) return;
    const data: RunSummary[] = await res.json();
    setRuns(data);
  }, []);

  useEffect(() => {
    fetch("/examples")
      .then((r) => r.json())
      .then((data: Example[]) => {
        setExamples(data);
        const first = data[0];
        if (first) setDraft(JSON.stringify(first.work_order, null, 2));
      })
      .catch(() => setError("No se pudieron cargar los ejemplos. ¿Está corriendo la API en :8080?"));
    loadRuns();
    const timer = window.setInterval(loadRuns, 4000);
    return () => window.clearInterval(timer);
  }, [loadRuns]);

  useEffect(() => {
    if (!selectedId) return;
    socketRef.current?.close();
    setEvents([]);
    setReport(null);

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${protocol}://${window.location.host}/ws/runs/${selectedId}`);
    socketRef.current = ws;
    ws.onmessage = (msg) => {
      const event: TraceEvent = JSON.parse(msg.data);
      if (event.phase === "done") {
        loadRuns();
        return;
      }
      setEvents((prev) => [...prev, event]);
      if (event.phase === "report" && event.result && typeof event.result === "object") {
        setReport(event.result as Report);
        loadRuns();
      }
    };
    ws.onerror = () => setError("WebSocket desconectado");
    return () => ws.close();
  }, [selectedId, loadRuns]);

  useEffect(() => {
    if (processView !== "log") return;
    timelineRef.current?.scrollTo({ top: timelineRef.current.scrollHeight, behavior: "smooth" });
  }, [events.length, processView]);

  const selected = useMemo(
    () => runs.find((r) => r.id === selectedId) ?? null,
    [runs, selectedId]
  );

  async function execute() {
    setError(null);
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(draft);
    } catch {
      setError("El work order no es JSON válido");
      return;
    }
    setBusy(true);
    try {
      const res = await fetch("/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setSelectedId(data.id);
      await loadRuns();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar el run");
    } finally {
      setBusy(false);
    }
  }

  if (view === "agents") {
    return <AgentsView nav={<ViewSwitch view={view} onChange={setView} />} />;
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <ViewSwitch view={view} onChange={setView} />
        <ul className="run-list">
          {runs.length === 0 && <li className="empty">Todavía no hay ejecuciones</li>}
          {runs.map((run) => (
            <li key={run.id}>
              <button
                className={run.id === selectedId ? "run active" : "run"}
                onClick={() => setSelectedId(run.id)}
              >
                <span className={`dot ${run.status}`} />
                <span className="run-meta">
                  <em>{run.title || run.goal || run.id}</em>
                  <small>
                    {STATUS_LABEL[run.status]} · {run.id}
                  </small>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="main">
        <section className="composer">
          <div className="row">
            <h1>Work order</h1>
            <div className="examples">
              {examples.map((ex) => (
                <button
                  key={ex.id}
                  type="button"
                  onClick={() => setDraft(JSON.stringify(ex.work_order, null, 2))}
                >
                  {ex.id.replace("work_order_", "")}
                </button>
              ))}
            </div>
          </div>
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            spellCheck={false}
          />
          <div className="row">
            <button className="primary" disabled={busy} onClick={execute}>
              {busy ? "Enviando…" : "Ejecutar"}
            </button>
            {error && <span className="error">{error}</span>}
            {selected && (
              <span className={`badge ${selected.status}`}>{STATUS_LABEL[selected.status]}</span>
            )}
          </div>
        </section>

        <section className="timeline-wrap">
          <div className="row timeline-head">
            <h2>Procesamiento</h2>
            <nav className="process-switch">
              <button
                type="button"
                className={processView === "log" ? "active" : ""}
                onClick={() => setProcessView("log")}
              >
                Log
              </button>
              <button
                type="button"
                className={processView === "map" ? "active" : ""}
                onClick={() => setProcessView("map")}
              >
                Mapa
              </button>
            </nav>
          </div>
          {processView === "map" ? (
            <ExecutionMap events={events} />
          ) : (
            <div className="timeline" ref={timelineRef}>
              {events.length === 0 && (
                <p className="empty">Ejecutá un work order para ver el stream en vivo.</p>
              )}
              {events.map((event, i) => (
                <article key={`${event.ts}-${i}`} className={`card ${event.phase}`}>
                  <header>
                    <span className="phase">{event.phase}</span>
                    {event.tool && <code>{event.tool}</code>}
                    {event.decision && <span className="decision">{event.decision}</span>}
                  </header>
                  {event.thought && event.phase !== "report" && <p>{event.thought}</p>}
                  {event.error && <pre className="err">{event.error}</pre>}
                  {event.args && <pre>{pretty(event.args)}</pre>}
                  {event.result != null && event.phase !== "report" && (
                    <pre>{pretty(event.result)}</pre>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>

        {report && (
          <section className="report">
            <h2>Reporte final</h2>
            <p>
              <span className={`badge ${report.contained ? "contained" : report.status}`}>
                {report.contained ? "contención" : STATUS_LABEL[report.status]}
              </span>{" "}
              {report.goal}
            </p>
            {report.summary && <p>{report.summary}</p>}
            {!!report.missing_data?.length && (
              <p>Datos faltantes: {report.missing_data.join(", ")}</p>
            )}
            {report.headline && <p>{report.headline}</p>}
          </section>
        )}
      </main>
    </div>
  );
}
