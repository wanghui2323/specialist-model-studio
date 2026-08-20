from __future__ import annotations

from importlib import metadata
from threading import Lock
from typing import Iterable

from .errors import PluginError
from .plugin_api import RecipePlugin


ENTRY_POINT_GROUP = "ai_pm_model_harness.recipes"


class PluginRegistry:
    def __init__(self, include_builtins: bool = True) -> None:
        self._recipes: dict[str, RecipePlugin] = {}
        if include_builtins:
            from .recipes.digit_plugin import PLUGIN

            self.register_recipe(PLUGIN)

    def register_recipe(self, plugin: RecipePlugin) -> None:
        if not isinstance(plugin, RecipePlugin):
            raise PluginError("recipe plugin does not satisfy the RecipePlugin protocol")
        plugin_id = plugin.manifest.plugin_id
        if not plugin_id or plugin_id in self._recipes:
            raise PluginError(f"duplicate or empty recipe plugin id: {plugin_id!r}")
        self._recipes[plugin_id] = plugin

    def discover(self) -> None:
        entry_points = metadata.entry_points()
        selected: Iterable[metadata.EntryPoint]
        if hasattr(entry_points, "select"):
            selected = entry_points.select(group=ENTRY_POINT_GROUP)
        else:  # pragma: no cover - compatibility with older Python metadata API
            selected = entry_points.get(ENTRY_POINT_GROUP, [])
        for entry_point in selected:
            loaded = entry_point.load()
            plugin = loaded() if isinstance(loaded, type) else loaded
            self.register_recipe(plugin)

    def get_recipe(self, plugin_id: str) -> RecipePlugin:
        try:
            return self._recipes[plugin_id]
        except KeyError as exc:
            raise PluginError(
                f"unknown recipe plugin: {plugin_id}; available: {self.recipe_ids()}"
            ) from exc

    def recipe_ids(self) -> list[str]:
        return sorted(self._recipes)

    def recipe_manifests(self) -> list[dict[str, str]]:
        return [self._recipes[key].manifest.to_dict() for key in self.recipe_ids()]


_default_registry: PluginRegistry | None = None
_default_lock = Lock()


def default_registry() -> PluginRegistry:
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            registry = PluginRegistry(include_builtins=True)
            registry.discover()
            _default_registry = registry
        return _default_registry
