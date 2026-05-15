import asyncio
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import agent_runner
import main
import worker
from api import webhooks


class FakeSpan:
    def __init__(self):
        self.output = None

    def set_output(self, output):
        self.output = output

    def set_attribute(self, key, value):
        setattr(self, key, value)

    def add_event(self, name):
        self.event = name


def run_async(coro):
    return asyncio.run(coro)


class OmiumIntegrationPointTests(unittest.TestCase):
    def test_startup_initializes_omium_tracing(self):
        with patch.object(main.db, "init_db", new=AsyncMock()), \
             patch.object(main.Path, "mkdir"), \
             patch.object(main.worker, "start", new=AsyncMock()), \
             patch.object(main.worker, "stop", new=AsyncMock()), \
             patch.object(main, "init_tracing") as init_tracing:
            async def exercise_lifespan():
                async with main.lifespan(SimpleNamespace()):
                    pass

            run_async(exercise_lifespan())

        init_tracing.assert_called_once_with(
            main.settings.omium_api_key,
            main.settings.omium_project,
        )

    def test_goal_planning_runs_inside_goal_trace_context(self):
        goal = SimpleNamespace(id="goal-1", trace_id="trace-1", title="Build demo")
        calls = []

        @contextmanager
        def fake_goal_trace_context(**kwargs):
            calls.append(kwargs)
            yield "goal-tracer"

        with patch.object(worker, "goal_trace_context", side_effect=fake_goal_trace_context), \
             patch.object(worker.orch, "run_plan", new=AsyncMock()) as run_plan, \
             patch.object(worker.events, "emit"):
            run_async(worker._plan_goal(goal))

        run_plan.assert_awaited_once_with(goal)
        self.assertEqual(calls, [{"execution_id": goal.trace_id, "goal_title": goal.title}])

    def test_task_execution_runs_inside_task_span(self):
        task = SimpleNamespace(
            id="task-1",
            goal_id="goal-1",
            agent_name="researcher",
            description="Research the topic",
            inputs={},
            attempt_count=0,
        )
        span = FakeSpan()
        calls = []

        @contextmanager
        def fake_task_span(*args):
            calls.append(args)
            yield span

        with patch.object(worker.db, "list_goal_tasks", new=AsyncMock(return_value=[])), \
             patch.object(worker, "get_active_tracer", return_value="active-tracer"), \
             patch.object(worker, "task_span", side_effect=fake_task_span), \
             patch.object(worker, "agent_run", new=AsyncMock(return_value={"done": True})), \
             patch.object(worker.db, "settle_task", new=AsyncMock()), \
             patch.object(worker, "_after_task_done", new=AsyncMock()), \
             patch.object(worker.events, "emit"):
            run_async(worker._execute_task(task))

        self.assertEqual(calls, [("active-tracer", task.id, task.agent_name, task.description)])
        self.assertEqual(span.output, {"task_id": task.id, "status": "DONE"})

    def test_agent_runner_wraps_tool_execution_in_tool_span(self):
        task = SimpleNamespace(
            id="task-1",
            goal_id="goal-1",
            agent_name="researcher",
            description="Search for Omium details",
            attempt_count=0,
            trace_id="trace-1",
        )
        tool_calls = []
        span = FakeSpan()

        @contextmanager
        def fake_tool_span(*args, **kwargs):
            tool_calls.append((args, kwargs))
            yield span

        async def fake_tool(args):
            return {"answer": args["query"]}

        first_tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="fake_search", arguments=json.dumps({"query": "omium"})),
        )
        submit_call = SimpleNamespace(
            id="call-2",
            function=SimpleNamespace(name="submit_result", arguments=json.dumps({"result": {"ok": True}})),
        )
        first_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[first_tool_call]))]
        )
        submit_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[submit_call]))]
        )
        fake_registry = {
            "fake_search": SimpleNamespace(
                fn=fake_tool,
                schema={
                    "description": "Fake search",
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        }

        with patch.object(agent_runner, "get_agent_config", return_value={
            "allowed_tools": ["fake_search"],
            "model": "fake-model",
            "max_iterations": 2,
            "system_prompt": "Use tools.",
        }), \
             patch.object(agent_runner, "TOOL_REGISTRY", fake_registry), \
             patch.object(agent_runner, "acompletion", new=AsyncMock(side_effect=[first_response, submit_response])), \
             patch.object(agent_runner.db, "save_message", new=AsyncMock()), \
             patch.object(agent_runner.db, "get_tool_call_by_idempotency", new=AsyncMock(return_value=None)), \
             patch.object(agent_runner.db, "create_tool_call", new=AsyncMock()), \
             patch.object(agent_runner.db, "settle_tool_call", new=AsyncMock()), \
             patch.object(agent_runner, "tool_span", side_effect=fake_tool_span):
            result = run_async(agent_runner.run(task, {}, tracer="active-tracer"))

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(tool_calls), 1)
        args, kwargs = tool_calls[0]
        self.assertEqual(args[:4], ("active-tracer", task.id, "fake_search", {"query": "omium"}))
        self.assertEqual(kwargs, {"cached": False})
        self.assertEqual(span.output, {"answer": "omium"})

    def test_webhook_resume_runs_inside_webhook_span(self):
        task = SimpleNamespace(id="task-1", goal_id="goal-1")
        request = SimpleNamespace(json=AsyncMock(return_value={"approved": True}))
        calls = []
        span = FakeSpan()

        @contextmanager
        def fake_webhook_span(*args):
            calls.append(args)
            yield span

        with patch.object(webhooks.db, "resume_webhook_task", new=AsyncMock(return_value=task)), \
             patch.object(webhooks, "get_active_tracer", return_value="active-tracer"), \
             patch.object(webhooks, "webhook_span", side_effect=fake_webhook_span), \
             patch.object(webhooks.events, "emit"):
            response = run_async(webhooks.receive_webhook("wait-token", request))

        self.assertTrue(response.ok)
        self.assertEqual(response.task_id, task.id)
        self.assertEqual(calls, [("active-tracer", task.id, "wait-token", {"approved": True})])
        self.assertEqual(span.output, {"task_id": task.id, "resumed": True})


if __name__ == "__main__":
    unittest.main()
