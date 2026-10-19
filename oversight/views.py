from django.shortcuts import render

from core.permissions import admin_required
from .services import OversightService


@admin_required
def exception_center(request):
    categories = OversightService.exceptions()
    total = sum(c.count for c in categories)
    return render(request, "oversight/exception-center.html", {
        "categories": categories,
        "total": total,
    })


@admin_required
def data_quality_center(request):
    categories = OversightService.data_quality()
    total = sum(c.count for c in categories)
    return render(request, "oversight/data-quality.html", {
        "categories": categories,
        "total": total,
    })
