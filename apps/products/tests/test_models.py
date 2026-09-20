import pytest
from django.db import IntegrityError

from apps.products.models import Product


pytestmark = pytest.mark.django_db


def test_create_product_with_valid_data():
    product = Product.objects.create(
        name="Café em grãos",
        sku="CAFE-001",
        description="Pacote de 1 kg",
        minimum_stock=5,
    )

    assert product.name == "Café em grãos"
    assert product.sku == "CAFE-001"
    assert product.minimum_stock == 5
    assert product.is_active is True
    assert product.created_at is not None
    assert product.updated_at is not None


def test_sku_cannot_be_duplicated():
    Product.objects.create(name="Produto A", sku="SKU-001")

    with pytest.raises(IntegrityError):
        Product.objects.create(name="Produto B", sku="SKU-001")


def test_minimum_stock_cannot_be_negative():
    with pytest.raises(IntegrityError):
        Product.objects.create(
            name="Produto inválido",
            sku="INVALID-001",
            minimum_stock=-1,
        )

def test_product_can_be_created_inactive():
    product = Product.objects.create(
        name="Produto inativo",
        sku="INACTIVE-001",
        is_active=False,
    )

    assert product.is_active is False
