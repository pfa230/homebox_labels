"""Template loader for Homebox label generators."""

from __future__ import annotations

from importlib import import_module

from typing import Dict, Iterable, Optional

from .base import LabelTemplate

_TEMPLATE_MAP = {
    "5163": "avery5163",
    "5163_vert": "avery5163_vert",
    "ptouch": "ptouch",
}


def get_template(
    name: str,
    options: Optional[Dict[str, str]] = None,
) -> LabelTemplate:
    """Instantiate the template implementation for ``name``."""

    key = name.lower()
    module_name = _TEMPLATE_MAP.get(key)
    if not module_name:
        available = ", ".join(sorted(_TEMPLATE_MAP))
        raise SystemExit(
            f"Unknown template '{name}'. Available templates: {available}"
        )

    module = import_module(f"{__name__}.{module_name}")

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
    if options:
        template.apply_options(options)
    return template


def list_templates() -> Iterable[str]:
    """Return available template identifiers."""

    return sorted(_TEMPLATE_MAP.keys())
