from django import forms

from apps.products.models import Product
from apps.suppliers.models import ProductSupplier, Supplier


class BootstrapFormMixin:
    def _apply_bootstrap_classes(self):
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                css_class = "form-check-input"
            elif isinstance(field.widget, forms.Select):
                css_class = "form-select"
            else:
                css_class = "form-control"
            field.widget.attrs["class"] = css_class


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ("name", "sku", "description", "minimum_stock", "is_active")
        labels = {
            "name": "Nome",
            "sku": "SKU",
            "description": "Descri\u00e7\u00e3o",
            "minimum_stock": "Estoque m\u00ednimo",
            "is_active": "Ativo",
        }
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class SupplierForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ("name", "cnpj", "email", "phone", "is_active")

        labels = {
            "name": "Nome",
            "cnpj": "CNPJ",
            "email": "E-mail",
            "phone": "Telefone",
            "is_active": "Ativo",
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()


class ProductSupplierForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductSupplier
        fields = (
            "product",
            "supplier",
            "price",
            "lead_time_days",
            "is_preferred",
        )
        labels = {
            "product": "Produto",
            "supplier": "Fornecedor",
            "price": "Pre\u00e7o",
            "lead_time_days": "Lead time (dias)",
            "is_preferred": "Preferencial",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._apply_bootstrap_classes()
        self.fields["product"].queryset = Product.objects.order_by("name")
        self.fields["supplier"].queryset = Supplier.objects.order_by("name")


class StockMovementForm(BootstrapFormMixin, forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        label="Produto",
    )
    movement_type = forms.ChoiceField(
        choices=(("IN", "Entrada"), ("OUT", "Sa\u00edda")),
        label="Tipo",
    )
    quantity = forms.IntegerField(min_value=1, label="Quantidade")
    note = forms.CharField(
        required=False,
        label="Observação",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.order_by("name")
        self._apply_bootstrap_classes()


class ReplenishmentRequestForm(BootstrapFormMixin, forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.none(),
        label="Produto",
    )
    product_supplier = forms.ModelChoiceField(
        queryset=ProductSupplier.objects.none(),
        label="Fornecedor do produto",
    )
    consumption_days = forms.IntegerField(
        min_value=1,
        initial=30,
        label="Período de consumo (dias)",
    )
    planning_days = forms.IntegerField(
        min_value=1,
        initial=30,
        label="Horizonte de planejamento (dias)",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.order_by("name")
        self.fields["product_supplier"].queryset = (
            ProductSupplier.objects.select_related("product", "supplier")
            .order_by("product__name", "supplier__name")
        )
        self._apply_bootstrap_classes()

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        relation = cleaned_data.get("product_supplier")
        if product and relation and relation.product_id != product.pk:
            self.add_error(
                "product_supplier",
                "O fornecedor selecionado não pertence ao produto.",
            )
        return cleaned_data
