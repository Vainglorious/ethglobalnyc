"""Tests for catalog-driven scouting matrix source assembly."""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest import mock


COLONY_DIR = Path(__file__).resolve().parents[1]
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

_SPEC = importlib.util.spec_from_file_location("scouting_matrix_module", COLONY_DIR / "scouting_matrix.py")
assert _SPEC and _SPEC.loader
scouting_matrix = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(scouting_matrix)

_SCOUT_TO_KG_SPEC = importlib.util.spec_from_file_location("scout_to_kg_module", COLONY_DIR / "scout_to_kg.py")
assert _SCOUT_TO_KG_SPEC and _SCOUT_TO_KG_SPEC.loader
scout_to_kg = importlib.util.module_from_spec(_SCOUT_TO_KG_SPEC)
_SCOUT_TO_KG_SPEC.loader.exec_module(scout_to_kg)


MATCH_ENTITY = {
    "entity_id": "match:world_cup_2026:test:brazil_morocco",
    "entity_type": "match",
    "name": "Brazil vs Morocco",
    "attributes": {
        "team1": "Brazil",
        "team2": "Morocco",
        "date": "2026-06-13",
    },
}


class ScoutingMatrixCatalogTests(unittest.TestCase):
    def test_catalog_expands_bundle_modules(self) -> None:
        catalog = scouting_matrix._load_source_catalog(str(scouting_matrix.DEFAULT_SOURCE_CATALOG))

        modules = scouting_matrix._expanded_modules(["txline_full"], catalog)

        self.assertEqual(
            modules,
            ["fixture", "txline_fixture", "txline_scores", "txline_odds_historical"],
        )

    def test_catalog_template_rendering_preserves_row_claim_placeholders(self) -> None:
        rendered = scouting_matrix._render_catalog_value(
            {
                "query": {"q": "{team1} {team2}"},
                "claim": "Market '{question}' has price {outcomePrices[item_index]} for {team1}.",
            },
            {"team1": "Brazil", "team2": "Morocco"},
        )

        self.assertEqual(rendered["query"]["q"], "Brazil Morocco")
        self.assertEqual(rendered["claim"], "Market '{question}' has price {outcomePrices[item_index]} for Brazil.")

    def test_source_manifest_template_rendering_uses_selected_match(self) -> None:
        context = scout_to_kg._match_template_context(MATCH_ENTITY)

        rendered = scout_to_kg._render_manifest_value(
            {
                "title": "Polymarket public search: {match_name}",
                "query": {"q": "{team1} {team2}"},
            },
            context,
        )

        self.assertEqual(rendered["title"], "Polymarket public search: Brazil vs Morocco")
        self.assertEqual(rendered["query"]["q"], "Brazil Morocco")

    def test_catalog_sources_for_match_are_provider_neutral_specs(self) -> None:
        catalog_path = scouting_matrix.DEFAULT_SOURCE_CATALOG
        catalog = scouting_matrix._load_source_catalog(str(catalog_path))
        self.assertTrue(catalog_path.exists())

        sources = scouting_matrix._sources_for_match(
            MATCH_ENTITY,
            ["fixture", "polymarket_api"],
            catalog=catalog,
        )

        self.assertEqual([source.kind for source in sources], ["fixture", "api"])
        self.assertEqual(sources[1].config["query"]["q"], "Brazil Morocco")
        self.assertEqual(sources[1].config["adapter"], "polymarket_gamma")

    def test_txline_context_renders_prediction_cutoff_as_epoch_ms(self) -> None:
        context = scouting_matrix._match_template_context(
            MATCH_ENTITY,
            txline_fixture={"fixture_id": 17588234, "start_time": 1782500400000},
            cutoff_hours=6.0,
        )

        self.assertEqual(context["txline_prediction_cutoff_utc"], "2026-06-26T13:00:00Z")
        self.assertEqual(context["txline_prediction_cutoff_ms"], "1782478800000")

    def test_catalog_pipeline_flags_enable_optional_social_modules(self) -> None:
        catalog = scouting_matrix._load_source_catalog(str(scouting_matrix.DEFAULT_SOURCE_CATALOG))

        flags = scouting_matrix._pipeline_flags_for_modules(["fixture", "public_x", "public_camel"], catalog)

        self.assertTrue(flags["include_x"])
        self.assertTrue(flags["include_camel"])
        self.assertFalse(flags["include_camel_deep"])
        self.assertEqual(flags["camel_agent_count"], 4)
        self.assertFalse(flags["include_telegram"])

    def test_catalog_pipeline_flags_allow_camel_agent_override(self) -> None:
        catalog = scouting_matrix._load_source_catalog(str(scouting_matrix.DEFAULT_SOURCE_CATALOG))

        flags = scouting_matrix._pipeline_flags_for_modules(
            ["public_camel"],
            catalog,
            camel_agent_count_override=2,
        )

        self.assertTrue(flags["include_camel"])
        self.assertEqual(flags["camel_agent_count"], 2)

    def test_catalog_pipeline_flags_enable_camel_deep_research(self) -> None:
        catalog = scouting_matrix._load_source_catalog(str(scouting_matrix.DEFAULT_SOURCE_CATALOG))

        flags = scouting_matrix._pipeline_flags_for_modules(["camel_deep_research"], catalog)

        self.assertTrue(flags["include_camel_deep"])
        self.assertFalse(flags["include_camel"])
        self.assertEqual(flags["camel_agent_count"], 6)

    def test_sources_for_match_dedupes_shared_public_source(self) -> None:
        catalog = scouting_matrix._load_source_catalog(str(scouting_matrix.DEFAULT_SOURCE_CATALOG))

        sources = scouting_matrix._sources_for_match(
            MATCH_ENTITY,
            ["fixture", "public", "camel_deep_research"],
            catalog=catalog,
        )

        self.assertEqual([source.kind for source in sources], ["fixture", "public"])

    def test_catalog_requires_any_env_groups_for_x_connector(self) -> None:
        catalog = scouting_matrix._load_source_catalog(str(scouting_matrix.DEFAULT_SOURCE_CATALOG))
        module = scouting_matrix._catalog_module(catalog, "public_x")
        clear_names = {
            "SCRAPECREATORS_X_SEARCH_URL": "",
            "COLONY_X_SEARCH_URL": "",
            "SCRAPECREATORS_API_KEY": "",
            "COLONY_X_API_KEY": "",
        }

        with mock.patch.dict(os.environ, clear_names, clear=False):
            missing = scouting_matrix._missing_module_env(module)

        self.assertIn("one_of(SCRAPECREATORS_X_SEARCH_URL|COLONY_X_SEARCH_URL)", missing)
        self.assertIn("one_of(SCRAPECREATORS_API_KEY|COLONY_X_API_KEY)", missing)

        with mock.patch.dict(
            os.environ,
            {
                **clear_names,
                "COLONY_X_SEARCH_URL": "https://example.test/search?q={query}",
                "COLONY_X_API_KEY": "test-key",
            },
            clear=False,
        ):
            self.assertEqual(scouting_matrix._missing_module_env(module), [])


if __name__ == "__main__":
    unittest.main()
