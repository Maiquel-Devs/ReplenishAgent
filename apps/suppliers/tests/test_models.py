from decimal import Decimal

import pytest
from django.db import IntegrityError

from apps.products.models import Product
from apps.suppliers.models import ProductSupplier, Supplier


pytestmark = pytest.mark.django_db


@pytest.fixture
def product():
    return Product.objects.create(name="Café em grãos", sku="CAFE-001")


@pytest.fixture
def supplier():
    return Supplier.objects.create(
        name="Fornecedor Central",
        cnpj="12345678000199",
        email="contato@example.com",
        phone="(11) 99999-0000",
    )


def test_create_supplier_with_valid_data(supplier):
    assert supplier.name == "Fornecedor Central"
    assert supplier.cnpj == "12345678000199"
    assert supplier.is_active is True
    assert supplier.created_at is not None
    assert supplier.updated_at is not None


def test_cnpj_cannot_be_duplicated_when_provided(supplier):
    with pytest.raises(IntegrityError):
        Supplier.objects.create(
            name="Outro fornecedor",
            cnpj=supplier.cnpj,
        )


def test_create_product_supplier_with_valid_data(product, supplier):
    product_supplier = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("49.90"),
        lead_time_days=3,
    )

    assert product_supplier.price == Decimal("49.90")
    assert product_supplier.lead_time_days == 3
    assert product_supplier.is_preferred is False
    assert product_supplier.created_at is not None
    assert product_supplier.updated_at is not None


def test_product_supplier_combination_cannot_be_duplicated(product, supplier):
    ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("49.90"),
    )

    with pytest.raises(IntegrityError):
        ProductSupplier.objects.create(
            product=product,
            supplier=supplier,
            price=Decimal("45.00"),
        )


@pytest.mark.parametrize("invalid_price", [Decimal("0.00"), Decimal("-0.01")])
def test_price_must_be_greater_than_zero(product, supplier, invalid_price):
    with pytest.raises(IntegrityError):
        ProductSupplier.objects.create(
            product=product,
            supplier=supplier,
            price=invalid_price,
        )


def test_lead_time_cannot_be_negative(product, supplier):
    with pytest.raises(IntegrityError):
        ProductSupplier.objects.create(
            product=product,
            supplier=supplier,
            price=Decimal("49.90"),
            lead_time_days=-1,
        )

def test_multiple_suppliers_without_cnpj_are_allowed():
    first = Supplier.objects.create(name="Sem CNPJ 1")
    second = Supplier.objects.create(name="Sem CNPJ 2")

    assert first.cnpj is None
    assert second.cnpj is None


def test_product_supplier_can_be_marked_as_preferred(product, supplier):
    relation = ProductSupplier.objects.create(
        product=product,
        supplier=supplier,
        price=Decimal("49.90"),
        is_preferred=True,
    )

    assert relation.is_preferred is True
