"""Template loader for Homebox label generators."""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

_TEMPLATE_MAP = {
    "5163": "avery5163",
}

REQUIRED_ATTRS = {"get_label_grid", "draw_label"}


def get_template(name: str) -> ModuleType:
    """Load the template module for the provided identifier."""

    key = name.lower()
    module_name = _TEMPLATE_MAP.get(key)
    if not module_name:
        available = ", ".join(sorted(_TEMPLATE_MAP))
        raise SystemExit(
            f"Unknown template '{name}'. Available templates: {available}"
        )

    module = import_module(f"{__name__}.{module_name}")

    missing = [attr for attr in REQUIRED_ATTRS if not hasattr(module, attr)]
    if missing:
        raise SystemExit(
            f"Template '{name}' is missing required attributes: {', '.join(missing)}"
        )

    return module

