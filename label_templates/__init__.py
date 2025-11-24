"""Template loader for Homebox label generators."""

from __future__ import annotations

from typing import Iterable
from importlib import import_module

from .base import LabelTemplate

_TEMPLATE_NAMES = {"avery5163", "ptouch"}


def _load_template_module(name: str):
    """Load template module, handling package/module name conflicts."""
    key = name.lower()
    return import_module(f"{__name__}.{key}")


def get_template(
    name: str,
) -> LabelTemplate:
    """Instantiate the template implementation for ``name``."""

    key = name.lower()
    if key not in _TEMPLATE_NAMES:
        available = ", ".join(sorted(_TEMPLATE_NAMES))
        raise SystemExit(
            f"Unknown template '{name}'. Available templates: {available}"
        )

    module = _load_template_module(key)

    template_cls: type[LabelTemplate] | None = getattr(
        module,
        "Template",
        None,
    )
    if not template_cls or not issubclass(template_cls, LabelTemplate):
        raise SystemExit(
            f"Template '{name}' does not export a valid Template class"
        )

    template = template_cls()
    return template


def list_templates() -> Iterable[str]:
    """Return the template identifiers."""

    return sorted(_TEMPLATE_NAMES)
