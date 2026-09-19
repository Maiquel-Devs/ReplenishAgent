import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission

from apps.agent.authorization import tool_context_for_user
from apps.agent.tools import (
    ToolExecutionContext,
    ToolExecutionPolicy,
    ToolPermission,
)


pytestmark = pytest.mark.django_db


def test_anonymous_identity_cannot_authorize_write():
    context = tool_context_for_user(AnonymousUser())
    policy = ToolExecutionPolicy(allow_write=True)

    assert context.is_authenticated is False
    assert context.user_id is None
    assert policy.allows(ToolPermission.WRITE, context) is False


def test_authenticated_user_without_permission_cannot_authorize_write():
    user = get_user_model().objects.create_user(username="without-write")
    context = tool_context_for_user(user)

    assert context.is_authenticated is True
    assert context.user_id == user.pk
    assert context.permissions == frozenset()
    assert ToolExecutionPolicy(allow_write=True).allows(
        ToolPermission.WRITE,
        context,
    ) is False


def test_user_permission_and_backend_gate_are_both_required():
    user = get_user_model().objects.create_user(username="with-write")
    user.user_permissions.add(
        Permission.objects.get(codename="execute_agent_write")
    )
    context = tool_context_for_user(user)

    assert ToolExecutionPolicy(allow_write=False).allows(
        ToolPermission.WRITE,
        context,
    ) is False
    assert ToolExecutionPolicy(allow_write=True).allows(
        ToolPermission.WRITE,
        context,
    ) is True


def test_critical_is_never_authorized_for_privileged_identity():
    context = ToolExecutionContext(
        user_id=1,
        is_authenticated=True,
        permissions=frozenset({"agent.execute_agent_write"}),
    )

    assert ToolExecutionPolicy(allow_write=True).allows(
        ToolPermission.CRITICAL,
        context,
    ) is False
