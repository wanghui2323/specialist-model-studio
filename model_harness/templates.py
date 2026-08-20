from __future__ import annotations

from typing import Any

from .plugins import PluginRegistry, default_registry
from .recipes.digit_plugin import DIGIT_CLASSIFICATION_TEMPLATE as _DIGIT_TEMPLATE

DIGIT_CLASSIFICATION_TEMPLATE: dict[str, Any] = _DIGIT_TEMPLATE


def get_template(
    recipe: str,
    registry: PluginRegistry | None = None,
) -> dict[str, Any]:
    return (registry or default_registry()).get_recipe(recipe).template()
