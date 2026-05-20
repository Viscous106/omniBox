import json

from fastapi import APIRouter, HTTPException

import db
import events
import worker
from models import GoalListResponse, GoalResponse, GoalSummary, SubmitGoalRequest, UpdatePlanRequest
from state import GoalStatus, TaskStatus

router = APIRouter(prefix="/api/goals", tags=["goals"])


def _task_to_dict(t) -> dict:
    return {
        "id": t.id,
        "goal_id": t.goal_id,
        "agent_name": t.agent_name,
        "description": t.description,
        "status": t.status,
        "inputs": t.inputs,
        "output": t.output,
        "error": t.error,
        "attempt_count": t.attempt_count,
        "wait_token": t.wait_token,
        "depends_on": t.depends_on,
        "requires_approval": t.requires_approval,
        "model_override": t.model_override,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _goal_response(goal, tasks) -> GoalResponse:
    return GoalResponse(
        goal_id=goal.id,
        title=goal.title,
        goal_text=goal.goal_text,
        status=goal.status,
        output=goal.output,
        error=goal.error,
        plan=json.loads(goal.plan_json) if goal.plan_json else None,
        tasks=[_task_to_dict(t) for t in tasks],
        trace_id=goal.trace_id,
        is_paused=goal.is_paused,
        requires_plan_approval=goal.requires_plan_approval,
        step_mode=goal.step_mode,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


@router.post("", status_code=202)
async def submit_goal(body: SubmitGoalRequest) -> dict:
    if not body.goal or not body.goal.strip():
        raise HTTPException(status_code=400, detail="goal must not be empty")
    manual_start = body.manual_start
    if body.metadata and body.metadata.get("manual_start"):
        manual_start = True
    goal = await db.create_goal(body.goal.strip(), requires_plan_approval=manual_start)
    return {"goal_id": goal.id, "status": goal.status, "created_at": goal.created_at}


@router.get("")
async def list_goals(status: str | None = None, limit: int = 20, offset: int = 0) -> GoalListResponse:
    goals = await db.list_goals(status=status, limit=limit, offset=offset)
    return GoalListResponse(
        goals=[GoalSummary(goal_id=g.id, title=g.title, status=g.status, created_at=g.created_at, updated_at=g.updated_at) for g in goals],
        total=len(goals),
    )


@router.get("/{goal_id}")
async def get_goal(goal_id: str) -> GoalResponse:
    goal = await db.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    tasks = await db.list_goal_tasks(goal_id)
    return _goal_response(goal, tasks)


@router.put("/{goal_id}/plan")
async def update_plan(goal_id: str, body: UpdatePlanRequest) -> GoalResponse:
    goal = await db.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    if goal.status not in (GoalStatus.PLANNING_COMPLETED, GoalStatus.RUNNING):
        raise HTTPException(status_code=409, detail=f"Cannot edit plan while goal is {goal.status}")

    task_ids = {t.id for t in body.tasks}
    if body.terminal not in task_ids:
        raise HTTPException(status_code=400, detail="terminal task must be in tasks list")

    for t in body.tasks:
        for dep in t.depends_on:
            if dep not in task_ids:
                raise HTTPException(status_code=400, detail=f"task {t.id} depends on unknown task {dep}")
            if dep == t.id:
                raise HTTPException(status_code=400, detail=f"task {t.id} cannot depend on itself")

    tasks_data = [t.model_dump() for t in body.tasks]
    plan_json = json.dumps({"tasks": tasks_data, "terminal": body.terminal})

    try:
        await db.replace_goal_plan(goal_id, tasks_data, body.terminal, plan_json)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    events.emit(goal_id, "plan_updated", {"goal_id": goal_id, "task_count": len(body.tasks)})
    goal = await db.get_goal(goal_id)
    tasks = await db.list_goal_tasks(goal_id)
    return _goal_response(goal, tasks)


@router.post("/{goal_id}/approve")
async def approve_goal(goal_id: str) -> dict:
    goal = await db.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    if goal.status != GoalStatus.PLANNING_COMPLETED:
        raise HTTPException(status_code=409, detail=f"Goal is {goal.status}, not awaiting plan approval")

    ok = await worker.approve_goal_execution(goal_id)
    if not ok:
        raise HTTPException(status_code=409, detail="Could not approve goal")
    return {"ok": True, "status": GoalStatus.RUNNING}


@router.post("/{goal_id}/pause")
async def pause_goal(goal_id: str) -> dict:
    goal = await db.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    updated = await db.set_goal_paused(goal_id, True)
    events.emit(goal_id, "goal_status", {"status": updated.status, "goal_id": goal_id, "is_paused": True})
    return {"ok": True, "is_paused": True}


@router.post("/{goal_id}/resume")
async def resume_goal(goal_id: str) -> dict:
    goal = await db.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    await db.set_goal_step_mode(goal_id, False)
    updated = await db.set_goal_paused(goal_id, False)
    events.emit(goal_id, "goal_status", {"status": updated.status, "goal_id": goal_id, "is_paused": False})
    return {"ok": True, "is_paused": False}


@router.post("/{goal_id}/step")
async def step_goal(goal_id: str) -> dict:
    goal = await db.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    if goal.is_paused and not goal.step_mode:
        await db.set_goal_step_mode(goal_id, True)
    task = await worker.step_goal_execution(goal_id)
    if not task:
        raise HTTPException(status_code=404, detail="No ready task to execute")
    return {"ok": True, "task_id": task.id, "status": TaskStatus.RUNNING}
