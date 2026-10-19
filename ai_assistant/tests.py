import unittest
from django.contrib.auth.models import User
from django.test import TestCase

from ai_assistant.local_assistant import answer
from ai_assistant.agent import _build_tools_for_user
from workflow.models import WorkflowRequest


class LocalAssistantExceptionsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("la_admin", password="pw", is_staff=True, is_superuser=True)
        self.student = User.objects.create_user("la_student", password="pw")

    def test_admin_gets_exceptions_summary(self):
        reply = answer(self.admin, "what needs attention today?")
        self.assertIn("Open exceptions", reply)
        self.assertIn("Pending workflow requests", reply)

    def test_non_admin_is_refused_exceptions_summary(self):
        reply = answer(self.student, "any exceptions to review?")
        self.assertIn("restricted to administrators", reply)

    def test_pending_workflow_count_reflected(self):
        WorkflowRequest.objects.create(
            request_type="other", requested_by=self.student, reason="test", status="pending",
        )
        reply = answer(self.admin, "show pending approval requests")
        self.assertIn("Pending workflow requests: 1", reply)


from ai_assistant.agent import LANGGRAPH_AVAILABLE


@unittest.skipUnless(LANGGRAPH_AVAILABLE, 'optional LangGraph packages (requirements-ai.txt) not installed')
class AgentToolRegistrationTests(TestCase):
    """The LangGraph tool-based agent may be unavailable in this sandbox
    (no LLM provider configured), but _build_tools_for_user() itself is
    pure Python/ORM and should always work, so we test it directly rather
    than going through the LLM."""

    def setUp(self):
        self.admin = User.objects.create_user("agent_admin", password="pw", is_staff=True, is_superuser=True)
        self.student = User.objects.create_user("agent_student", password="pw")

    def test_admin_tool_list_includes_new_oversight_tools(self):
        tools = _build_tools_for_user(self.admin)
        names = {t.name for t in tools}
        self.assertIn("get_exceptions_summary", names)
        self.assertIn("get_pending_workflow_requests", names)

    def test_admin_only_tool_refuses_non_admin(self):
        tools = _build_tools_for_user(self.student)
        by_name = {t.name: t for t in tools}
        result = by_name["get_exceptions_summary"].invoke({})
        self.assertIn("Only admin accounts", result)
