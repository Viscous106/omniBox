import { useCallback, useEffect, useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  Position,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { Settings } from "lucide-react";
import type { TaskDetail } from "../lib/api";
import { AgentBadge } from "./AgentBadge";
import { StatusBadge } from "./StatusBadge";

interface Props {
  tasks: TaskDetail[];
  editable?: boolean;
  selectedTaskId?: string | null;
  onSelectTask?: (task: TaskDetail | null) => void;
  onTasksChange?: (tasks: TaskDetail[]) => void;
}

const STATUS_EDGE_COLOR: Record<string, string> = {
  DONE: "#22c55e",
  RUNNING: "#3b82f6",
  FAILED: "#ef4444",
  WAITING_WEBHOOK: "#f59e0b",
  WAITING_APPROVAL: "#f97316",
  READY: "#eab308",
};

type TaskNodeData = {
  task: TaskDetail;
  editable: boolean;
  selected: boolean;
  onSelect?: (task: TaskDetail) => void;
};

function TaskNodeComponent({ data }: NodeProps<TaskNodeData>) {
  const { task, editable, selected, onSelect } = data;
  return (
    <div
      className={`px-3 py-2.5 space-y-1.5 relative ${selected ? "ring-2 ring-accent/60 rounded-xl" : ""}`}
      onClick={(e) => {
        e.stopPropagation();
        onSelect?.(task);
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-500 !w-2 !h-2" />
      <div className="flex items-center justify-between gap-2">
        <AgentBadge agent={task.agent_name} />
        <div className="flex items-center gap-1">
          {task.requires_approval && (
            <span className="text-[10px] text-orange-400 font-medium">gate</span>
          )}
          <StatusBadge status={task.status} size="sm" />
        </div>
      </div>
      <p className="text-xs text-gray-300 leading-relaxed line-clamp-2 pr-6">{task.description}</p>
      {editable && (
        <button
          type="button"
          className="absolute top-2 right-2 p-1 rounded-md text-text-muted hover:text-white hover:bg-white/10 transition-colors"
          onClick={(e) => {
            e.stopPropagation();
            onSelect?.(task);
          }}
          title="Edit task"
        >
          <Settings className="w-3.5 h-3.5" />
        </button>
      )}
      <Handle type="source" position={Position.Bottom} className="!bg-gray-500 !w-2 !h-2" />
    </div>
  );
}

const nodeTypes = { taskNode: TaskNodeComponent };

function buildGraph(
  tasks: TaskDetail[],
  editable: boolean,
  selectedTaskId: string | null | undefined,
  onSelectTask?: (task: TaskDetail | null) => void,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = tasks.map((t, i) => ({
    id: t.id,
    position: { x: (i % 3) * 260, y: Math.floor(i / 3) * 130 },
    type: "taskNode",
    data: {
      task: t,
      editable,
      selected: t.id === selectedTaskId,
      onSelect: onSelectTask,
    },
    style: {
      background: "#111111",
      border: `1px solid ${STATUS_EDGE_COLOR[t.status] ?? "#1f1f1f"}`,
      borderRadius: 12,
      padding: 0,
      width: 220,
    },
  }));

  const edges: Edge[] = [];
  tasks.forEach((t) => {
    t.depends_on?.forEach?.((depId: string) => {
      edges.push({
        id: `${depId}->${t.id}`,
        source: depId,
        target: t.id,
        animated: t.status === "RUNNING",
        style: { stroke: STATUS_EDGE_COLOR[t.status] ?? "#3a3a3a" },
      });
    });
  });

  return { nodes, edges };
}

export function TaskDAG({
  tasks,
  editable = false,
  selectedTaskId,
  onSelectTask,
  onTasksChange,
}: Props) {
  const { nodes, edges } = useMemo(
    () => buildGraph(tasks, editable, selectedTaskId, onSelectTask),
    [tasks, editable, selectedTaskId, onSelectTask],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!editable || !onTasksChange || !connection.source || !connection.target) return;
      const updated = tasks.map((t) => {
        if (t.id !== connection.target) return t;
        const deps = new Set(t.depends_on ?? []);
        deps.add(connection.source!);
        return { ...t, depends_on: [...deps] };
      });
      onTasksChange(updated);
    },
    [editable, onTasksChange, tasks],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      if (!editable || !onTasksChange) return;
      let updated = [...tasks];
      for (const edge of deleted) {
        updated = updated.map((t) => {
          if (t.id !== edge.target) return t;
          return {
            ...t,
            depends_on: (t.depends_on ?? []).filter((d) => d !== edge.source),
          };
        });
      }
      onTasksChange(updated);
    },
    [editable, onTasksChange, tasks],
  );

  useEffect(() => {
    if (!editable) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onSelectTask?.(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [editable, onSelectTask]);

  if (!tasks.length) return null;

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onConnect={onConnect}
        onEdgesDelete={onEdgesDelete}
        onPaneClick={() => onSelectTask?.(null)}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={editable}
        nodesConnectable={editable}
        elementsSelectable={editable}
        edgesUpdatable={editable}
        deleteKeyCode={editable ? "Delete" : null}
        zoomOnScroll={false}
        panOnDrag
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1f1f1f" gap={20} size={1} />
        <Controls showInteractive={false} className="!bg-surface !border-border" />
      </ReactFlow>
    </div>
  );
}

export function tasksToPlanInput(tasks: TaskDetail[]) {
  return tasks.map((t) => ({
    id: t.id,
    agent: t.agent_name,
    description: t.description,
    inputs: t.inputs,
    depends_on: t.depends_on ?? [],
    requires_approval: t.requires_approval ?? false,
    model_override: t.model_override ?? null,
  }));
}
