"""Product colony config helpers.

These helpers translate the user-owned colony config stored in Supabase into
the existing Genome fields used by the harness. The config is intentionally
small for v1: a preset, population size, model preference, persona mix, KG
focus, and risk profile.
"""

from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path
from typing import Any

from .genes import LLM_MODEL_SPECIES, PERSONA_TRAITS, Genome, ModelSpecies, SourceWeights


CONFIG_SCHEMA_VERSION = 1
ALLOWED_ANT_COUNTS = {50, 100, 200}
ALLOWED_PRESETS = {"market", "scout", "quant"}
ALLOWED_RISK_PROFILES = {"cautious", "balanced", "aggressive"}
MODEL_SPECIES = set(LLM_MODEL_SPECIES) | {"parametric", "mixed"}

PRESET_DEFAULTS: dict[str, dict[str, Any]] = {
    "market": {
        "source_weights": {"stats": 0.16, "odds": 0.52, "news": 0.12, "debate": 0.20},
        "personality_mix": ["market contrarian", "crowd watcher", "quiet value hunter"],
        "model_preference": "parametric",
        "risk_profile": "balanced",
        "kg_focus": ["odds", "market_context", "sentiment"],
    },
    "scout": {
        "source_weights": {"stats": 0.20, "odds": 0.14, "news": 0.46, "debate": 0.20},
        "personality_mix": ["news-sensitive scout", "defensive skeptic", "quiet value hunter"],
        "model_preference": "deepseek-v3.2",
        "risk_profile": "cautious",
        "kg_focus": ["news", "players", "availability"],
    },
    "quant": {
        "source_weights": {"stats": 0.54, "odds": 0.26, "news": 0.06, "debate": 0.14},
        "personality_mix": ["cold probabilist", "model maximalist", "defensive skeptic"],
        "model_preference": "parametric",
        "risk_profile": "balanced",
        "kg_focus": ["stats", "odds", "form"],
    },
}

RISK_SETTINGS = {
    "cautious": {"risk_appetite": (0.018, 0.060), "edge_threshold": (0.100, 0.180), "query_budget": (0.35, 0.85)},
    "balanced": {"risk_appetite": (0.060, 0.130), "edge_threshold": (0.040, 0.105), "query_budget": (0.75, 1.50)},
    "aggressive": {"risk_appetite": (0.140, 0.260), "edge_threshold": (0.006, 0.045), "query_budget": (1.40, 2.80)},
}


def load_colony_config(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("config"), dict):
        payload = payload["config"]
    if not isinstance(payload, dict):
        raise ValueError(f"Colony config must be a JSON object: {source}")
    return normalize_colony_config(payload)


def normalize_colony_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(raw or {})
    preset = str(data.get("preset") or "market").strip().lower()
    if preset not in ALLOWED_PRESETS:
        raise ValueError(f"Unsupported colony preset: {preset}")
    defaults = PRESET_DEFAULTS[preset]

    ant_count = int(data.get("ant_count") or data.get("agents") or 50)
    if ant_count not in ALLOWED_ANT_COUNTS:
        raise ValueError(f"ant_count must be one of {sorted(ALLOWED_ANT_COUNTS)}")

    model_preference = str(data.get("model_preference") or defaults["model_preference"]).strip()
    if model_preference not in MODEL_SPECIES:
        raise ValueError(f"Unsupported model_preference: {model_preference}")

    risk_profile = str(data.get("risk_profile") or defaults["risk_profile"]).strip().lower()
    if risk_profile not in ALLOWED_RISK_PROFILES:
        raise ValueError(f"Unsupported risk_profile: {risk_profile}")

    personality_mix = _string_list(data.get("personality_mix") or defaults["personality_mix"])
    if not personality_mix:
        personality_mix = list(defaults["personality_mix"])
    invalid_personas = [persona for persona in personality_mix if persona not in PERSONA_TRAITS]
    if invalid_personas:
        raise ValueError(f"Unsupported personality_mix values: {', '.join(invalid_personas)}")

    kg_focus = _string_list(data.get("kg_focus") or defaults["kg_focus"])
    source_weights = _weights_from_dict(data.get("source_weights") or defaults["source_weights"]).normalized()

    return {
        "preset": preset,
        "ant_count": ant_count,
        "model_preference": model_preference,
        "personality_mix": personality_mix,
        "kg_focus": kg_focus,
        "risk_profile": risk_profile,
        "source_weights": source_weights.to_dict(),
    }


def ant_count_from_config(config: dict[str, Any] | None, fallback: int) -> int:
    if not config:
        return fallback
    return int(normalize_colony_config(config)["ant_count"])


def describe_colony_config(config: dict[str, Any] | None) -> str:
    if not config:
        return "none"
    normalized = normalize_colony_config(config)
    return (
        f"preset={normalized['preset']} "
        f"ants={normalized['ant_count']} "
        f"risk={normalized['risk_profile']} "
        f"model={normalized['model_preference']} "
        f"personas={','.join(normalized['personality_mix'])} "
        f"kg_focus={','.join(normalized['kg_focus'])}"
    )


def apply_colony_config_to_genome(
    genome: Genome,
    config: dict[str, Any] | None,
    rng: random.Random,
    *,
    index: int,
) -> Genome:
    if not config:
        return genome
    normalized = normalize_colony_config(config)
    risk = RISK_SETTINGS[normalized["risk_profile"]]
    model = _model_for_ant(normalized["model_preference"], rng)
    estimator = "poisson" if model == "parametric" else "llm"
    persona_mix = normalized["personality_mix"]
    persona = persona_mix[index % len(persona_mix)]
    source_weights = _jitter_weights(_weights_from_dict(normalized["source_weights"]), rng).normalized()

    return replace(
        genome,
        estimator=estimator,
        model=model,
        risk_appetite=round(_range_value(risk["risk_appetite"], rng), 4),
        edge_threshold=round(_range_value(risk["edge_threshold"], rng), 4),
        query_budget=round(_range_value(risk["query_budget"], rng), 4),
        source_weights=source_weights,
        persona=persona,
    )


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    raise ValueError("Expected a string list")


def _weights_from_dict(value: Any) -> SourceWeights:
    data = dict(value or {})
    return SourceWeights(
        stats=float(data.get("stats", 0.25)),
        odds=float(data.get("odds", 0.25)),
        news=float(data.get("news", 0.25)),
        debate=float(data.get("debate", 0.25)),
    )


def _jitter_weights(weights: SourceWeights, rng: random.Random) -> SourceWeights:
    def j(value: float) -> float:
        return max(0.01, value * rng.uniform(0.88, 1.12))

    return SourceWeights(
        stats=j(weights.stats),
        odds=j(weights.odds),
        news=j(weights.news),
        debate=j(weights.debate),
    )


def _model_for_ant(preference: str, rng: random.Random) -> ModelSpecies:
    if preference == "mixed":
        return rng.choice(["parametric", *LLM_MODEL_SPECIES])
    return preference  # type: ignore[return-value]


def _range_value(bounds: tuple[float, float], rng: random.Random) -> float:
    low, high = bounds
    return rng.uniform(low, high)
