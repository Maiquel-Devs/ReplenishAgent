from django.urls import path

from . import admin_views, views


app_name = "web"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("produtos/", views.product_list, name="product_list"),
    path("produtos/novo/", views.product_create, name="product_create"),
    path("produtos/<int:pk>/", views.product_detail, name="product_detail"),
    path("produtos/<int:pk>/editar/", views.product_update, name="product_update"),
    path("fornecedores/", views.supplier_list, name="supplier_list"),
    path("fornecedores/novo/", views.supplier_create, name="supplier_create"),
    path("fornecedores/<int:pk>/", views.supplier_detail, name="supplier_detail"),
    path(
        "fornecedores/<int:pk>/editar/",
        views.supplier_update,
        name="supplier_update",
    ),
    path(
        "fornecedores/relacoes/",
        views.product_supplier_list,
        name="product_supplier_list",
    ),
    path(
        "fornecedores/relacoes/nova/",
        views.product_supplier_create,
        name="product_supplier_create",
    ),
    path("estoque/", views.inventory_list, name="inventory_list"),
    path("movimentacoes/", views.movement_list, name="movement_list"),
    path("movimentacoes/nova/", views.movement_create, name="movement_create"),
    path("reposicao/", views.replenishment_analysis, name="replenishment_analysis"),
    path(
        "reposicao/proposta/",
        views.proposal_create_from_analysis,
        name="proposal_create_from_analysis",
    ),
    path("propostas/", views.proposal_list, name="proposal_list"),
    path("propostas/<int:pk>/", views.proposal_detail, name="proposal_detail"),
    path(
        "administracao/",
        admin_views.administration_overview,
        name="administration_overview",
    ),
    path(
        "administracao/propostas/",
        admin_views.pending_proposals,
        name="pending_proposals",
    ),
    path(
        "administracao/propostas/<int:pk>/aprovar/",
        admin_views.proposal_approve,
        name="proposal_approve",
    ),
    path(
        "administracao/propostas/<int:pk>/rejeitar/",
        admin_views.proposal_reject,
        name="proposal_reject",
    ),
    path(
        "administracao/auditoria/",
        admin_views.agent_audit_list,
        name="agent_audit_list",
    ),
    path(
        "administracao/auditoria/<uuid:execution_id>/",
        admin_views.agent_audit_detail,
        name="agent_audit_detail",
    ),
]
