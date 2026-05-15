import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


tracing = importlib.import_module("tracing")


class FakeSpan:
    def __init__(self, tracer, name, kwargs):
        self.tracer = tracer
        self.name = name
        self.kwargs = kwargs
        self.attributes = {}
        self.events = []
        self.output = None

    def __enter__(self):
        self.tracer.entered_spans.append(self)
        return self

    def __exit__(self, exc_type, exc, tb):
        self.tracer.exited_spans.append(self)
        return False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def add_event(self, name):
        self.events.append(name)

    def set_output(self, output):
        self.output = output


class FakeTracer:
    instances = []

    def __init__(self, execution_id, trace_id):
        self.execution_id = execution_id
        self.trace_id = trace_id
        self.entered_spans = []
        self.exited_spans = []
        self.flushed = False
        self.aflushed = False
        FakeTracer.instances.append(self)

    def span(self, name, **kwargs):
        return FakeSpan(self, name, kwargs)

    def flush(self):
        self.flushed = True

    async def aflush(self):
        self.aflushed = True


class FakeContextVar:
    def __init__(self):
        self.value = None

    def set(self, value):
        previous = self.value
        self.value = value
        return previous

    def get(self):
        return self.value

    def reset(self, token):
        self.value = token


class OmiumTracingTests(unittest.TestCase):
    def setUp(self):
        FakeTracer.instances = []

    def test_init_tracing_initializes_omium_with_runtime_settings(self):
        fake_omium = SimpleNamespace(init=Mock())

        with patch.object(tracing, "_omium_available", True), \
             patch.object(tracing, "_omium_module", fake_omium, create=True), \
             patch.object(tracing.settings, "omium_skip_workflow_register", True), \
             patch.dict(os.environ, {}, clear=True):
            tracing.init_tracing("test-key", "test-project")
            self.assertEqual(os.environ["OMIUM_SKIP_WORKFLOW_REGISTER"], "true")

        fake_omium.init.assert_called_once_with(
            api_key="test-key",
            project="test-project",
            auto_trace=False,
            auto_checkpoint=False,
        )

    def test_goal_trace_context_creates_root_span_for_goal(self):
        ctx = FakeContextVar()

        with patch.object(tracing, "_omium_available", True), \
             patch.object(tracing, "_OmiumTracer", FakeTracer), \
             patch.object(tracing, "_omium_ctx_var", ctx):
            with tracing.goal_trace_context("goal-trace-id", "Ship the demo") as tracer:
                self.assertIs(ctx.get(), tracer)

        tracer = FakeTracer.instances[0]
        root_span = tracer.entered_spans[0]
        self.assertEqual(tracer.execution_id, "goal-trace-id")
        self.assertEqual(tracer.trace_id, "goal-trace-id")
        self.assertEqual(root_span.name, "goal_run")
        self.assertEqual(root_span.kwargs["input"], {"goal": "Ship the demo"})
        self.assertIn("goal_finished", root_span.events)
        self.assertIsNone(ctx.get())
        self.assertTrue(tracer.flushed)

    def test_task_span_records_agent_task_metadata(self):
        tracer = FakeTracer("execution-id", "trace-id")

        with tracing.task_span(tracer, "task-1", "researcher", "Find sources") as span:
            span.set_output({"status": "DONE"})

        task_span = tracer.entered_spans[0]
        self.assertEqual(task_span.name, "task/researcher")
        self.assertEqual(task_span.kwargs["span_type"], "agent")
        self.assertEqual(task_span.kwargs["task_id"], "task-1")
        self.assertEqual(task_span.kwargs["agent"], "researcher")
        self.assertEqual(task_span.output, {"status": "DONE"})

    def test_tool_span_records_sanitized_tool_input_and_cache_flag(self):
        tracer = FakeTracer("execution-id", "trace-id")
        args = {
            "query": "x" * 350,
            "_goal_id": "internal",
            "limit": 5,
        }

        with tracing.tool_span(tracer, "task-1", "web_search", args, cached=True) as span:
            span.set_output({"ok": True})

        tool_span = tracer.entered_spans[0]
        tool_input = tool_span.kwargs["input"]
        self.assertEqual(tool_span.name, "tool/web_search")
        self.assertEqual(tool_span.kwargs["span_type"], "tool")
        self.assertTrue(tool_span.kwargs["cached"])
        self.assertNotIn("_goal_id", tool_input)
        self.assertEqual(tool_input["task_id"], "task-1")
        self.assertEqual(tool_input["limit"], 5)
        self.assertLess(len(tool_input["query"]), len(args["query"]))
        self.assertEqual(tool_span.output, {"ok": True})

    def test_webhook_span_records_resume_payload_without_full_token(self):
        tracer = FakeTracer("execution-id", "trace-id")
        token = "abcdefghijklmnopqrstuvwxyz"
        payload = {"approved": True}

        with tracing.webhook_span(tracer, "task-1", token, payload) as span:
            span.set_output({"resumed": True})

        webhook_span = tracer.entered_spans[0]
        webhook_input = webhook_span.kwargs["input"]
        self.assertEqual(webhook_span.name, "webhook_resume")
        self.assertEqual(webhook_span.kwargs["event"], "webhook_fire")
        self.assertEqual(webhook_input["task_id"], "task-1")
        self.assertEqual(webhook_input["payload"], payload)
        self.assertNotEqual(webhook_input["wait_token"], token)
        self.assertTrue(webhook_input["wait_token"].endswith("…"))
        self.assertEqual(webhook_span.output, {"resumed": True})

    def test_trace_decorator_delegates_to_omium_trace_wrapper(self):
        def fake_trace(name, **kwargs):
            def decorator(fn):
                def wrapped(*args, **inner_kwargs):
                    return {"name": name, "result": fn(*args, **inner_kwargs), **kwargs}

                return wrapped

            return decorator

        fake_omium = SimpleNamespace(trace=Mock(side_effect=fake_trace))

        with patch.object(tracing, "_omium_available", True), \
             patch.object(tracing, "_omium_module", fake_omium, create=True):
            @tracing.trace("agent_run")
            def add_one(value):
                return value + 1

            result = add_one(41)

        self.assertEqual(result["name"], "agent_run")
        self.assertEqual(result["result"], 42)
        self.assertEqual(result["span_type"], "agent")
        self.assertTrue(result["capture_input"])
        self.assertTrue(result["capture_output"])


if __name__ == "__main__":
    unittest.main()
