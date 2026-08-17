import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

type AgentStatus = "active" | "reserve";
type AgentType = "menu" | "nutrition" | "geo";

type AgentSummary = {
  id: string;
  name: string;
  type: AgentType;
  goal: string;
  personality: string;
  ktag_count: number;
  capabilities: string[];
  status: AgentStatus;
};

type Ktag = {
  id: string;
  name: string;
  value: string;
};

type AgentDetail = AgentSummary & {
  ktags: Ktag[];
  knowledge: string[];
  instructions: string;
};

type Citation = {
  name: string;
  score: number;
  source_agent?: string;
};

type ChatMessage = {
  role: "user" | "agent";
  text: string;
  citations?: Citation[];
};

type PublicTool = {
  name: string;
  label: string;
  source: string;
  description: string;
  enabled: boolean;
};

const TYPE_LABEL: Record<AgentType, string> = {
  menu: "Menú",
  nutrition: "Nutrición",
  geo: "Geo",
};

const TYPE_ORDER: AgentType[] = ["menu", "nutrition", "geo"];
const DUTY_ORDER: AgentStatus[] = ["active", "reserve"];
const DUTY_LABEL: Record<AgentStatus, string> = {
  active: "Activos",
  reserve: "Reserva",
};

async function readError(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
  } catch {
    /* ignore */
  }
  return text || res.statusText;
}

function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function AgentsView({ nav }: { nav: ReactNode }) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<AgentDetail | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Ktag>>({});
  const [openIds, setOpenIds] = useState<Record<string, boolean>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [draftMessage, setDraftMessage] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [activating, setActivating] = useState(false);
  const [editingGoal, setEditingGoal] = useState(false);
  const [goalDraft, setGoalDraft] = useState("");
  const [savingGoal, setSavingGoal] = useState(false);
  const [editingInstructions, setEditingInstructions] = useState(false);
  const [instructionsDraft, setInstructionsDraft] = useState("");
  const [savingInstructions, setSavingInstructions] = useState(false);
  const [openDuties, setOpenDuties] = useState<Record<AgentStatus, boolean>>({
    active: true,
    reserve: true,
  });
  const [publicTools, setPublicTools] = useState<PublicTool[]>([]);
  const [openTools, setOpenTools] = useState(true);
  const [togglingTool, setTogglingTool] = useState<string | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);

  const loadAgents = useCallback(async () => {
    const res = await fetch("/agents");
    if (!res.ok) throw new Error("No se pudieron cargar los agentes");
    const data: AgentSummary[] = await res.json();
    setAgents(data);
    return data;
  }, []);

  const loadDetail = useCallback(async (agentId: string) => {
    const res = await fetch(`/agents/${agentId}`);
    if (!res.ok) throw new Error(await readError(res));
    const data: AgentDetail = await res.json();
    setDetail({ ...data, instructions: data.instructions || "" });
    const next: Record<string, Ktag> = {};
    for (const ktag of data.ktags) next[ktag.id] = { ...ktag };
    setDrafts(next);
  }, []);

  const loadPublicTools = useCallback(async () => {
    const res = await fetch("/tools/public");
    if (!res.ok) throw new Error("No se pudieron cargar las APIs públicas");
    const data: PublicTool[] = await res.json();
    setPublicTools(data);
    return data;
  }, []);

  useEffect(() => {
    loadAgents()
      .then((data) => {
        if (data[0]) setSelectedId(data[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Error al cargar"));
    loadPublicTools().catch((err) =>
      setError(err instanceof Error ? err.message : "Error al cargar las APIs")
    );
  }, [loadAgents, loadPublicTools]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadAgents().catch(() => undefined);
      loadPublicTools().catch(() => undefined);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [loadAgents, loadPublicTools]);

  useEffect(() => {
    if (!selectedId) return;
    setError(null);
    setChat([]);
    setEditingGoal(false);
    setEditingInstructions(false);
    loadDetail(selectedId).catch((err) =>
      setError(err instanceof Error ? err.message : "No se pudo abrir el agente")
    );
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (!detail) return;
    const summary = agents.find((agent) => agent.id === detail.id);
    if (summary && summary.status !== detail.status) {
      setDetail((prev) => (prev ? { ...prev, status: summary.status } : prev));
    }
  }, [agents, detail]);

  useEffect(() => {
    chatRef.current?.scrollTo({ top: chatRef.current.scrollHeight, behavior: "smooth" });
  }, [chat.length]);

  const grouped = useMemo(() => {
    const groups: Record<AgentStatus, Record<AgentType, AgentSummary[]>> = {
      active: { menu: [], nutrition: [], geo: [] },
      reserve: { menu: [], nutrition: [], geo: [] },
    };
    for (const agent of agents) {
      const duty = agent.status === "active" ? "active" : "reserve";
      (groups[duty][agent.type] ?? groups[duty].menu).push(agent);
    }
    return groups;
  }, [agents]);

  const isActive = detail?.status === "active";

  function updateDraft(id: string, patch: Partial<Ktag>) {
    setDrafts((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }));
  }

  async function saveKtag(id: string) {
    if (!selectedId) return;
    const draft = drafts[id];
    if (!draft) return;
    setSavingId(id);
    setError(null);
    try {
      const res = await fetch(`/agents/${selectedId}/ktags/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: draft.name, value: draft.value }),
      });
      if (!res.ok) throw new Error(await readError(res));
      await Promise.all([loadDetail(selectedId), loadAgents()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar el ktag");
    } finally {
      setSavingId(null);
    }
  }

  async function removeKtag(id: string) {
    if (!selectedId) return;
    setSavingId(id);
    setError(null);
    try {
      const res = await fetch(`/agents/${selectedId}/ktags/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await readError(res));
      await Promise.all([loadDetail(selectedId), loadAgents()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo borrar el ktag");
    } finally {
      setSavingId(null);
    }
  }

  async function toggleDuty() {
    if (!selectedId || activating || !detail) return;
    const toReserve = isActive;
    setActivating(true);
    setError(null);
    try {
      const path = toReserve ? "deactivate" : "activate";
      const res = await fetch(`/agents/${selectedId}/${path}`, { method: "POST" });
      if (!res.ok) throw new Error(await readError(res));
      await Promise.all([loadDetail(selectedId), loadAgents()]);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : toReserve
            ? "No se pudo pasar a reserva"
            : "No se pudo activar el agente"
      );
    } finally {
      setActivating(false);
    }
  }

  function startEditGoal() {
    if (!detail) return;
    setGoalDraft(detail.goal);
    setEditingGoal(true);
    setEditingInstructions(false);
    setError(null);
  }

  async function saveGoal() {
    if (!selectedId || savingGoal) return;
    const text = goalDraft.trim();
    if (!text) {
      setError("la descripción no puede estar vacía");
      return;
    }
    setSavingGoal(true);
    setError(null);
    try {
      const res = await fetch(`/agents/${selectedId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: text }),
      });
      if (!res.ok) throw new Error(await readError(res));
      setEditingGoal(false);
      await Promise.all([loadDetail(selectedId), loadAgents()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la descripción");
    } finally {
      setSavingGoal(false);
    }
  }

  function startEditInstructions() {
    if (!detail) return;
    setInstructionsDraft(detail.instructions || "");
    setEditingInstructions(true);
    setEditingGoal(false);
    setError(null);
  }

  async function saveInstructions() {
    if (!selectedId || savingInstructions) return;
    const text = instructionsDraft.trim();
    if (!text) {
      setError("las instrucciones no pueden estar vacías");
      return;
    }
    setSavingInstructions(true);
    setError(null);
    try {
      const res = await fetch(`/agents/${selectedId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instructions: text }),
      });
      if (!res.ok) throw new Error(await readError(res));
      setEditingInstructions(false);
      await Promise.all([loadDetail(selectedId), loadAgents()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron guardar las instrucciones");
    } finally {
      setSavingInstructions(false);
    }
  }

  async function addKtag() {
    if (!selectedId) return;
    setError(null);
    try {
      const res = await fetch(`/agents/${selectedId}/ktags`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: `nuevo_ktag_${Date.now().toString().slice(-4)}`, value: "" }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const created: Ktag = await res.json();
      await Promise.all([loadDetail(selectedId), loadAgents()]);
      setOpenIds((prev) => ({ ...prev, [created.id]: true }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear el ktag");
    }
  }

  async function togglePublicTool(tool: PublicTool) {
    if (togglingTool) return;
    setTogglingTool(tool.name);
    setError(null);
    setPublicTools((prev) =>
      prev.map((item) =>
        item.name === tool.name ? { ...item, enabled: !tool.enabled } : item
      )
    );
    try {
      const res = await fetch(`/tools/public/${tool.name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !tool.enabled }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const data: PublicTool[] = await res.json();
      setPublicTools(data);
    } catch (err) {
      setPublicTools((prev) =>
        prev.map((item) =>
          item.name === tool.name ? { ...item, enabled: tool.enabled } : item
        )
      );
      setError(err instanceof Error ? err.message : "No se pudo actualizar la API");
    } finally {
      setTogglingTool(null);
    }
  }

  async function sendChat(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !draftMessage.trim() || chatBusy || !isActive) return;
    const text = draftMessage.trim();
    setDraftMessage("");
    setChat((prev) => [...prev, { role: "user", text }]);
    setChatBusy(true);
    setError(null);
    try {
      const res = await fetch(`/agents/${selectedId}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) throw new Error(await readError(res));
      const data = await res.json();
      setChat((prev) => [
        ...prev,
        { role: "agent", text: data.reply, citations: data.citations || [] },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo chatear");
    } finally {
      setChatBusy(false);
    }
  }

  return (
    <div className="shell agents-shell">
      <aside className="sidebar">
        {nav}
        <ul className="run-list">
        <li>
          <button
            type="button"
            className="duty-heading tools"
            onClick={() => setOpenTools((prev) => !prev)}
            aria-expanded={openTools}
          >
            <span className="duty-title">
              <span className="duty-chevron">{openTools ? "▾" : "▸"}</span>
              APIs públicas
            </span>
            <span className="duty-count">
              {publicTools.filter((tool) => tool.enabled).length}/{publicTools.length || 0}
            </span>
          </button>
          {openTools && (
            <>
              {publicTools.length === 0 && <p className="empty">Sin APIs</p>}
              {publicTools.map((tool) => (
                <button
                  key={tool.name}
                  type="button"
                  className={`run tool-row${tool.enabled ? " on" : ""}`}
                  onClick={() => togglePublicTool(tool)}
                  disabled={togglingTool === tool.name}
                  title={tool.description}
                  role="switch"
                  aria-checked={tool.enabled}
                  aria-label={`${tool.enabled ? "Desactivar" : "Activar"} ${tool.label}`}
                >
                  <span className={`tool-switch${tool.enabled ? " on" : ""}`} aria-hidden="true">
                    <span />
                  </span>
                  <span className="run-meta">
                    <em>{tool.label}</em>
                    <small>
                      {tool.enabled ? "activa" : "inactiva"} · {tool.source}
                    </small>
                  </span>
                </button>
              ))}
            </>
          )}
        </li>
        {DUTY_ORDER.map((duty) => {
          const byType = grouped[duty];
          const count = TYPE_ORDER.reduce((sum, type) => sum + byType[type].length, 0);
          return (
            <li key={duty}>
              <button
                type="button"
                className={`duty-heading ${duty}`}
                onClick={() =>
                  setOpenDuties((prev) => ({ ...prev, [duty]: !prev[duty] }))
                }
                aria-expanded={openDuties[duty]}
              >
                <span className="duty-title">
                  <span className="duty-chevron">{openDuties[duty] ? "▾" : "▸"}</span>
                  {DUTY_LABEL[duty]}
                </span>
                <span className="duty-count">{count}</span>
              </button>
              {openDuties[duty] && (
                <>
                  {count === 0 && <p className="empty">Sin agentes</p>}
                  {TYPE_ORDER.map((type) =>
                    byType[type].length === 0 ? null : (
                      <div key={type}>
                        <p className="group-label type-sublabel">{TYPE_LABEL[type]}</p>
                        {byType[type].map((agent) => (
                          <button
                            key={agent.id}
                            className={agent.id === selectedId ? "run active" : "run"}
                            onClick={() => setSelectedId(agent.id)}
                          >
                            <span className={`type-dot ${agent.type}`} />
                            <span className="run-meta">
                              <em>{agent.name}</em>
                              <small>
                                <span className={`duty-badge ${agent.status}`}>
                                  {agent.status === "active" ? "activo" : "reserva"}
                                </span>{" "}
                                {agent.ktag_count} ktags · {agent.id}
                              </small>
                            </span>
                          </button>
                        ))}
                      </div>
                    )
                  )}
                </>
              )}
            </li>
          );
        })}
        </ul>
      </aside>

      <main className="main agents-main">
        {!detail && <p className="empty pad">Elegí un agente para editar su RAG.</p>}
        {detail && (
          <>
            <section className="ktags-pane">
              <div className="agent-header">
                <h1>{detail.name}</h1>
                {editingGoal ? (
                  <div className="goal-edit">
                    <label>
                      Descripción
                      <textarea
                        value={goalDraft}
                        onChange={(e) => setGoalDraft(e.target.value)}
                      />
                    </label>
                    <div className="row">
                      <button
                        className="primary"
                        type="button"
                        disabled={savingGoal}
                        onClick={saveGoal}
                      >
                        {savingGoal ? "Guardando…" : "Guardar"}
                      </button>
                      <button
                        type="button"
                        disabled={savingGoal}
                        onClick={() => setEditingGoal(false)}
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                ) : (
                  <p className="muted goal-line">
                    <span className={`duty-badge ${detail.status}`}>
                      {detail.status === "active" ? "activo" : "reserva"}
                    </span>
                    <span className={`type-badge ${detail.type}`}>{TYPE_LABEL[detail.type]}</span>
                    <span className="goal-text">Descripción: {detail.goal}</span>
                    <button
                      type="button"
                      className="icon-btn"
                      title="Editar descripción"
                      aria-label="Editar descripción"
                      onClick={startEditGoal}
                    >
                      <PencilIcon />
                    </button>
                  </p>
                )}
                <div className="row agent-actions">
                  <button
                    className="primary"
                    type="button"
                    disabled={activating || editingInstructions}
                    onClick={toggleDuty}
                  >
                    {activating
                      ? "Cambiando…"
                      : isActive
                        ? "Pasar a reserva"
                        : "Pasar a activo"}
                  </button>
                  <button
                    className="primary"
                    type="button"
                    disabled={editingInstructions}
                    onClick={addKtag}
                  >
                    Agregar ktag
                  </button>
                  <button
                    className={`instruct${editingInstructions ? " active" : ""}`}
                    type="button"
                    onClick={() =>
                      editingInstructions
                        ? setEditingInstructions(false)
                        : startEditInstructions()
                    }
                  >
                    Editar instrucciones
                  </button>
                </div>
              </div>
              {error && <p className="error">{error}</p>}
              {editingInstructions ? (
                <div className="instructions-edit">
                  <p className="hint">
                    Estas instrucciones definen tono y comportamiento. Los ktags aportan datos del
                    negocio; no reemplazan este texto.
                  </p>
                  <label>
                    Instrucciones
                    <textarea
                      value={instructionsDraft}
                      onChange={(e) => setInstructionsDraft(e.target.value)}
                    />
                  </label>
                  <div className="row">
                    <button
                      className="instruct"
                      type="button"
                      disabled={savingInstructions}
                      onClick={saveInstructions}
                    >
                      {savingInstructions ? "Guardando…" : "Guardar instrucciones"}
                    </button>
                    <button
                      type="button"
                      disabled={savingInstructions}
                      onClick={() => setEditingInstructions(false)}
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              ) : (
                <>
              <p className="hint">
                El conocimiento se segmenta en ktags (nombre + valor). Al guardar, el RAG se
                actualiza.
              </p>
              <div className="ktag-list">
                {detail.ktags.length === 0 && <p className="empty">Todavía no hay ktags.</p>}
                {detail.ktags.map((ktag) => {
                  const open = openIds[ktag.id] ?? false;
                  const draft = drafts[ktag.id] ?? ktag;
                  return (
                    <article key={ktag.id} className="ktag-card">
                      <header>
                        <button
                          type="button"
                          className="ktag-toggle"
                          onClick={() =>
                            setOpenIds((prev) => ({ ...prev, [ktag.id]: !open }))
                          }
                        >
                          <span>{open ? "▾" : "▸"}</span>
                          <strong>{draft.name}</strong>
                        </button>
                        <button
                          type="button"
                          disabled={savingId === ktag.id}
                          onClick={() => removeKtag(ktag.id)}
                        >
                          Borrar
                        </button>
                      </header>
                      {open && (
                        <div className="ktag-body">
                          <label>
                            Nombre
                            <input
                              value={draft.name}
                              onChange={(e) => updateDraft(ktag.id, { name: e.target.value })}
                            />
                          </label>
                          <label>
                            Valor
                            <textarea
                              value={draft.value}
                              onChange={(e) => updateDraft(ktag.id, { value: e.target.value })}
                            />
                          </label>
                          <button
                            className="primary"
                            type="button"
                            disabled={savingId === ktag.id}
                            onClick={() => saveKtag(ktag.id)}
                          >
                            {savingId === ktag.id ? "Guardando…" : "Guardar"}
                          </button>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
                </>
              )}
            </section>

            <section className="chat-pane">
              <h2>Probar RAG</h2>
              {!isActive && (
                <p className="hint">
                  Este agente está en reserva. Ejecutá un work order que lo active para poder
                  chatear. El nombre y la descripción funcionan como ktag preliminar.
                </p>
              )}
              <div className="chat-log" ref={chatRef}>
                {chat.length === 0 && (
                  <p className="empty">
                    {isActive
                      ? "Escribí una consulta para ver qué recupera el agente."
                      : "El chat se habilita cuando el agente pasa a activo."}
                  </p>
                )}
                {chat.map((msg, i) => (
                  <article key={i} className={`bubble ${msg.role}`}>
                    <p>{msg.text}</p>
                    {!!msg.citations?.length && (
                      <ul className="citations">
                        {msg.citations.map((c) => (
                          <li key={`${c.name}-${c.score}`}>
                            {c.name}
                            <small> {c.score.toFixed(2)}</small>
                          </li>
                        ))}
                      </ul>
                    )}
                  </article>
                ))}
              </div>
              <form className="chat-form" onSubmit={sendChat}>
                <input
                  value={draftMessage}
                  onChange={(e) => setDraftMessage(e.target.value)}
                  placeholder={
                    isActive ? "Preguntá al agente…" : "Agente en reserva"
                  }
                  disabled={chatBusy || !isActive}
                />
                <button
                  className="primary"
                  disabled={chatBusy || !isActive || !draftMessage.trim()}
                >
                  {chatBusy ? "…" : "Enviar"}
                </button>
              </form>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
