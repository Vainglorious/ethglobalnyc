"""Tests for standalone scouting source ingestion."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import textwrap
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from .scouting_pipeline import (
    ScoutingRunLogger,
    SourceSpec,
    build_local_scouting_result,
    parse_source_spec,
    write_local_scouting_artifacts,
)
from .scouting_views import DOMAIN_GRAPH_ENTITY_TYPES, KNOWLEDGE_VIEW_NAMES


MATCH_ENTITY = {
    "entity_id": "match:world_cup_2026:test:brazil_morocco",
    "entity_type": "match",
    "name": "Brazil vs Morocco",
    "attributes": {
        "team1": "Brazil",
        "team2": "Morocco",
        "date": "2026-06-13",
        "time": "18:00 UTC-4",
        "group": "Group C",
        "round": "Matchday 3",
        "ground": "New York/New Jersey (East Rutherford)",
    },
}


class ScoutingPipelineTests(unittest.TestCase):
    def test_parse_source_spec_accepts_plain_url(self) -> None:
        source = parse_source_spec("https://example.test/brazil-morocco-preview")

        self.assertEqual(source.kind, "url")
        self.assertEqual(source.locator, "https://example.test/brazil-morocco-preview")

    def test_parse_source_spec_accepts_mcp_stdio_object(self) -> None:
        source = parse_source_spec(
            {
                "kind": "mcp_stdio",
                "command": ["python3", "server.py"],
                "tool": "scout_match",
                "arguments": {"match": "Brazil vs Morocco"},
            }
        )

        self.assertEqual(source.kind, "mcp-stdio")
        self.assertEqual(source.config["tool"], "scout_match")

    def test_as_of_gate_keeps_only_pre_cutoff_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "dated_claims.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "findings": [
                            {
                                "finding_id": "dated_market",
                                "scout_name": "dated_market_scout",
                                "source_type": "odds",
                                "finding_name": "dated_market_claims",
                                "evidence_claims": [
                                    {
                                        "claim_type": "market_snapshot",
                                        "subject": "Brazil market",
                                        "team": "Brazil",
                                        "claim": "Pre-cutoff odds signal favours Brazil.",
                                        "impact": "context_home",
                                        "source_title": "Historical odds",
                                        "source_url": "https://example.test/pre",
                                        "source_kind": "api",
                                        "source_quality": "strong",
                                        "available_at_utc": "2026-06-13T18:00:00Z",
                                    },
                                    {
                                        "claim_type": "market_snapshot",
                                        "subject": "Brazil market",
                                        "team": "Brazil",
                                        "claim": "Post-cutoff odds signal should be hidden.",
                                        "impact": "context_home",
                                        "source_title": "Historical odds",
                                        "source_url": "https://example.test/post",
                                        "source_kind": "api",
                                        "source_quality": "strong",
                                        "available_at_utc": "2026-06-13T20:00:00Z",
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[parse_source_spec({"kind": "json", "path": str(payload_path)})],
                as_of_utc="2026-06-13T19:00:00Z",
            )

        claims = [claim for finding in result.findings for claim in finding.evidence_claims]
        self.assertEqual(len(claims), 1)
        self.assertIn("Pre-cutoff", claims[0]["claim"])

    def test_as_of_gate_keeps_durable_fixture_context(self) -> None:
        result = build_local_scouting_result(
            match_entity=MATCH_ENTITY,
            mode="fast",
            sources=[SourceSpec("fixture", raw="fixture")],
            as_of_utc="2026-06-13T16:00:00Z",
        )

        claims = [claim for finding in result.findings for claim in finding.evidence_claims]
        self.assertGreaterEqual(len(claims), 2)
        self.assertTrue(all(claim["claim_type"] in {"match_schedule", "team_profile"} for claim in claims))

    def test_mcp_document_payload_is_extracted_into_kg_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "mcp_export.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "documents": [
                            {
                                "title": "MCP Brazil Morocco scout",
                                "url": "mcp://local/brazil-morocco",
                                "text": (
                                    "Brazil recent form shows Brazil won 4 of their last 6 matches. "
                                    "Neymar has 18 goals and 9 assists in 42 appearances for Brazil. "
                                    "Morocco predicted lineup uses a 4-1-4-1 formation."
                                ),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[SourceSpec("mcp", locator=str(payload_path), raw=f"mcp:{payload_path}")],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}
        entity_types = {entity.entity_type for entity in result.graph.entities}

        self.assertIn("recent_form", claim_types)
        self.assertIn("player_form", claim_types)
        self.assertIn("lineup", claim_types)
        self.assertIn("evidence_claim", entity_types)
        self.assertIn("player", entity_types)

    def test_local_artifacts_include_domain_graph_and_agent_ready_views(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "mcp_export.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "documents": [
                            {
                                "title": "MCP Brazil Morocco scout",
                                "url": "mcp://local/brazil-morocco",
                                "text": (
                                    "Brazil recent form shows Brazil won 4 of their last 6 matches. "
                                    "Neymar has 18 goals and 9 assists in 42 appearances for Brazil. "
                                    "Morocco predicted lineup uses a 4-1-4-1 formation."
                                ),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[SourceSpec("mcp", locator=str(payload_path), raw=f"mcp:{payload_path}")],
            )
            out_dir = Path(tmp) / "run"
            write_local_scouting_artifacts(
                out_dir=out_dir,
                result=result,
                logger=ScoutingRunLogger(verbose=False),
                mode="fast",
            )

            domain_graph = json.loads((out_dir / "domain_graph.json").read_text(encoding="utf-8"))
            views = json.loads((out_dir / "knowledge_views.json").read_text(encoding="utf-8"))
            run_summary = json.loads((out_dir / "scouting_run_summary.json").read_text(encoding="utf-8"))
            manifest = json.loads((out_dir / "kg_manifest.json").read_text(encoding="utf-8"))

        domain_types = {entity["entity_type"] for entity in domain_graph["entities"]}
        domain_entity_ids = {entity["entity_id"] for entity in domain_graph["entities"]}

        self.assertTrue(domain_graph["entities"])
        self.assertLessEqual(domain_types, DOMAIN_GRAPH_ENTITY_TYPES)
        self.assertIn("match", domain_types)
        self.assertIn("team", domain_types)
        self.assertNotIn("evidence_claim", domain_types)
        self.assertNotIn("source", domain_types)
        self.assertTrue(
            all(
                relationship["source_id"] in domain_entity_ids
                and relationship["target_id"] in domain_entity_ids
                for relationship in domain_graph["relationships"]
            )
        )
        self.assertEqual(views["view_names"], list(KNOWLEDGE_VIEW_NAMES))
        for view_name in KNOWLEDGE_VIEW_NAMES:
            self.assertIn(view_name, views)
        self.assertGreaterEqual(len(views["team_snapshot"]["teams"]), 2)
        self.assertGreater(views["source_quality_summary"]["evidence_claim_count"], 0)
        self.assertEqual(manifest["files"]["domain_graph"], "domain_graph.json")
        self.assertEqual(manifest["files"]["scouting_run_summary"], "scouting_run_summary.json")
        self.assertEqual(run_summary["artifact_files"]["domain_graph"], "domain_graph.json")
        self.assertEqual(run_summary["knowledge_views"]["view_names"], list(KNOWLEDGE_VIEW_NAMES))
        self.assertTrue(run_summary["kg_load_ready"])
        self.assertIn("agent_ready", run_summary)

    def test_mcp_stdio_tool_result_is_extracted_into_kg_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server_path = Path(tmp) / "fake_mcp_server.py"
            server_path.write_text(
                textwrap.dedent(
                    """
                    import json
                    import sys

                    for line in sys.stdin:
                        message = json.loads(line)
                        method = message.get("method")
                        if method == "initialize":
                            response = {
                                "jsonrpc": "2.0",
                                "id": message.get("id"),
                                "result": {
                                    "protocolVersion": "2024-11-05",
                                    "capabilities": {"tools": {}},
                                    "serverInfo": {"name": "fake-scout", "version": "0.1"},
                                },
                            }
                            print(json.dumps(response), flush=True)
                        elif method == "tools/call":
                            text = (
                                "Brazil recent form shows Brazil won 4 of their last 6 matches. "
                                "Neymar has 18 goals and 9 assists in 42 appearances for Brazil. "
                                "Morocco predicted lineup uses a 4-1-4-1 formation."
                            )
                            response = {
                                "jsonrpc": "2.0",
                                "id": message.get("id"),
                                "result": {"content": [{"type": "text", "text": text}]},
                            }
                            print(json.dumps(response), flush=True)
                    """
                ).strip()
                + "\n",
                encoding="utf-8",
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[
                    SourceSpec(
                        "mcp-stdio",
                        config={
                            "command": [sys.executable, str(server_path)],
                            "tool": "scout_match",
                            "arguments": {"match": "Brazil vs Morocco"},
                        },
                    )
                ],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}
        scout_names = {finding.scout_name for finding in result.findings}

        self.assertIn("recent_form", claim_types)
        self.assertIn("player_form", claim_types)
        self.assertIn("lineup", claim_types)
        self.assertIn("mcp-stdio_document_scout", scout_names)

    def test_polymarket_mcp_stdio_source_maps_market_snapshot_claims(self) -> None:
        server_path = Path(__file__).resolve().parents[2] / "polymarket" / "mcp_server.py"

        result = build_local_scouting_result(
            match_entity=MATCH_ENTITY,
            mode="fast",
            sources=[
                SourceSpec(
                    "mcp-stdio",
                    config={
                        "command": [sys.executable, str(server_path), "--offline"],
                        "tool": "scout_match_market",
                        "arguments": {
                            "match": "Brazil vs Morocco",
                            "home_team": "Brazil",
                            "away_team": "Morocco",
                            "limit": 5,
                        },
                    },
                )
            ],
        )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}
        scout_names = {finding.scout_name for finding in result.findings}

        self.assertIn("market_snapshot", claim_types)
        self.assertIn("polymarket_mcp_scout", scout_names)
        self.assertTrue(any(claim["metrics"]["token_id"] == "offline-home-token" for claim in claims))

    def test_cli_plain_text_source_is_extracted_into_kg_claims(self) -> None:
        command = (
            f"{sys.executable} -c "
            "\"print('Brazil recent form shows Brazil won 4 of their last 6 matches. "
            "Neymar has 18 goals and 9 assists in 42 appearances for Brazil.')\""
        )

        result = build_local_scouting_result(
            match_entity=MATCH_ENTITY,
            mode="fast",
            sources=[SourceSpec("cli", locator=command, raw=f"cli:{command}")],
        )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}

        self.assertIn("recent_form", claim_types)
        self.assertIn("player_form", claim_types)

    def test_polymarket_cli_source_maps_market_snapshot_claims(self) -> None:
        cli_path = Path(__file__).resolve().parents[2] / "polymarket" / "scout_market.py"
        source = parse_source_spec(
            {
                "kind": "cli",
                "command": [
                    sys.executable,
                    str(cli_path),
                    "--offline",
                    "--match",
                    "Brazil vs Morocco",
                    "--home-team",
                    "Brazil",
                    "--away-team",
                    "Morocco",
                    "--limit",
                    "5",
                ],
            }
        )

        result = build_local_scouting_result(
            match_entity=MATCH_ENTITY,
            mode="fast",
            sources=[source],
        )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        self.assertIn("polymarket_cli_scout", {finding.scout_name for finding in result.findings})
        self.assertTrue(any(claim["claim_type"] == "market_snapshot" for claim in claims))
        self.assertTrue(any(claim["source_kind"] == "cli" for claim in claims))

    def test_api_html_source_is_extracted_into_kg_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "api_preview.html"
            html_path.write_text(
                (
                    "<html><body>"
                    "<p>Brazil recent form shows Brazil won 4 of their last 6 matches.</p>"
                    "<p>Morocco predicted lineup uses a 4-1-4-1 formation.</p>"
                    "</body></html>"
                ),
                encoding="utf-8",
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[SourceSpec("api", locator=html_path.as_uri(), raw=f"api:{html_path.as_uri()}")],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}

        self.assertIn("recent_form", claim_types)
        self.assertIn("lineup", claim_types)

    def test_failing_external_source_is_logged_without_aborting_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_payload = Path(tmp) / "missing_api_payload.json"
            source = parse_source_spec({"kind": "api", "url": missing_payload.as_uri()})

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[SourceSpec("fixture", raw="fixture"), source],
            )

        self.assertTrue(result.findings)
        self.assertEqual(result.source_summaries[-1]["source"], f"api:{missing_payload.as_uri()}")
        self.assertEqual(result.source_summaries[-1]["finding_count"], 0)
        self.assertIn("error_type", result.source_summaries[-1])

    def test_polymarket_api_source_maps_public_search_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "polymarket_public_search.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "slug": "brazil-vs-morocco",
                                "markets": [
                                    {
                                        "id": "pm-1",
                                        "conditionId": "condition-1",
                                        "question": "Will Brazil vs. Morocco end in a draw?",
                                        "slug": "fifwc-bra-mar-2026-06-13-draw",
                                        "outcomes": json.dumps(["Yes", "No"]),
                                        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
                                        "outcomePrices": json.dumps(["0.31", "0.69"]),
                                        "volume": "1000",
                                        "liquidity": "250",
                                        "active": True,
                                        "closed": False,
                                        "acceptingOrders": True,
                                    }
                                ],
                            }
                        ],
                        "pagination": {"hasMore": False, "totalResults": 1},
                    }
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "polymarket_market",
                    "title": "Polymarket public search",
                    "max_rows": 5,
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        self.assertEqual(result.findings[0].scout_name, "polymarket_api_scout")
        self.assertEqual(result.findings[0].source_type, "market")
        self.assertTrue(any(claim["metrics"]["token_id"] == "yes-token" for claim in claims))
        self.assertTrue(all(claim["source_kind"] == "market_snapshot" for claim in claims))
        self.assertTrue(all(claim["team"] == "" for claim in claims))

    def test_polymarket_clob_source_enriches_gamma_markets_with_orderbook_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "polymarket_public_search.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "slug": "brazil-vs-morocco",
                                "markets": [
                                    {
                                        "id": "pm-1",
                                        "conditionId": "condition-1",
                                        "question": "Will Brazil vs. Morocco end in a draw?",
                                        "slug": "fifwc-bra-mar-2026-06-13-draw",
                                        "outcomes": json.dumps(["Yes", "No"]),
                                        "clobTokenIds": json.dumps(["yes-token", "no-token"]),
                                        "outcomePrices": json.dumps(["0.31", "0.69"]),
                                        "volume": "1000",
                                        "liquidity": "250",
                                        "active": True,
                                        "closed": False,
                                        "acceptingOrders": True,
                                    }
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "polymarket_clob",
                    "title": "Polymarket CLOB test",
                    "max_rows": 5,
                    "clob_snapshots": {
                        "yes-token": {
                            "mid": "0.315",
                            "bids": [{"price": "0.30", "size": "10"}, {"price": "0.31", "size": "4"}],
                            "asks": [{"price": "0.32", "size": "6"}, {"price": "0.34", "size": "9"}],
                            "timestamp": "1781892739521",
                        }
                    },
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        yes_claim = next(claim for claim in claims if claim["metrics"]["token_id"] == "yes-token")
        self.assertEqual(yes_claim["extraction_method"], "polymarket_gamma_clob_adapter")
        self.assertEqual(yes_claim["metrics"]["clob_midpoint"], 0.315)
        self.assertEqual(yes_claim["metrics"]["clob_best_bid"], 0.31)
        self.assertEqual(yes_claim["metrics"]["clob_best_ask"], 0.32)
        self.assertEqual(yes_claim["metrics"]["clob_spread"], 0.01)
        self.assertIn("CLOB midpoint is 0.315", yes_claim["claim"])

    def test_wikidata_api_source_maps_profile_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "wikidata_profiles.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "head": {"vars": ["kind", "team", "teamLabel", "player", "playerLabel"]},
                        "results": {
                            "bindings": [
                                {
                                    "kind": {"type": "literal", "value": "team"},
                                    "team": {"type": "uri", "value": "http://www.wikidata.org/entity/Q83459"},
                                    "teamLabel": {"type": "literal", "value": "Brazil national football team"},
                                    "teamDescription": {"type": "literal", "value": "men's national association football team"},
                                    "country": {"type": "uri", "value": "http://www.wikidata.org/entity/Q155"},
                                    "countryLabel": {"type": "literal", "value": "Brazil"},
                                    "coach": {"type": "uri", "value": "http://www.wikidata.org/entity/Q187221"},
                                    "coachLabel": {"type": "literal", "value": "Carlo Ancelotti"},
                                },
                                {
                                    "kind": {"type": "literal", "value": "player"},
                                    "team": {"type": "uri", "value": "http://www.wikidata.org/entity/Q83459"},
                                    "teamLabel": {"type": "literal", "value": "Brazil national football team"},
                                    "player": {"type": "uri", "value": "http://www.wikidata.org/entity/Q142794"},
                                    "playerLabel": {"type": "literal", "value": "Neymar"},
                                    "playerDescription": {"type": "literal", "value": "Brazilian association football player"},
                                    "position": {"type": "uri", "value": "http://www.wikidata.org/entity/Q280658"},
                                    "positionLabel": {"type": "literal", "value": "forward"},
                                },
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "wikidata_profiles",
                    "title": "Wikidata football profiles",
                    "max_players_per_team": 2,
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}
        entity_types = {entity.entity_type for entity in result.graph.entities}

        self.assertIn("team_profile", claim_types)
        self.assertIn("player_profile", claim_types)
        self.assertIn("player", entity_types)
        self.assertTrue(any(claim["metrics"].get("wikidata_player_id") == "Q142794" for claim in claims))

    def test_wikidata_entity_search_source_maps_team_profile_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "wikidata_entity_search.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "search": [
                            {
                                "id": "Q83459",
                                "title": "Q83459",
                                "concepturi": "http://www.wikidata.org/entity/Q83459",
                                "label": "Brazil national football team",
                                "description": "men's national association football team representing Brazil",
                                "repository": "wikidata",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "wikidata_entity_search",
                    "title": "Wikidata entity search: Brazil",
                    "team": "Brazil",
                    "max_rows": 1,
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]

        self.assertEqual(result.findings[0].scout_name, "wikidata_entity_search_api_scout")
        self.assertTrue(any(claim["claim_type"] == "team_profile" for claim in claims))
        self.assertTrue(any(claim["metrics"].get("wikidata_id") == "Q83459" for claim in claims))

    def test_polymarket_adapter_rejects_old_basketball_market(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "polymarket_mixed_public_search.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "slug": "usa-australia",
                                "markets": [
                                    {
                                        "id": "old-basketball",
                                        "conditionId": "condition-old",
                                        "question": (
                                            "Will the USA beat Australia by 10 or more points in the Men's "
                                            "Basketball Tokyo 2020 Olympic Semifinals match?"
                                        ),
                                        "slug": "usa-australia-basketball-tokyo-2020",
                                        "outcomes": json.dumps(["Yes", "No"]),
                                        "clobTokenIds": json.dumps(["old-yes", "old-no"]),
                                        "outcomePrices": json.dumps(["0.99", "0.01"]),
                                        "active": True,
                                        "closed": False,
                                    },
                                    {
                                        "id": "world-cup-draw",
                                        "conditionId": "condition-good",
                                        "question": "Will USA vs. Australia end in a draw?",
                                        "slug": "fifwc-usa-aus-2026-06-19-draw",
                                        "outcomes": json.dumps(["Yes", "No"]),
                                        "clobTokenIds": json.dumps(["good-yes", "good-no"]),
                                        "outcomePrices": json.dumps(["0.22", "0.78"]),
                                        "active": True,
                                        "closed": False,
                                    },
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "polymarket_market",
                    "title": "Polymarket public search",
                }
            )

            result = build_local_scouting_result(
                match_entity={
                    **MATCH_ENTITY,
                    "name": "USA vs Australia",
                    "attributes": {**MATCH_ENTITY["attributes"], "team1": "USA", "team2": "Australia", "date": "2026-06-19"},
                },
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        self.assertEqual(len(claims), 2)
        self.assertTrue(all("basketball" not in claim["claim"].casefold() for claim in claims))
        self.assertTrue(any(claim["metrics"]["token_id"] == "good-yes" for claim in claims))

    def test_generic_row_claims_filter_blocks_unrelated_api_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "unrelated_markets.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "markets": [
                            {
                                "id": "pm-2",
                                "question": "Will Spain beat Germany?",
                                "slug": "spain-germany",
                                "outcomes": json.dumps(["Spain", "Germany"]),
                                "outcomePrices": json.dumps(["0.52", "0.48"]),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "row_claims",
                    "rows_path": "markets[]",
                    "row_filter": {"field": "question", "match_teams": True},
                    "claim": {
                        "for_each": "outcomes",
                        "claim_type": "market_snapshot",
                        "team": "{home_team}",
                        "claim": "{question} {item}",
                        "source_url": "https://example.test/event/{slug}",
                        "source_quality": "strong",
                    },
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        self.assertEqual(result.findings, [])

    def test_generic_row_claims_filter_excludes_noisy_public_search_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "mixed_markets.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "markets": [
                            {
                                "id": "pm-clean",
                                "question": "Will Brazil vs Morocco end in a draw?",
                                "slug": "brazil-morocco-draw",
                                "outcomes": json.dumps(["Yes", "No"]),
                                "outcomePrices": json.dumps(["0.31", "0.69"]),
                            },
                            {
                                "id": "pm-noisy",
                                "question": "Will announcers mention Visa during Brazil vs Morocco?",
                                "slug": "brazil-morocco-announcers-visa",
                                "outcomes": json.dumps(["Yes", "No"]),
                                "outcomePrices": json.dumps(["0.12", "0.88"]),
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "row_claims",
                    "rows_path": "markets[]",
                    "row_filter": {
                        "field": "question",
                        "match_teams": True,
                        "exclude_contains_any": ["announcers", "visa"],
                    },
                    "claim": {
                        "for_each": "outcomes",
                        "claim_type": "market_snapshot",
                        "team": "{home_team}",
                        "claim": "{question} {item}",
                        "source_url": "https://example.test/event/{slug}",
                        "source_quality": "strong",
                    },
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        self.assertEqual(len(claims), 2)
        self.assertTrue(all("announcers" not in claim["claim"].casefold() for claim in claims))

    def test_txline_fixture_api_source_maps_structured_fixture_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"TXLINE_JWT": "test-jwt", "TXLINE_API_TOKEN": "test-api-token"},
            clear=False,
        ):
            payload_path = Path(tmp) / "txline_fixtures.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {
                            "Ts": 1781359200000,
                            "StartTime": 1781373600000,
                            "Competition": "World Cup",
                            "CompetitionId": 101,
                            "FixtureGroupId": 12,
                            "Participant1Id": 1,
                            "Participant1": "Brazil",
                            "Participant2Id": 2,
                            "Participant2": "Morocco",
                            "FixtureId": 987654,
                            "Participant1IsHome": True,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "txline_fixtures",
                    "title": "TXLINE fixtures snapshot",
                    "headers": {
                        "Authorization": "Bearer ${TXLINE_JWT}",
                        "X-Api-Token": "${TXLINE_API_TOKEN}",
                    },
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}
        schedule_claim = next(claim for claim in claims if claim["claim_type"] == "match_schedule")

        self.assertIn("team_profile", claim_types)
        self.assertIn("match_schedule", claim_types)
        self.assertEqual(schedule_claim["metrics"]["fixture_id"], 987654)
        self.assertEqual(schedule_claim["source_kind"], "api")
        self.assertEqual(schedule_claim["source_quality"], "strong")
        self.assertEqual(schedule_claim["source_title"], "TXLINE fixtures snapshot")

    def test_txline_odds_api_source_maps_market_snapshot_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "txline_odds.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {
                            "FixtureId": 987654,
                            "MessageId": "msg-1",
                            "Ts": 1781359200000,
                            "Bookmaker": "ExampleBook",
                            "BookmakerId": 4,
                            "SuperOddsType": "1X2",
                            "InRunning": False,
                            "GameState": "PreMatch",
                            "MarketPeriod": "FullTime",
                            "PriceNames": ["part1", "draw", "part2"],
                            "Prices": [1500, 3400, 5200],
                            "Pct": ["0.667", "0.294", "0.192"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "txline_odds",
                    "title": "TXLINE odds snapshot",
                    "max_rows": 1,
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        self.assertEqual(result.findings[0].source_type, "odds")
        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        self.assertEqual(claims[0]["claim_type"], "market_snapshot")
        self.assertEqual(claims[0]["metrics"]["fixture_id"], 987654)
        self.assertEqual(json.loads(claims[0]["metrics"]["price_names"]), ["part1", "draw", "part2"])
        self.assertEqual(json.loads(claims[0]["metrics"]["price_labels"]), ["Brazil", "draw", "Morocco"])
        self.assertIn("Brazil=1500", claims[0]["claim"])

    def test_api_source_empty_on_status_treats_404_as_empty_payload(self) -> None:
        source = parse_source_spec(
            {
                "kind": "api",
                "url": "https://example.test/api/odds/snapshot/987654",
                "adapter": "txline_odds",
                "title": "TXLINE odds snapshot",
                "empty_on_status": [404],
            }
        )
        http_error = urllib.error.HTTPError(
            source.config["url"],
            404,
            "Not Found",
            {"Content-Type": "text/plain"},
            io.BytesIO(b"not found"),
        )

        with mock.patch("urllib.request.urlopen", side_effect=http_error):
            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        self.assertEqual(result.source_summaries[0]["finding_count"], 0)
        self.assertEqual(result.source_summaries[0]["evidence_claim_count"], 0)
        self.assertNotIn("error_type", result.source_summaries[0])

    def test_txline_scores_api_source_maps_scheduled_rows_to_coverage_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload_path = Path(tmp) / "txline_scores.json"
            payload_path.write_text(
                json.dumps(
                    [
                        {
                            "fixtureId": 987654,
                            "action": "coverage_update",
                            "gameState": "scheduled",
                            "startTime": 1781373600000,
                            "seq": 1,
                            "ts": 1781359200000,
                            "confirmed": True,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            source = parse_source_spec(
                {
                    "kind": "api",
                    "url": payload_path.as_uri(),
                    "adapter": "txline_scores",
                    "title": "TXLINE score snapshot",
                    "max_rows": 1,
                }
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[source],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        self.assertEqual(claims[0]["claim_type"], "coverage_status")
        self.assertEqual(claims[0]["metrics"]["game_state"], "scheduled")

    def test_url_html_source_is_scraped_into_claims(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "preview.html"
            html_path.write_text(
                (
                    "<html><head><title>Brazil Morocco preview</title></head><body>"
                    "<p>Brazil recent form shows Brazil won 4 of their last 6 matches and scored 11 goals in their last 6 matches.</p>"
                    "<p>Neymar has 18 goals and 9 assists in 42 appearances for Brazil.</p>"
                    "</body></html>"
                ),
                encoding="utf-8",
            )

            result = build_local_scouting_result(
                match_entity=MATCH_ENTITY,
                mode="fast",
                sources=[SourceSpec("url", locator=html_path.as_uri(), raw=html_path.as_uri())],
            )

        claims = [
            claim
            for finding in result.findings
            for claim in finding.evidence_claims
        ]
        claim_types = {claim["claim_type"] for claim in claims}

        self.assertIn("recent_form", claim_types)
        self.assertIn("player_form", claim_types)


if __name__ == "__main__":
    unittest.main()
