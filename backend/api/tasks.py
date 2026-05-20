from fastapi import APIRouter, HTTPException

import db
import events
from models import ApproveTaskRequest, TaskDetail, TaskListResponse
from state import TaskStatus

router = APIRouter(prefix="/api", tags=["tasks"])


def _to_detail(t) -> TaskDetail:
    return TaskDetail(
        id=t.id,
        goal_id=t.goal_id,
        agent_name=t.agent_name,
        description=t.description,
        status=t.status,
        inputs=t.inputs,
        output=t.output,
        error=t.error,
        attempt_count=t.attempt_count,
        wait_token=t.wait_token,
        depends_on=t.depends_on,
        requires_approval=t.requires_approval,
        model_override=t.model_override,
        created_at=t.created_at,
        updated_at=t.updated_at,
    )


@router.get("/goals/{goal_id}/tasks")
async def list_goal_tasks(goal_id: str) -> TaskListResponse:
    goal = await db.get_goal(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    tasks = await db.list_goal_tasks(goal_id)
    return TaskListResponse(tasks=[_to_detail(t) for t in tasks])


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> TaskDetail:
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return _to_detail(task)


@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: str, body: ApproveTaskRequest | None = None) -> TaskDetail:
    task = await db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.WAITING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"Task is {task.status}, not waiting for approval")

    inputs = body.inputs if body else None
    approved = await db.approve_task(task_id, inputs=inputs)
    if not approved:
        raise HTTPException(status_code=409, detail="Could not approve task")

    events.emit(task.goal_id, "task_update", {
        "task_id": task_id, "status": TaskStatus.READY,
    })
    return _to_detail(approved)
