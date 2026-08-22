from __future__ import annotations

import unittest
from types import SimpleNamespace

from model_harness.huggingface_catalog import (
    HuggingFaceCatalog,
    HuggingFaceCatalogError,
)


COMMIT = "a" * 40


class FakeApi:
    def __init__(self) -> None:
        self.tokens: list[bool] = []

    def list_models(self, **kwargs):
        self.tokens.append(kwargs.get("token") is not None)
        return [
            SimpleNamespace(
                id="owner/model",
                sha=COMMIT,
                cardData={"license": "apache-2.0"},
                library_name="onnx",
                pipeline_tag="image-classification",
                tags=["image-classification", "onnx"],
                downloads=20,
                likes=3,
            )
        ]

    def model_info(self, **kwargs):
        self.tokens.append(kwargs.get("token") is not None)
        return SimpleNamespace(
            id="owner/model",
            sha=COMMIT,
            card_data={"license": "apache-2.0"},
            library_name="onnx",
            pipeline_tag="image-classification",
            tags=["image-classification", "onnx"],
            downloads=20,
            likes=3,
            siblings=[
                SimpleNamespace(rfilename=".gitattributes", size=123),
                SimpleNamespace(rfilename="config.json", size=175),
                SimpleNamespace(rfilename="model.onnx", size=6_000_000),
                SimpleNamespace(rfilename="../escape.onnx", size=1),
            ],
        )


class HuggingFaceCatalogTests(unittest.TestCase):
    def test_search_and_model_card_use_official_api_and_expose_compatibility(self) -> None:
        api = FakeApi()
        catalog = HuggingFaceCatalog(api_factory=lambda token=None: api)
        results = catalog.search("mobile net", limit=5, token="ephemeral")
        self.assertEqual(results[0]["repository"], "owner/model")
        card = catalog.model_card("owner/model", revision=COMMIT, token="ephemeral")
        self.assertEqual(card["revision"], COMMIT)
        self.assertEqual(card["license"], "apache-2.0")
        self.assertEqual(card["compatibility"]["state"], "compatible_candidate")
        self.assertNotIn("../escape.onnx", {item["path"] for item in card["files"]})
        self.assertEqual(api.tokens, [True, True])
        self.assertNotIn("ephemeral", repr(results) + repr(card))

    def test_revision_and_queries_fail_closed(self) -> None:
        catalog = HuggingFaceCatalog(api_factory=lambda token=None: FakeApi())
        with self.assertRaisesRegex(HuggingFaceCatalogError, "invalid_huggingface_search"):
            catalog.search("")
        with self.assertRaisesRegex(HuggingFaceCatalogError, "revision_not_immutable"):
            catalog.model_card("owner/model", revision="main")
        with self.assertRaisesRegex(HuggingFaceCatalogError, "invalid_repo_id"):
            catalog.model_card("../escape")


if __name__ == "__main__":
    unittest.main()
