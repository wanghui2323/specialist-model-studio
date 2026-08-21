from __future__ import annotations

from importlib import metadata
from threading import Lock
from typing import Any, Iterable

from .errors import PluginError
from .plugin_api import RecipePlugin


ENTRY_POINT_GROUP = "ai_pm_model_harness.recipes"


class PluginRegistry:
    def __init__(self, include_builtins: bool = True) -> None:
        self._recipes: dict[str, RecipePlugin] = {}
        if include_builtins:
            from .recipes.digit_plugin import PLUGIN
            from .recipes.image_folder_plugin import PLUGIN as IMAGE_FOLDER_PLUGIN
            from .recipes.tabular_regression_plugin import PLUGIN as TABULAR_REGRESSION_PLUGIN

            self.register_recipe(PLUGIN)
            self.register_recipe(IMAGE_FOLDER_PLUGIN)
            self.register_recipe(TABULAR_REGRESSION_PLUGIN)

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

    def recipe_manifests(self) -> list[dict[str, Any]]:
        return [self._recipes[key].manifest.to_dict() for key in self.recipe_ids()]

    def match_recipes(self, capability: dict[str, Any]) -> list[dict[str, Any]]:
        """Return deterministic, explainable matches for a task capability request."""

        modality = str(capability.get("modality", "")).strip().lower()
        objective = str(capability.get("objective", "")).strip().lower()
        target_kind = str(capability.get("target_kind", "")).strip().lower()
        data_adapter = str(capability.get("data_adapter", "")).strip().lower()
        requested_tags = {
            str(tag).strip().lower()
            for tag in capability.get("tags", [])
            if str(tag).strip()
        }
        matches: list[dict[str, Any]] = []
        for plugin_id in self.recipe_ids():
            manifest = self._recipes[plugin_id].manifest
            reasons: list[str] = []
            score = 0
            blocked = False
            for label, requested, supported, weight in (
                ("modality", modality, manifest.modalities, 5),
                ("objective", objective, manifest.objectives, 5),
                ("target_kind", target_kind, manifest.target_kinds, 2),
            ):
                supported_values = {value.lower() for value in supported}
                if requested:
                    if requested in supported_values:
                        score += weight
                        reasons.append(f"{label}={requested}")
                    else:
                        blocked = True
            if data_adapter:
                if (manifest.data_adapter or "").lower() == data_adapter:
                    score += 4
                    reasons.append(f"data_adapter={data_adapter}")
                else:
                    blocked = True
            tag_overlap = requested_tags & {
                value.lower() for value in manifest.capability_tags
            }
            if tag_overlap:
                score += len(tag_overlap)
                reasons.append(f"tags={','.join(sorted(tag_overlap))}")
            if not blocked and score > 0:
                matches.append(
                    {
                        "plugin_id": plugin_id,
                        "score": score,
                        "reasons": reasons,
                        "manifest": manifest.to_dict(),
                    }
                )
        return sorted(matches, key=lambda item: (-int(item["score"]), item["plugin_id"]))


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
