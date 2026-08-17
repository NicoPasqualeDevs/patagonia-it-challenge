export type Status = "running" | "success" | "partial" | "failed";

export type TraceEvent = {
  ts?: string;
  run_id?: string;
  phase: string;
  thought?: string;
  tool?: string | null;
  args?: Record<string, unknown> | null;
  result?: unknown;
  error?: string | null;
  decision?: string | null;
  status?: Status;
};

export type NodeStatus = "pending" | "running" | "ok" | "failed" | "retry" | "skipped";
export type NodeKind = "phase" | "tool";
export type EdgeKind = "default" | "fallback" | "detour" | "containment";

export type GraphNode = {
  id: string;
  kind: NodeKind;
  label: string;
  tool?: string;
  status: NodeStatus;
  attempts: number;
  decision?: string | null;
  thought?: string;
  why?: string;
  args?: unknown;
  result?: unknown;
  error?: string | null;
  contained?: boolean;
  decisions?: string[];
  events: TraceEvent[];
  column: number;
  lane: number;
  parentId?: string;
};

export type GraphEdge = {
  id: string;
  from: string;
  to: string;
  kind: EdgeKind;
};

export type ExecutionGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

const PHASE_LABEL: Record<string, string> = {
  interpret: "Interpretar",
  validate: "Validar",
  plan: "Plan",
  report: "Reporte",
};

const TOOL_LABEL: Record<string, string> = {
  create_support_ticket: "Ticket de soporte",
  execute_agent: "Ejecutar agente",
};

const AGENT_TOOLS = new Set([
  "execute_agent",
  "activate_agent",
  "lookup_agent",
  "enable_capability",
  "attach_knowledge",
  "create_or_update_agent",
]);

const DETOUR_TOOLS = new Set([
  "get_weather",
  "get_dollar",
  "get_holidays",
  "get_local_time",
  "lookup_food",
  "geocode_address",
  "activate_agent",
]);

function isDetour(node: GraphNode): boolean {
  return node.kind === "tool" && Boolean(node.tool && DETOUR_TOOLS.has(node.tool));
}

function detourEdgeKind(tool?: string): EdgeKind {
  return tool === "create_support_ticket" ? "fallback" : "detour";
}

function nodesBetween(sequence: GraphNode[], from: GraphNode, to: GraphNode): GraphNode[] {
  const start = sequence.findIndex((node) => node.id === from.id);
  const end = sequence.findIndex((node) => node.id === to.id);
  if (start < 0 || end < 0 || end <= start) return [];
  return sequence.slice(start + 1, end);
}

function phaseNode(id: string): GraphNode {
  return {
    id,
    kind: "phase",
    label: PHASE_LABEL[id] ?? id,
    status: "pending",
    attempts: 0,
    events: [],
    column: 0,
    lane: 0,
  };
}

function toolNode(id: string, tool: string): GraphNode {
  return {
    id,
    kind: "tool",
    label: TOOL_LABEL[tool] ?? tool,
    tool,
    status: "pending",
    attempts: 0,
    events: [],
    column: 0,
    lane: 0,
  };
}

function attachEvent(node: GraphNode, event: TraceEvent): void {
  node.events.push(event);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function firstName(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string") {
      const text = value.trim();
      if (text && !text.startsWith("$")) return text;
    }
  }
  return "";
}

function agentNameFrom(value: unknown): string {
  if (!isRecord(value)) return "";
  const nested = isRecord(value.agent) ? value.agent : null;
  return firstName(value.agent_name, nested?.name, nested?.id, value.name);
}

export function actorOf(node: GraphNode): string {
  if (node.kind === "phase" || !node.tool || !AGENT_TOOLS.has(node.tool)) {
    return "orquestador";
  }
  const fromNode = agentNameFrom(node.result) || agentNameFrom(node.args);
  if (fromNode) return fromNode;
  for (const event of node.events) {
    const found = agentNameFrom(event.result) || agentNameFrom(event.args);
    if (found) return found;
  }
  const agentId = isRecord(node.args) ? firstName(node.args.agent_id) : "";
  return agentId || "orquestador";
}

function plannedActions(result: unknown): Array<{ tool: string; args?: unknown; why?: string }> {
  const items = Array.isArray(result)
    ? result
    : isRecord(result) && Array.isArray(result.actions)
      ? result.actions
      : [];
  const actions: Array<{ tool: string; args?: unknown; why?: string }> = [];
  for (const item of items) {
    if (isRecord(item) && typeof item.tool === "string" && item.tool) {
      actions.push({
        tool: item.tool,
        args: item.args,
        why: typeof item.why === "string" ? item.why : undefined,
      });
    }
  }
  return actions;
}

function applyPhaseStart(node: GraphNode, event: TraceEvent): void {
  if (node.status === "pending") node.status = "running";
  if (event.thought) node.thought = event.thought;
  attachEvent(node, event);
}

function applyPhaseDone(node: GraphNode, event: TraceEvent, failed: boolean): void {
  node.status = failed ? "failed" : "ok";
  if (event.thought) node.thought = event.thought;
  if (event.result != null) node.result = event.result;
  if (event.error) node.error = event.error;
  if (event.decision) node.decision = event.decision;
  if (event.args) node.args = event.args;
  if (isRecord(event.result) && Array.isArray(event.result.decisions)) {
    node.decisions = event.result.decisions.filter(
      (item): item is string => typeof item === "string" && item.length > 0
    );
  }
  attachEvent(node, event);
}

function lastStartedMainId(mainIds: string[], nodes: Map<string, GraphNode>): string {
  let last = "plan";
  for (const id of mainIds) {
    const node = nodes.get(id);
    if (!node || node.lane !== 0) continue;
    if (id === "report") continue;
    if (node.status !== "pending") last = id;
  }
  return last;
}

function insertMainAfter(
  mainIds: string[],
  afterId: string,
  newId: string
): void {
  const reportAt = mainIds.indexOf("report");
  const afterAt = mainIds.indexOf(afterId);
  let at = afterAt >= 0 ? afterAt + 1 : mainIds.length;
  if (reportAt >= 0 && at > reportAt) at = reportAt;
  mainIds.splice(at, 0, newId);
}

export function buildExecutionGraph(events: TraceEvent[]): ExecutionGraph {
  const nodes = new Map<string, GraphNode>([
    ["interpret", phaseNode("interpret")],
    ["validate", phaseNode("validate")],
    ["plan", phaseNode("plan")],
  ]);
  const mainIds = ["interpret", "validate", "plan"];
  let toolSeq = 0;
  let currentToolId: string | null = null;

  const findPendingTool = (tool: string): GraphNode | undefined => {
    for (const id of mainIds) {
      const node = nodes.get(id);
      if (node?.kind === "tool" && node.tool === tool && node.status === "pending") {
        return node;
      }
    }
    return undefined;
  };

  const ensureReport = (): GraphNode => {
    const existing = nodes.get("report");
    if (existing) return existing;
    const node = phaseNode("report");
    nodes.set("report", node);
    mainIds.push("report");
    return node;
  };

  const createMainTool = (tool: string, afterId?: string): GraphNode => {
    toolSeq += 1;
    const id = `tool:${tool}:${toolSeq}`;
    const node = toolNode(id, tool);
    nodes.set(id, node);
    insertMainAfter(mainIds, afterId ?? lastStartedMainId(mainIds, nodes), id);
    return node;
  };

  for (const event of events) {
    if (event.phase === "interpret") {
      const node = nodes.get("interpret")!;
      if (event.result != null) {
        const failed = isRecord(event.result) && event.result.can_proceed === false;
        applyPhaseDone(node, event, failed);
      } else {
        applyPhaseStart(node, event);
      }
      continue;
    }

    if (event.phase === "validate") {
      const node = nodes.get("validate")!;
      const failed = event.decision === "stop" || Boolean(event.error);
      applyPhaseDone(node, event, failed);
      continue;
    }

    if (event.phase === "plan") {
      const node = nodes.get("plan")!;
      if (event.result != null) {
        applyPhaseDone(node, event, false);
        for (const id of [...mainIds]) {
          const existing = nodes.get(id);
          if (existing?.kind === "tool" && existing.status === "pending") {
            mainIds.splice(mainIds.indexOf(id), 1);
            nodes.delete(id);
          }
        }
        let after = lastStartedMainId(mainIds, nodes);
        for (const action of plannedActions(event.result)) {
          const created = createMainTool(action.tool, after);
          if (action.args != null) created.args = action.args;
          if (action.why) created.why = action.why;
          after = created.id;
        }
        ensureReport();
      } else {
        applyPhaseStart(node, event);
      }
      continue;
    }

    if (event.phase === "execute") {
      const tool = event.tool;
      if (!tool) continue;

      let node = findPendingTool(tool);
      if (!node && currentToolId) {
        const current = nodes.get(currentToolId);
        if (current?.tool === tool && (current.status === "retry" || current.status === "running")) {
          node = current;
        }
      }
      if (!node) node = createMainTool(tool);

      node.status = "running";
      node.attempts = Math.max(node.attempts, 1);
      node.thought = event.thought;
      node.args = event.args ?? node.args;
      node.error = event.error ?? null;
      if (event.decision) node.decision = event.decision;
      attachEvent(node, event);
      currentToolId = node.id;
      ensureReport();
      continue;
    }

    if (event.phase === "observe") {
      const tool = event.tool;
      let node =
        (tool
          ? [...nodes.values()]
              .reverse()
              .find((n) => n.tool === tool && n.status !== "pending")
          : undefined) ?? (currentToolId ? nodes.get(currentToolId) : undefined);
      if (!node) continue;

      if (event.thought) node.thought = event.thought;
      if (event.args) node.args = event.args;
      if (event.result != null) node.result = event.result;
      if (event.error) node.error = event.error;
      if (event.decision) node.decision = event.decision;

      const skipped = isRecord(event.result) && (
        event.result.skipped === true || event.result.disabled === true
      );
      if (event.decision === "retry") {
        node.status = "retry";
        node.attempts = Math.max(node.attempts, 1) + 1;
      } else if (skipped) {
        node.status = "skipped";
      } else if (event.error && event.decision !== "continue") {
        node.status = "failed";
      } else if (event.result != null || event.decision === "continue") {
        node.status = "ok";
        if (!event.error) node.error = null;
        if (!node.attempts) node.attempts = 1;
      }
      attachEvent(node, event);
      continue;
    }

    if (event.phase === "decide") {
      const node = currentToolId ? nodes.get(currentToolId) : undefined;
      if (node && event.decision) node.decision = event.decision;
      if (node && event.thought) node.thought = event.thought;
      if (node) attachEvent(node, event);
      continue;
    }

    if (event.phase === "report") {
      const node = ensureReport();
      const status =
        isRecord(event.result) && typeof event.result.status === "string"
          ? event.result.status
          : undefined;
      node.status =
        status === "failed" ? "failed" : status === "partial" ? "retry" : "ok";
      node.contained = Boolean(
        isRecord(event.result) && event.result.contained === true
      );
      node.thought = event.thought;
      node.result = event.result;
      node.error = event.error;
      node.decision = event.decision;
      attachEvent(node, event);
    }
  }

  const ordered = mainIds
    .map((id) => nodes.get(id))
    .filter((n): n is GraphNode => Boolean(n));
  assignDetourLayout(ordered);
  return { nodes: ordered, edges: buildEdges(ordered) };
}

function assignDetourLayout(sequence: GraphNode[]): void {
  let nextCol = 0;
  let i = 0;
  while (i < sequence.length) {
    const node = sequence[i];
    if (!isDetour(node)) {
      node.lane = 0;
      node.column = nextCol;
      node.parentId = undefined;
      nextCol += 1;
      i += 1;
      continue;
    }
    const prevMain = [...sequence.slice(0, i)].reverse().find((item) => !isDetour(item));
    const startCol = prevMain?.column ?? nextCol;
    let offset = 0;
    while (i < sequence.length && isDetour(sequence[i])) {
      const detour = sequence[i];
      detour.lane = 1;
      detour.column = startCol + offset;
      detour.parentId = offset === 0 ? prevMain?.id : sequence[i - 1].id;
      offset += 1;
      i += 1;
    }
    nextCol = Math.max(nextCol, startCol + offset);
  }
}

function buildEdges(sequence: GraphNode[]): GraphEdge[] {
  const edges: GraphEdge[] = [];
  const mains = sequence.filter((node) => !isDetour(node));
  for (let i = 0; i < mains.length - 1; i += 1) {
    const from = mains[i];
    const to = mains[i + 1];
    const gated =
      from.id === "plan" &&
      to.tool === "execute_agent" &&
      nodesBetween(sequence, from, to).some((node) => node.tool === "activate_agent");
    edges.push({
      id: `${from.id}->${to.id}`,
      from: from.id,
      to: to.id,
      kind: gated ? "containment" : "default",
    });
  }

  let i = 0;
  while (i < sequence.length) {
    if (!isDetour(sequence[i])) {
      i += 1;
      continue;
    }
    const group: GraphNode[] = [];
    while (i < sequence.length && isDetour(sequence[i])) {
      group.push(sequence[i]);
      i += 1;
    }
    const prevMain = group[0]?.parentId
      ? sequence.find((node) => node.id === group[0].parentId)
      : undefined;
    const nextMain = sequence.slice(i).find((node) => !isDetour(node));
    if (prevMain) {
      edges.push({
        id: `${prevMain.id}->${group[0].id}`,
        from: prevMain.id,
        to: group[0].id,
        kind: detourEdgeKind(group[0].tool),
      });
    }
    for (let j = 0; j < group.length - 1; j += 1) {
      edges.push({
        id: `${group[j].id}->${group[j + 1].id}`,
        from: group[j].id,
        to: group[j + 1].id,
        kind: detourEdgeKind(group[j + 1].tool),
      });
    }
    const last = group[group.length - 1];
    if (nextMain && last.status !== "failed" && last.status !== "retry") {
      edges.push({
        id: `${last.id}->${nextMain.id}`,
        from: last.id,
        to: nextMain.id,
        kind: detourEdgeKind(last.tool),
      });
    }
  }
  return edges;
}

export function pretty(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export const NODE_STATUS_LABEL: Record<NodeStatus, string> = {
  pending: "pendiente",
  running: "en curso",
  ok: "ok",
  failed: "fallo",
  retry: "reintento",
  skipped: "desactivada",
};
