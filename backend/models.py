from typing import Any

from pydantic import BaseModel


class SubmitGoalRequest(BaseModel):
    goal: str
    metadata: dict[str, Any] | None = None
    manual_start: bool = False


class PlanTaskInput(BaseModel):
    id: str
    agent: str
    description: str
    inputs: dict[str, Any] = {}
    depends_on: list[str] = []
    requires_approval: bool = False
    model_override: str | None = None


class UpdatePlanRequest(BaseModel):
    tasks: list[PlanTaskInput]
    terminal: str


class ApproveTaskRequest(BaseModel):
    inputs: dict[str, Any] | None = None


class GoalResponse(BaseModel):
    goal_id: str
    title: str
    goal_text: str
    status: str
    output: Any | None
    error: str | None
    plan: Any | None
    tasks: list[dict] | None
    trace_id: str
    is_paused: bool = False
    requires_plan_approval: bool = False
    step_mode: bool = False
    created_at: int
    updated_at: int


class GoalSummary(BaseModel):
    goal_id: str
    title: str
    status: str
    created_at: int
    updated_at: int


class GoalListResponse(BaseModel):
    goals: list[GoalSummary]
    total: int


class TaskDetail(BaseModel):
    id: str
    goal_id: str
    agent_name: str
    description: str
    status: str
    inputs: dict
    output: Any | None
    error: str | None
    attempt_count: int
    wait_token: str | None
    depends_on: list[str] = []
    requires_approval: bool = False
    model_override: str | None = None
    created_at: int
    updated_at: int


class TaskListResponse(BaseModel):
    tasks: list[TaskDetail]


class WebhookResponse(BaseModel):
    ok: bool
    task_id: str | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    db: str
    worker: str
    ts: int
