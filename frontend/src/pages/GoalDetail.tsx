import { motion, AnimatePresence } from "framer-motion";
import {
  ArrowLeft,
  RefreshCw,
  AlertCircle,
  Key,
  Eye,
  EyeOff,
  X,
  Play,
  Pause,
  StepForward,
  CheckCircle2,
  Save,
} from "lucide-react";
import { useState, useEffect, useCallback, useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";
import useSWR from "swr";
import { LiveLog } from "../components/LiveLog";
import { OutputDisplay } from "../components/OutputDisplay";
import { StatusBadge } from "../components/StatusBadge";
import { TaskDAG, tasksToPlanInput } from "../components/TaskDAG";
import { TaskPanel } from "../components/TaskPanel";
import { AppNav } from "../components/AppNav";
import { AppBackground } from "../components/AppBackground";
import { ModelErrorBanner } from "../components/ModelErrorBanner";
import { api, type TaskDetail } from "../lib/api";
import { useSSE } from "../lib/sse";

const ACTIVE_STATUSES = new Set([
  "NEW",
  "PLANNING",
  "PLANNING_COMPLETED",
  "RUNNING",
  "WAITING_APPROVAL",
]);

const AGENTS = ["researcher", "writer", "coder", "integrator"] as const;

interface CredentialRequest {
  task_id: string;
  credential: string;
  provider: string;
  message: string;
}

interface ApprovalRequest {
  task_id: string;
  agent: string;
  description: string;
  inputs?: Record<string, unknown>;
}

function CredentialBanner({
  req,
  onDismiss,
}: {
  req: CredentialRequest;
  onDismiss: () => void;
}) {
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    if (!value.trim()) return;
    setSaving(true);
    setErr(null);
    try {
      await api.updateApiKey(req.provider, value.trim());
      onDismiss();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      className="mx-5 mt-4 rounded-xl border border-amber-500/30 bg-amber-500/5 p-4"
    >
      <div className="flex items-start gap-3">
        <Key className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-amber-300">Credential required</p>
          <p className="text-xs text-amber-300/70 mt-0.5">{req.message}</p>
          <div className="flex items-center gap-2 mt-3">
            <div className="flex-1 flex items-center gap-2 rounded-lg border border-white/12 bg-white/3 px-3 py-2">
              <input
                type={show ? "text" : "password"}
                value={value}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") save(); }}
                placeholder={`Paste ${req.credential}…`}
                autoFocus
                className="flex-1 bg-transparent text-xs font-mono text-white outline-none placeholder:text-text-muted"
              />
              <button onClick={() => setShow((s) => !s)} className="text-text-muted hover:text-white transition-colors">
                {show ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
              </button>
            </div>
            <button
              onClick={save}
              disabled={saving || !value.trim()}
              className="px-4 py-2 rounded-lg text-xs font-semibold bg-amber-500 text-black hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {saving ? "Saving…" : "Save & Resume"}
            </button>
          </div>
          {err && <p className="mt-1.5 text-xs text-danger">{err}</p>}
        </div>
        <button onClick={onDismiss} className="text-text-muted hover:text-white transition-colors shrink-0">
          <X className="w-4 h-4" />
        </button>
      </div>
    </motion.div>
  );
}

function TaskEditorDrawer({
  task,
  terminalId,
  onClose,
  onChange,
  onSetTerminal,
}: {
  task: TaskDetail;
  terminalId: string | null;
  onClose: () => void;
  onChange: (updated: TaskDetail) => void;
  onSetTerminal: (id: string) => void;
}) {
  const [inputsJson, setInputsJson] = useState(JSON.stringify(task.inputs ?? {}, null, 2));
  const [jsonError, setJsonError] = useState<string | null>(null);

  useEffect(() => {
    setInputsJson(JSON.stringify(task.inputs ?? {}, null, 2));
    setJsonError(null);
  }, [task.id, task.inputs]);

  const applyInputs = () => {
    try {
      const parsed = JSON.parse(inputsJson) as Record<string, unknown>;
      setJsonError(null);
      onChange({ ...task, inputs: parsed });
    } catch {
      setJsonError("Invalid JSON");
    }
  };

  return (
    <motion.div
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ type: "spring", damping: 28, stiffness: 320 }}
      className="absolute inset-y-0 right-0 w-full max-w-md border-l border-white/10 bg-black/90 backdrop-blur-xl z-20 flex flex-col shadow-2xl"
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/8">
        <div>
          <p className="text-sm font-semibold text-white">Edit Task</p>
          <p className="text-xs text-text-muted font-mono truncate">{task.id}</p>
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-white p-1">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider font-medium">Agent</label>
          <select
            value={task.agent_name}
            onChange={(e) => onChange({ ...task, agent_name: e.target.value })}
            className="mt-1 w-full rounded-lg border border-white/12 bg-white/5 px-3 py-2 text-sm text-white outline-none"
          >
            {AGENTS.map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider font-medium">Model override</label>
          <input
            value={task.model_override ?? ""}
            onChange={(e) => onChange({ ...task, model_override: e.target.value || null })}
            placeholder="e.g. anthropic/claude-sonnet-4-6 (optional)"
            className="mt-1 w-full rounded-lg border border-white/12 bg-white/5 px-3 py-2 text-xs font-mono text-white outline-none placeholder:text-text-muted"
          />
        </div>

        <div>
          <label className="text-xs text-text-muted uppercase tracking-wider font-medium">Description</label>
          <textarea
            value={task.description}
            onChange={(e) => onChange({ ...task, description: e.target.value })}
            rows={3}
            className="mt-1 w-full rounded-lg border border-white/12 bg-white/5 px-3 py-2 text-sm text-white outline-none resize-none"
          />
        </div>

        <div>
          <label className="flex items-center gap-2 text-sm text-gray-200 cursor-pointer">
            <input
              type="checkbox"
              checked={task.requires_approval ?? false}
              onChange={(e) => onChange({ ...task, requires_approval: e.target.checked })}
              className="rounded border-white/20"
            />
            Require approval before running
          </label>
        </div>

        <div>
          <label className="flex items-center gap-2 text-sm text-gray-200 cursor-pointer">
            <input
              type="radio"
              name="terminal"
              checked={terminalId === task.id}
              onChange={() => onSetTerminal(task.id)}
            />
            Terminal task (final output)
          </label>
        </div>

        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="text-xs text-text-muted uppercase tracking-wider font-medium">Inputs (JSON)</label>
            <button
              onClick={applyInputs}
              className="text-xs text-accent hover:text-accent/80"
            >
              Apply JSON
            </button>
          </div>
          <textarea
            value={inputsJson}
            onChange={(e) => setInputsJson(e.target.value)}
            rows={10}
            className="w-full rounded-lg border border-white/12 bg-black/40 px-3 py-2 text-xs font-mono text-gray-300 outline-none resize-none"
          />
          {jsonError && <p className="text-xs text-danger mt-1">{jsonError}</p>}
        </div>
      </div>
    </motion.div>
  );
}

function ApprovalOverlay({
  req,
  task,
  onDismiss,
  onApproved,
}: {
  req: ApprovalRequest;
  task: TaskDetail | undefined;
  onDismiss: () => void;
  onApproved: () => void;
}) {
  const [inputsJson, setInputsJson] = useState(
    JSON.stringify(req.inputs ?? task?.inputs ?? {}, null, 2),
  );
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const approve = async () => {
    setSaving(true);
    setErr(null);
    try {
      let inputs: Record<string, unknown> | undefined;
      try {
        inputs = JSON.parse(inputsJson) as Record<string, unknown>;
      } catch {
        setErr("Invalid inputs JSON");
        setSaving(false);
        return;
      }
      await api.approveTask(req.task_id, inputs);
      onApproved();
      onDismiss();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
    >
      <motion.div
        initial={{ scale: 0.95, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.95, opacity: 0 }}
        className="w-full max-w-lg rounded-2xl border border-orange-500/30 bg-[#0d0d0d] p-6 shadow-2xl"
      >
        <div className="flex items-start gap-3 mb-4">
          <CheckCircle2 className="w-5 h-5 text-orange-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-base font-semibold text-orange-200">Task awaiting approval</p>
            <p className="text-sm text-gray-400 mt-1">
              <span className="font-medium text-gray-300">{req.agent}</span> — {req.description}
            </p>
          </div>
        </div>

        <label className="text-xs text-text-muted uppercase tracking-wider font-medium">Review / edit inputs</label>
        <textarea
          value={inputsJson}
          onChange={(e) => setInputsJson(e.target.value)}
          rows={8}
          className="mt-1 w-full rounded-lg border border-white/12 bg-black/40 px-3 py-2 text-xs font-mono text-gray-300 outline-none resize-none"
        />
        {err && <p className="text-xs text-danger mt-2">{err}</p>}

        <div className="flex items-center justify-end gap-2 mt-4">
          <button
            onClick={onDismiss}
            className="px-4 py-2 rounded-lg text-xs text-text-muted hover:text-white transition-colors"
          >
            Later
          </button>
          <button
            onClick={approve}
            disabled={saving}
            className="px-4 py-2 rounded-lg text-xs font-semibold bg-orange-500 text-black hover:bg-orange-400 disabled:opacity-40 transition-all"
          >
            {saving ? "Approving…" : "Approve & Run"}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}

function fetcher(id: string) {
  return api.getGoal(id);
}

export function GoalDetail() {
  const { id } = useParams<{ id: string }>();
  const nav = useNavigate();
  const { data, isLoading, error, mutate } = useSWR(
    id ? `/api/goals/${id}` : null,
    () => fetcher(id!),
    { refreshInterval: (d) => (d && ACTIVE_STATUSES.has(d.status) ? 2000 : 0) },
  );

  const isActive = data ? ACTIVE_STATUSES.has(data.status) : false;
  const sseEvents = useSSE(id, isActive);

  const [credRequest, setCredRequest] = useState<CredentialRequest | null>(null);
  const [approvalRequest, setApprovalRequest] = useState<ApprovalRequest | null>(null);
  const [draftTasks, setDraftTasks] = useState<TaskDetail[] | null>(null);
  const [terminalId, setTerminalId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [planSaving, setPlanSaving] = useState(false);
  const [controlBusy, setControlBusy] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  const editable = useMemo(
    () =>
      data?.status === "PLANNING_COMPLETED" ||
      (data?.status === "RUNNING" && !!data.is_paused),
    [data?.status, data?.is_paused],
  );

  useEffect(() => {
    if (!data?.tasks) return;
    setDraftTasks(data.tasks);
    const terminal =
      (data.plan as { terminal?: string } | null)?.terminal ??
      data.tasks[data.tasks.length - 1]?.id ??
      null;
    setTerminalId(terminal);
  }, [data?.goal_id, data?.status, data?.tasks, data?.plan]);

  useEffect(() => {
    const last = [...sseEvents].reverse().find((e) => e.event === "credential_request");
    if (last) {
      setCredRequest(last.data as unknown as CredentialRequest);
    }
  }, [sseEvents]);

  useEffect(() => {
    const last = [...sseEvents].reverse().find((e) => e.event === "task_approval_required");
    if (last) {
      setApprovalRequest(last.data as unknown as ApprovalRequest);
    }
  }, [sseEvents]);

  useEffect(() => {
    const waiting = data?.tasks?.find((t) => t.status === "WAITING_APPROVAL");
    if (waiting && !approvalRequest) {
      setApprovalRequest({
        task_id: waiting.id,
        agent: waiting.agent_name,
        description: waiting.description,
        inputs: waiting.inputs,
      });
    }
  }, [data?.tasks, approvalRequest]);

  const displayTasks = draftTasks ?? data?.tasks ?? [];
  const selectedTask = displayTasks.find((t) => t.id === selectedTaskId);

  const handleTasksChange = useCallback((tasks: TaskDetail[]) => {
    setDraftTasks(tasks);
  }, []);

  const handleTaskEdit = useCallback((updated: TaskDetail) => {
    setDraftTasks((prev) => (prev ?? []).map((t) => (t.id === updated.id ? updated : t)));
  }, []);

  const savePlan = async () => {
    if (!id || !draftTasks?.length || !terminalId) return;
    setPlanSaving(true);
    setPlanError(null);
    try {
      const updated = await api.updatePlan(id, tasksToPlanInput(draftTasks), terminalId);
      await mutate(updated, { revalidate: false });
      setDraftTasks(updated.tasks);
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : "Failed to save plan");
    } finally {
      setPlanSaving(false);
    }
  };

  const approvePlan = async () => {
    if (!id) return;
    if (draftTasks && terminalId) {
      await savePlan();
    }
    setControlBusy(true);
    try {
      await api.approveGoal(id);
      await mutate();
    } finally {
      setControlBusy(false);
    }
  };

  const togglePause = async () => {
    if (!id || !data) return;
    setControlBusy(true);
    try {
      if (data.is_paused) {
        await api.resumeGoal(id);
      } else {
        await api.pauseGoal(id);
      }
      await mutate();
    } finally {
      setControlBusy(false);
    }
  };

  const stepNext = async () => {
    if (!id) return;
    setControlBusy(true);
    try {
      await api.stepGoal(id);
      await mutate();
    } catch (e) {
      setPlanError(e instanceof Error ? e.message : "No ready task");
    } finally {
      setControlBusy(false);
    }
  };

  if (isLoading) {
    return (
      <div className="relative min-h-screen" style={{ background: "#000" }}>
        <AppBackground />
        <div className="relative z-10 flex flex-col min-h-screen">
          <AppNav />
          <div className="flex-1 flex items-center justify-center">
            <div className="flex items-center gap-2.5 text-text-muted">
              <RefreshCw className="w-4 h-4 animate-spin" />
              <span className="text-sm">Loading goal…</span>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="relative min-h-screen" style={{ background: "#000" }}>
        <AppBackground />
        <div className="relative z-10 flex flex-col min-h-screen">
          <AppNav />
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-center">
              <AlertCircle className="w-8 h-8 text-danger/70" />
              <p className="text-sm text-text-muted">
                {error ? `Error: ${error.message}` : "Goal not found."}
              </p>
              <button
                onClick={() => nav("/app")}
                className="text-xs text-accent hover:text-accent/80 transition-colors"
              >
                ← Back to Dashboard
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const tasks = displayTasks;
  const canDebug = ["PLANNING_COMPLETED", "RUNNING"].includes(data.status);

  return (
    <div className="relative min-h-screen" style={{ background: "#000" }}>
      <AppBackground />

      <AnimatePresence>
        {approvalRequest && (
          <ApprovalOverlay
            req={approvalRequest}
            task={tasks.find((t) => t.id === approvalRequest.task_id)}
            onDismiss={() => setApprovalRequest(null)}
            onApproved={() => mutate()}
          />
        )}
      </AnimatePresence>

      <div className="relative z-10 flex flex-col min-h-screen">
      <AppNav />

      {/* Goal header + debug controls */}
      <div className="border-b border-white/6 bg-black/40 backdrop-blur-md">
        <div className="max-w-none px-6 py-4 flex items-center gap-4">
          <button
            onClick={() => nav("/app")}
            className="flex items-center gap-1.5 text-text-muted hover:text-white text-xs font-medium transition-colors shrink-0"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            Dashboard
          </button>
          <div className="w-px h-4 bg-white/10" />
          <p className="flex-1 min-w-0 truncate text-sm font-medium text-gray-200">{data.title}</p>
          <StatusBadge status={data.status} />
        </div>

        {canDebug && (
          <div className="px-6 pb-3 flex flex-wrap items-center gap-2">
            {data.status === "PLANNING_COMPLETED" && (
              <>
                <button
                  onClick={savePlan}
                  disabled={planSaving || !editable}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-white/12 bg-white/5 hover:bg-white/10 disabled:opacity-40 transition-all"
                >
                  <Save className="w-3.5 h-3.5" />
                  {planSaving ? "Saving…" : "Save Plan"}
                </button>
                <button
                  onClick={approvePlan}
                  disabled={controlBusy}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-accent text-white hover:bg-accent/90 disabled:opacity-40 transition-all"
                >
                  <Play className="w-3.5 h-3.5" />
                  Approve & Run
                </button>
              </>
            )}
            {data.status === "RUNNING" && (
              <>
                <button
                  onClick={togglePause}
                  disabled={controlBusy}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-white/12 bg-white/5 hover:bg-white/10 disabled:opacity-40 transition-all"
                >
                  {data.is_paused ? <Play className="w-3.5 h-3.5" /> : <Pause className="w-3.5 h-3.5" />}
                  {data.is_paused ? "Resume" : "Pause"}
                </button>
                <button
                  onClick={stepNext}
                  disabled={controlBusy}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-white/12 bg-white/5 hover:bg-white/10 disabled:opacity-40 transition-all"
                >
                  <StepForward className="w-3.5 h-3.5" />
                  Step Next
                </button>
                {editable && (
                  <button
                    onClick={savePlan}
                    disabled={planSaving}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-white/12 bg-white/5 hover:bg-white/10 disabled:opacity-40 transition-all"
                  >
                    <Save className="w-3.5 h-3.5" />
                    Save Plan
                  </button>
                )}
              </>
            )}
            {data.is_paused && (
              <span className="text-xs text-amber-400/80">Execution paused</span>
            )}
            {editable && data.status === "PLANNING_COMPLETED" && (
              <span className="text-xs text-purple-400/80">Drag nodes & connect edges to edit the plan</span>
            )}
            {planError && <span className="text-xs text-danger">{planError}</span>}
          </div>
        )}
      </div>

      {/* Body */}
      <div className="flex-1 flex flex-col lg:flex-row overflow-hidden">
        {/* Left: DAG + Tasks */}
        <div className="flex-1 flex flex-col overflow-hidden border-r border-white/8 bg-black/20 backdrop-blur-sm relative">
          {/* DAG */}
          {tasks.length > 0 && (
            <div className="h-64 lg:h-80 border-b border-white/6 relative">
              <TaskDAG
                tasks={tasks}
                editable={editable}
                selectedTaskId={selectedTaskId}
                onSelectTask={(t) => setSelectedTaskId(t?.id ?? null)}
                onTasksChange={handleTasksChange}
              />
              <AnimatePresence>
                {selectedTask && editable && (
                  <TaskEditorDrawer
                    task={selectedTask}
                    terminalId={terminalId}
                    onClose={() => setSelectedTaskId(null)}
                    onChange={handleTaskEdit}
                    onSetTerminal={setTerminalId}
                  />
                )}
              </AnimatePresence>
            </div>
          )}

          {/* Credential banner */}
          <AnimatePresence>
            {credRequest && (
              <CredentialBanner
                req={credRequest}
                onDismiss={() => setCredRequest(null)}
              />
            )}
          </AnimatePresence>

          {/* Tasks */}
          <div className="flex-1 overflow-y-auto p-5 space-y-2">
            <div className="flex items-center gap-2 mb-4">
              <p className="text-xs text-text-muted uppercase tracking-widest font-semibold">
                Tasks
              </p>
              {tasks.length > 0 && (
                <span className="px-1.5 py-0.5 rounded-md bg-white/6 text-xs text-text-muted">
                  {tasks.length}
                </span>
              )}
            </div>

            {tasks.length === 0 && (
              <div className="flex items-center gap-2 text-text-muted text-sm py-4">
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span>Orchestrator is planning tasks…</span>
              </div>
            )}

            {tasks.map((t) => (
              <TaskPanel key={t.id} task={t} />
            ))}

            {/* Output */}
            {data.output && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-5"
              >
                <p className="text-xs text-text-muted uppercase tracking-widest font-semibold mb-3">
                  Output
                </p>
                <OutputDisplay output={data.output} />
              </motion.div>
            )}

            {/* Error */}
            {data.error && (
              <div className="rounded-xl border border-danger/30 bg-danger/5 p-4 mt-4">
                <div className="flex items-center gap-2 mb-1">
                  <AlertCircle className="w-4 h-4 text-danger" />
                  <p className="text-sm text-red-400 font-semibold">Goal Failed</p>
                </div>
                <p className="text-xs text-red-300 font-mono leading-relaxed">{data.error}</p>
              </div>
            )}

            {/* Model error toast */}
            {data.error && <ModelErrorBanner error={data.error} />}
          </div>
        </div>

        {/* Right: Live Log */}
        <div className="w-full lg:w-96 flex flex-col border-t lg:border-t-0 border-white/8 bg-black/30 backdrop-blur-sm">
          <div className="border-b border-white/6 px-5 py-3 flex items-center justify-between">
            <p className="text-xs text-text-muted uppercase tracking-widest font-semibold">
              Live Log
            </p>
            {isActive && (
              <span className="flex items-center gap-1.5 text-xs text-accent">
                <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
                Streaming
              </span>
            )}
          </div>
          <div className="flex-1 overflow-hidden p-4">
            <LiveLog events={sseEvents} />
          </div>
        </div>
      </div>
      </div>
    </div>
  );
}
