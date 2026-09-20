from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.agent.audit import AgentExecutionStatus
from apps.agent.models import AgentExecution
from apps.products.models import Product
from apps.purchasing.models import PurchaseProposal
from apps.purchasing.services import create_purchase_proposal
from apps.replenishment.calculations import ReplenishmentAnalysis, RiskLevel
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


@pytest.fixture
def plain_user():
    return get_user_model().objects.create_user(
        username="plain-user",
        password="password",
    )


@pytest.fixture
def reviewer():
    user = get_user_model().objects.create_user(
        username="admin-reviewer",
        password="password",
    )
    user.user_permissions.add(
        Permission.objects.get(codename="review_purchaseproposal")
    )
    return user


@pytest.fixture
def auditor():
    user = get_user_model().objects.create_user(
        username="agent-auditor",
        password="password",
    )
    user.user_permissions.add(
        Permission.objects.get(
            codename="view_agentexecution",
            content_type__app_label="agent",
        )
    )
    return user


@pytest.fixture
def ai_administrator():
    user = get_user_model().objects.create_user(
        username="ai-administrator",
        password="password",
    )
    user.user_permissions.add(
        Permission.objects.get(
            codename="configure_ai",
            content_type__app_label="agent",
        )
    )
    return user


@pytest.fixture
def proposal():
    product = Product.objects.create(name="Admin product", sku="ADMIN-001")
    supplier = Supplier.objects.create(name="Admin supplier")
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("25.00"),
    )
    analysis = ReplenishmentAnalysis(
        product=product,
        current_stock=Decimal("0"),
        average_daily_consumption=Decimal("1"),
        stock_coverage_days=Decimal("0"),
        lead_time_days=0,
        minimum_stock=Decimal("0"),
        reorder_point=Decimal("0"),
        planning_days=4,
        target_stock=Decimal("4"),
        recommended_quantity=Decimal("4"),
        risk_level=RiskLevel.CRITICAL,
    )
    return create_purchase_proposal(
        product=product,
        product_supplier=relation,
        analysis=analysis,
    )


@pytest.fixture
def execution(auditor):
    return AgentExecution.objects.create(
        user=auditor,
        provider="FakeLLMProvider",
        model="fake-model",
        status=AgentExecutionStatus.COMPLETED.value,
        user_request="<script>request</script>",
        final_response="<script>response</script>",
    )


@pytest.mark.parametrize(
    "url_name",
    [
        "web:administration_overview",
        "web:pending_proposals",
        "web:agent_audit_list",
        "web:ai_configuration",
    ],
)
def test_administration_requires_login(client, url_name):
    response = client.get(reverse(url_name))

    assert response.status_code == 302
    assert reverse("login") in response.url


def test_authenticated_user_without_permission_gets_forbidden(client, plain_user):
    client.force_login(plain_user)

    assert client.get(reverse("web:administration_overview")).status_code == 403
    assert client.get(reverse("web:pending_proposals")).status_code == 403
    assert client.get(reverse("web:agent_audit_list")).status_code == 403
    assert client.get(reverse("web:ai_configuration")).status_code == 403


def test_administration_navigation_is_hidden_without_permission(
    client,
    plain_user,
):
    client.force_login(plain_user)

    response = client.get(reverse("web:dashboard"))

    assert "Administração" not in response.content.decode()


def test_authorized_user_sees_administration_navigation(client, reviewer):
    client.force_login(reviewer)

    response = client.get(reverse("web:dashboard"))

    assert response.status_code == 200
    assert "Administração" in response.content.decode()


def test_reviewer_cannot_access_ai_configuration_directly(client, reviewer):
    client.force_login(reviewer)

    response = client.get(reverse("web:ai_configuration"))

    assert response.status_code == 403


def test_ai_administrator_can_access_custom_administration(
    client,
    ai_administrator,
):
    client.force_login(ai_administrator)

    overview = client.get(reverse("web:administration_overview"))
    configuration = client.get(reverse("web:ai_configuration"))

    assert overview.status_code == 200
    assert "Configuração da IA" in overview.content.decode()
    assert configuration.status_code == 200


def test_ai_configuration_shows_provider_and_model_without_credentials(
    client,
    ai_administrator,
    monkeypatch,
):
    monkeypatch.setenv("LLM_PROVIDER", "mistral")
    monkeypatch.setenv("MISTRAL_MODEL", "configured-model")
    monkeypatch.setenv("MISTRAL_API_KEY", "must-not-be-rendered")
    client.force_login(ai_administrator)

    response = client.get(reverse("web:ai_configuration"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Ollama" in content
    assert "Mistral" in content
    assert "configured-model" in content
    assert "must-not-be-rendered" not in content
    assert 'name="api_key"' not in content
    assert "Salvar configuração" not in content


def test_reviewer_sees_pending_proposals(client, reviewer, proposal):
    client.force_login(reviewer)

    response = client.get(reverse("web:pending_proposals"))

    content = response.content.decode()
    assert response.status_code == 200
    assert proposal.product.name in content
    assert proposal.supplier.name in content
    assert "R$ 100,00" in content


def test_direct_decision_url_requires_review_permission(
    client,
    plain_user,
    proposal,
):
    client.force_login(plain_user)

    approve = client.post(reverse("web:proposal_approve", args=[proposal.pk]))
    reject = client.post(reverse("web:proposal_reject", args=[proposal.pk]))

    proposal.refresh_from_db()
    assert approve.status_code == 403
    assert reject.status_code == 403
    assert proposal.status == PurchaseProposal.Status.PENDING


def test_get_confirmation_does_not_decide_proposal(client, reviewer, proposal):
    client.force_login(reviewer)

    response = client.get(reverse("web:proposal_approve", args=[proposal.pk]))

    proposal.refresh_from_db()
    assert response.status_code == 200
    assert "Confirmar decisão" in response.content.decode()
    assert proposal.status == PurchaseProposal.Status.PENDING


def test_approve_and_reject_are_post_actions(client, reviewer, proposal):
    client.force_login(reviewer)

    response = client.post(reverse("web:proposal_approve", args=[proposal.pk]))

    proposal.refresh_from_db()
    assert response.status_code == 302
    assert proposal.status == PurchaseProposal.Status.APPROVED
    assert proposal.reviewed_by == reviewer


def test_reject_post_records_human_reviewer(client, reviewer, proposal):
    client.force_login(reviewer)

    response = client.post(reverse("web:proposal_reject", args=[proposal.pk]))

    proposal.refresh_from_db()
    assert response.status_code == 302
    assert proposal.status == PurchaseProposal.Status.REJECTED
    assert proposal.reviewed_by == reviewer


def test_decision_post_enforces_csrf(reviewer, proposal):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(reviewer)
    url = reverse("web:proposal_approve", args=[proposal.pk])

    assert csrf_client.post(url).status_code == 403

    confirmation = csrf_client.get(url)
    token = confirmation.cookies["csrftoken"].value
    response = csrf_client.post(
        url,
        HTTP_X_CSRFTOKEN=token,
    )

    proposal.refresh_from_db()
    assert response.status_code == 302
    assert proposal.status == PurchaseProposal.Status.APPROVED


def test_audit_pages_require_specific_permission(client, reviewer, execution):
    client.force_login(reviewer)

    assert client.get(reverse("web:agent_audit_list")).status_code == 403
    assert client.get(
        reverse("web:agent_audit_detail", args=[execution.pk])
    ).status_code == 403


def test_auditor_can_list_and_view_execution_without_unescaped_llm_content(
    client,
    auditor,
    execution,
):
    client.force_login(auditor)

    listing = client.get(reverse("web:agent_audit_list"))
    detail = client.get(
        reverse("web:agent_audit_detail", args=[execution.pk])
    )

    assert listing.status_code == 200
    assert "FakeLLMProvider" in listing.content.decode()
    assert detail.status_code == 200
    content = detail.content.decode()
    assert "&lt;script&gt;request&lt;/script&gt;" in content
    assert "&lt;script&gt;response&lt;/script&gt;" in content
    assert "<script>request</script>" not in content


def test_unknown_audit_execution_returns_404_for_authorized_user(
    client,
    auditor,
):
    client.force_login(auditor)

    response = client.get(
        reverse(
            "web:agent_audit_detail",
            args=["00000000-0000-0000-0000-000000000000"],
        )
    )

    assert response.status_code == 404
