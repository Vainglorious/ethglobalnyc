"""Tests for scheduled prematch snapshot automation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


COLONY_DIR = Path(__file__).resolve().parents[1]
if str(COLONY_DIR) not in sys.path:
    sys.path.insert(0, str(COLONY_DIR))

import automate_prematch_snapshots as automation  # noqa: E402


class PrematchSnapshotAutomationTest(unittest.TestCase):
    def test_select_due_matches_uses_thirty_minute_lead_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            kg_path = _write_kg(Path(tmp))
            now = datetime(2026, 6, 22, 20, 25, tzinfo=timezone.utc)

            matches = automation.select_due_matches(
                kg_path=kg_path,
                now=now,
                lead_minutes=30,
                lookahead_minutes=10,
                grace_minutes=0,
                limit=10,
            )

        self.assertEqual([match["name"] for match in matches], ["France vs Iraq"])
        self.assertEqual(matches[0]["kickoff_utc"], "2026-06-22T21:00:00Z")
        self.assertEqual(matches[0]["prediction_cutoff_utc"], "2026-06-22T20:30:00Z")

    def test_snapshot_id_uses_prediction_cutoff_not_kickoff(self) -> None:
        match = {
            "home_team": "France",
            "away_team": "Iraq",
            "prediction_cutoff_utc": "2026-06-22T20:30:00Z",
        }

        snapshot_id = automation.snapshot_id_for_match(match, competition="worldcup_2026")

        self.assertEqual(snapshot_id, "worldcup_2026_france_vs_iraq_20260622T203000Z")

    def test_tick_skips_existing_imported_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kg_path = _write_kg(root)
            out_root = root / "out"
            now = datetime(2026, 6, 22, 20, 25, tzinfo=timezone.utc)
            match = automation.select_due_matches(
                kg_path=kg_path,
                now=now,
                lead_minutes=30,
                lookahead_minutes=10,
                grace_minutes=0,
                limit=10,
            )[0]
            snapshot_id = automation.snapshot_id_for_match(match, competition="worldcup_2026")
            automation.write_marker(out_root, snapshot_id, {"status": "imported", "snapshot_id": snapshot_id})
            args = _args(root=root, kg_path=kg_path, out_root=out_root, skip_supabase_import=True)

            with patch.object(automation, "collect_match", side_effect=AssertionError("should not collect")):
                payload = automation.run_tick(args, now=now)

        self.assertEqual(payload["rows"][0]["status"], "skipped")
        self.assertEqual(payload["rows"][0]["action"], "already_done")

    def test_dry_run_does_not_collect_or_probe_supabase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kg_path = _write_kg(root)
            args = _args(root=root, kg_path=kg_path, out_root=root / "out", dry_run=True)
            now = datetime(2026, 6, 22, 20, 25, tzinfo=timezone.utc)

            with (
                patch.object(automation, "collect_match", side_effect=AssertionError("should not collect")),
                patch.object(automation, "snapshot_exists_in_supabase", side_effect=AssertionError("should not probe")),
            ):
                payload = automation.run_tick(args, now=now)

        self.assertEqual(payload["rows"][0]["status"], "dry_run")
        self.assertEqual(payload["rows"][0]["action"], "would_collect")


def _args(
    *,
    root: Path,
    kg_path: Path,
    out_root: Path,
    dry_run: bool = False,
    skip_supabase_import: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        kg=kg_path,
        env_file=root / "missing.env",
        out_root=out_root,
        competition="worldcup_2026",
        lead_minutes=30.0,
        lookahead_minutes=10.0,
        grace_minutes=0.0,
        stale_lock_minutes=90.0,
        limit=10,
        window_days=21,
        max_records=30,
        x_max_queries=11,
        polymarket_timeout=30,
        polymarket_raw_clob_limit=12,
        import_timeout=180,
        skip_google_news=False,
        skip_gdelt=False,
        skip_scrapecreators_x=False,
        skip_polymarket=False,
        skip_supabase_import=skip_supabase_import,
        keep_existing=False,
        force=False,
        dry_run=dry_run,
    )


def _write_kg(root: Path) -> Path:
    kg_path = root / "world_cup_kg.json"
    kg_path.write_text(
        json.dumps(
            {
                "entities": [
                    _match("match:france_iraq", "France vs Iraq", "France", "Iraq", "2026-06-22", "21:00 UTC+0"),
                    _match("match:norway_senegal", "Norway vs Senegal", "Norway", "Senegal", "2026-06-22", "22:00 UTC+0"),
                    _match("match:past", "Past vs Done", "Past", "Done", "2026-06-22", "20:00 UTC+0"),
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return kg_path


def _match(entity_id: str, name: str, home: str, away: str, date: str, time: str) -> dict:
    return {
        "entity_id": entity_id,
        "entity_type": "match",
        "name": name,
        "attributes": {
            "team1": home,
            "team2": away,
            "date": date,
            "time": time,
            "round": "Matchday",
            "group": "Group I",
            "ground": "Test Stadium",
        },
    }


if __name__ == "__main__":
    unittest.main()
