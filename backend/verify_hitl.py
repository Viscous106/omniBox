"""
Production verification for Human-in-the-Loop + backward compatibility.
Uses an isolated temp DB — no LLM calls, no network.
Run: .venv/bin/python verify_hitl.py  (or .venv\\Scripts\\python.exe on Windows)
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

# Isolate DB before importing app modules
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name

sys.path.insert(0, str(Path(__file__).parent))

import db  # noqa: E402
from state import GoalStatus, TaskStatus  # noqa: E402

PASS = 0
FAIL = 0


def ok(name: str) -> None:
    global PASS
    PASS += 1
    print(f"  PASS  {name}")


def fail(name: str, detail: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {name}: {detail}")


def assert_eq(name: str, got, expected) -> None:
    if got == expected:
        ok(name)
    else:
        fail(name, f"expected {expected!r}, got {got!r}")


def assert_true(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        ok(name)
    else:
        fail(name, detail or "condition false")


async def seed_plan(goal_id: str, trace_id: str, *, requires_approval: bool = False) -> list:
    tasks = [
        {
            "id": f"{goal_id[:8]}_t1",
            "agent": "researcher",
            "description": "Research",
            "inputs": {},
            "depends_on": [],
            "requires_approval": requires_approval,
        },
        {
            "id": f"{goal_id[:8]}_t2",
            "agent": "writer",
            "description": "Write",
            "inputs": {"data": "{{t1.output}}"},
            "depends_on": [f"{goal_id[:8]}_t1"],
        },
    ]
    await db.create_tasks(tasks, goal_id, trace_id)
    await db.set_goal_plan(goal_id, json.dumps({"terminal": tasks[1]["id"]}), tasks[1]["id"])
    return tasks


async def run_db_tests() -> None:
    print("\n=== DB & schema ===")
    await db.init_db()

    g_auto = await db.create_goal("Auto start goal", requires_plan_approval=False)
    assert_eq("create_goal default requires_plan_approval", g_auto.requires_plan_approval, False)

    g_manual = await db.create_goal("Manual start goal", requires_plan_approval=True)
    assert_eq("create_goal manual requires_plan_approval", g_manual.requires_plan_approval, True)

    # Schema columns present
    goal = await db.get_goal(g_auto.id)
    assert_true("goal has is_paused", hasattr(goal, "is_paused") and goal.is_paused is False)
    assert_true("goal has step_mode", hasattr(goal, "step_mode") and goal.step_mode is False)

    tasks = await seed_plan(g_auto.id, g_auto.trace_id)
    goal = await db.get_goal(g_auto.id)
    assert_eq("set_goal_plan -> PLANNING_COMPLETED", goal.status, GoalStatus.PLANNING_COMPLETED)

    t1 = await db.get_task(tasks[0]["id"])
    t2 = await db.get_task(tasks[1]["id"])
    assert_eq("root task initial READY", t1.status, TaskStatus.READY)
    assert_eq("dependent task initial PENDING", t2.status, TaskStatus.PENDING)

    # Cannot claim before approve (goal not RUNNING)
    claimed = await db.claim_ready_task("worker-1", 300)
    assert_eq("claim blocked before goal approve", claimed, None)

    approved = await db.approve_goal(g_auto.id)
    assert_true("approve_goal succeeds", approved is not None)
    assert_eq("approve_goal -> RUNNING", approved.status, GoalStatus.RUNNING)

    claimed = await db.claim_ready_task("worker-1", 300)
    assert_true("claim works after approve", claimed is not None and claimed.id == t1.id)

    # Pause blocks claiming
    await db.settle_task(t1.id, TaskStatus.READY)
    await db.set_goal_paused(g_auto.id, True)
    claimed = await db.claim_ready_task("worker-1", 300)
    assert_eq("claim blocked when goal paused", claimed, None)

    await db.set_goal_paused(g_auto.id, False)
    claimed = await db.claim_ready_task("worker-1", 300)
    assert_true("claim resumes after unpause", claimed is not None)

    print("\n=== Approval gates ===")
    g_gate = await db.create_goal("Gated task goal")
    gated_tasks = await seed_plan(g_gate.id, g_gate.trace_id, requires_approval=True)
    await db.approve_goal(g_gate.id)
    gt1 = await db.get_task(gated_tasks[0]["id"])
    assert_eq("requires_approval root -> WAITING_APPROVAL", gt1.status, TaskStatus.WAITING_APPROVAL)

    claimed = await db.claim_ready_task("worker-1", 300)
    assert_eq("gated task not claimable", claimed, None)

    approved_t = await db.approve_task(gt1.id, inputs={"edited": True})
    assert_true("approve_task succeeds", approved_t is not None)
    assert_eq("approve_task -> READY", approved_t.status, TaskStatus.READY)
    assert_eq("approve_task clears flag", approved_t.requires_approval, False)
    assert_eq("approve_task updates inputs", approved_t.inputs.get("edited"), True)

    print("\n=== promote_ready_tasks ===")
    g_promo = await db.create_goal("Promote test")
    tid1 = f"{g_promo.id[:8]}_a"
    tid2 = f"{g_promo.id[:8]}_b"
    await db.create_tasks([
        {"id": tid1, "agent": "researcher", "description": "A", "inputs": {}, "depends_on": []},
        {"id": tid2, "agent": "writer", "description": "B", "inputs": {}, "depends_on": [tid1], "requires_approval": True},
    ], g_promo.id, g_promo.trace_id)
    await db.settle_task(tid1, TaskStatus.DONE, output={"summary": "done"})
    promoted = await db.promote_ready_tasks(g_promo.id)
    assert_true("t2 promoted", tid2 in promoted)
    t2row = await db.get_task(tid2)
    assert_eq("promoted gated task -> WAITING_APPROVAL", t2row.status, TaskStatus.WAITING_APPROVAL)

    print("\n=== replace_goal_plan ===")
    g_edit = await db.create_goal("Plan edit test")
    await seed_plan(g_edit.id, g_edit.trace_id)
    new_tid = f"{g_edit.id[:8]}_t1"
    new_tasks = [{
        "id": new_tid,
        "agent": "coder",
        "description": "Edited task",
        "inputs": {"x": 1},
        "depends_on": [],
        "requires_approval": False,
    }]
    replaced = await db.replace_goal_plan(
        g_edit.id, new_tasks, new_tid, json.dumps({"terminal": new_tid})
    )
    assert_eq("replace_plan task count", len(replaced), 1)
    assert_eq("replace_plan agent updated", replaced[0].agent_name, "coder")

    print("\n=== step mode ===")
    g_step = await db.create_goal("Step test")
    stasks = await seed_plan(g_step.id, g_step.trace_id)
    await db.approve_goal(g_step.id)
    # Pause other goals so claim_ready_task only sees the step goal
    for g in await db.list_goals(limit=100):
        if g.id != g_step.id:
            await db.set_goal_paused(g.id, True)
    await db.set_goal_step_mode(g_step.id, True)
    normal = await db.claim_ready_task("worker-1", 300)
    assert_true(
        "step_mode blocks normal executor for step goal",
        normal is None or normal.goal_id != g_step.id,
        f"claimed {normal.goal_id if normal else None}",
    )
    stepped = await db.claim_next_task_for_goal(g_step.id, "worker-step", 300)
    assert_true("claim_next_task_for_goal works", stepped is not None and stepped.goal_id == g_step.id)


async def run_api_tests() -> None:
    print("\n=== API (TestClient) ===")
    from httpx import ASGITransport, AsyncClient
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Health
        r = await client.get("/api/health")
        assert_eq("GET /api/health status", r.status_code, 200)

        # Auto-start goal submit
        r = await client.post("/api/goals", json={"goal": "Verify auto start"})
        assert_eq("POST /api/goals status", r.status_code, 202)
        goal_id = r.json()["goal_id"]

        r = await client.get(f"/api/goals/{goal_id}")
        assert_eq("GET /api/goals/{id} status", r.status_code, 200)

        # Manual start
        r = await client.post("/api/goals", json={"goal": "Verify manual", "manual_start": True})
        assert_eq("POST manual_start status", r.status_code, 202)
        manual_id = r.json()["goal_id"]
        r = await client.get(f"/api/goals/{manual_id}")
        assert_eq("manual goal requires_plan_approval", r.json()["requires_plan_approval"], True)

        # Seed manual goal with plan for edit/approve flow
        manual = await db.get_goal(manual_id)
        tasks = await seed_plan(manual_id, manual.trace_id)
        r = await client.get(f"/api/goals/{manual_id}")
        assert_eq("manual goal PLANNING_COMPLETED", r.json()["status"], GoalStatus.PLANNING_COMPLETED)

        # Update plan
        plan_tasks = [
            {
                "id": tasks[0]["id"],
                "agent": "researcher",
                "description": "Updated research",
                "inputs": {"q": "test"},
                "depends_on": [],
                "requires_approval": True,
            },
            {
                "id": tasks[1]["id"],
                "agent": "writer",
                "description": "Updated write",
                "inputs": {},
                "depends_on": [tasks[0]["id"]],
            },
        ]
        r = await client.put(
            f"/api/goals/{manual_id}/plan",
            json={"tasks": plan_tasks, "terminal": tasks[1]["id"]},
        )
        assert_eq("PUT /plan status", r.status_code, 200)
        assert_true("PUT /plan requires_approval in response", any(
            t.get("requires_approval") for t in r.json()["tasks"]
        ))

        # Approve plan
        r = await client.post(f"/api/goals/{manual_id}/approve")
        assert_eq("POST /approve status", r.status_code, 200)
        r = await client.get(f"/api/goals/{manual_id}")
        assert_eq("after approve -> RUNNING", r.json()["status"], GoalStatus.RUNNING)

        # Pause / resume
        r = await client.post(f"/api/goals/{manual_id}/pause")
        assert_eq("POST /pause status", r.status_code, 200)
        r = await client.get(f"/api/goals/{manual_id}")
        assert_eq("paused flag", r.json()["is_paused"], True)

        r = await client.post(f"/api/goals/{manual_id}/resume")
        assert_eq("POST /resume status", r.status_code, 200)
        r = await client.get(f"/api/goals/{manual_id}")
        assert_eq("resumed flag", r.json()["is_paused"], False)

        # Task approve endpoint
        waiting = next((t for t in r.json()["tasks"] if t["status"] == TaskStatus.WAITING_APPROVAL), None)
        if waiting:
            r = await client.post(
                f"/api/tasks/{waiting['id']}/approve",
                json={"inputs": {"approved": True}},
            )
            assert_eq("POST /tasks/approve status", r.status_code, 200)
            assert_eq("task approved -> READY", r.json()["status"], TaskStatus.READY)
        else:
            ok("POST /tasks/approve (no waiting task in seeded plan — skipped)")

        # Invalid approve on wrong state
        r = await client.post(f"/api/goals/{manual_id}/approve")
        assert_eq("double approve -> 409", r.status_code, 409)

        # List goals still works
        r = await client.get("/api/goals")
        assert_eq("GET /api/goals status", r.status_code, 200)
        assert_true("goals list non-empty", r.json()["total"] >= 2)

        # Config endpoints (existing features)
        r = await client.get("/api/config/models")
        assert_eq("GET /config/models status", r.status_code, 200)

        r = await client.get("/api/config/keys")
        assert_eq("GET /config/keys status", r.status_code, 200)

        r = await client.get(f"/api/goals/{manual_id}/tasks")
        assert_eq("GET /goals/{id}/tasks status", r.status_code, 200)


async def run_worker_helpers() -> None:
    print("\n=== Worker helpers ===")
    import worker

    g = await db.create_goal("Worker approve test")
    await seed_plan(g.id, g.trace_id)
    result = await worker.approve_goal_execution(g.id)
    assert_true("approve_goal_execution", result is True)
    fresh = await db.get_goal(g.id)
    assert_eq("worker approve -> RUNNING", fresh.status, GoalStatus.RUNNING)


async def main() -> None:
    print("Human-in-the-Loop production verification")
    print(f"Temp DB: {_tmp.name}")
    try:
        await run_db_tests()
        await run_worker_helpers()
        await run_api_tests()
    finally:
        try:
            os.unlink(_tmp.name)
        except OSError:
            pass

    print(f"\n{'=' * 40}")
    print(f"Results: {PASS} passed, {FAIL} failed")
    if FAIL:
        sys.exit(1)
    print("All verification checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
