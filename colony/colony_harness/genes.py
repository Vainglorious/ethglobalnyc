"""Genome definitions for Colony agents."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass
from typing import Literal


Estimator = Literal["poisson", "llm"]
ModelSpecies = Literal[
    "deepseek-v3.2",
    "qwen-3",
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "claude-haiku",
    "parametric",
]

LLM_MODEL_SPECIES: list[ModelSpecies] = [
    "deepseek-v3.2",
    "qwen-3",
    "MiniMax-M3",
    "MiniMax-M2.7",
    "MiniMax-M2.7-highspeed",
    "claude-haiku",
]


PERSONA_TRAITS = [
    "cold probabilist",
    "market contrarian",
    "news-sensitive scout",
    "risk-on striker",
    "defensive skeptic",
    "crowd watcher",
    "model maximalist",
    "quiet value hunter",
]


@dataclass(frozen=True)
class SourceWeights:
    stats: float
    odds: float
    news: float
    debate: float

    def normalized(self) -> "SourceWeights":
        total = max(self.stats + self.odds + self.news + self.debate, 1e-9)
        return SourceWeights(
            stats=self.stats / total,
            odds=self.odds / total,
            news=self.news / total,
            debate=self.debate / total,
        )

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SourceWeights":
        return cls(
            stats=float(data["stats"]),
            odds=float(data["odds"]),
            news=float(data["news"]),
            debate=float(data["debate"]),
        )


@dataclass(frozen=True)
class Genome:
    estimator: Estimator
    model: ModelSpecies
    risk_appetite: float
    edge_threshold: float
    source_weights: SourceWeights
    herd_bias: float
    query_budget: float
    persona: str

    def stable_id(self) -> str:
        return f"genome_{self.public_hash()[:16]}"

    def public_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["source_weights"] = self.source_weights.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Genome":
        return cls(
            estimator=data["estimator"],
            model=data["model"],
            risk_appetite=float(data["risk_appetite"]),
            edge_threshold=float(data["edge_threshold"]),
            source_weights=SourceWeights.from_dict(data["source_weights"]),
            herd_bias=float(data["herd_bias"]),
            query_budget=float(data["query_budget"]),
            persona=str(data["persona"]),
        )


def _random_weights(rng: random.Random) -> SourceWeights:
    raw = [rng.random() + 0.05 for _ in range(4)]
    total = sum(raw)
    return SourceWeights(
        stats=raw[0] / total,
        odds=raw[1] / total,
        news=raw[2] / total,
        debate=raw[3] / total,
    )


def random_genome(rng: random.Random, llm_probability: float = 0.18) -> Genome:
    estimator: Estimator = "llm" if rng.random() < llm_probability else "poisson"
    if estimator == "llm":
        model: ModelSpecies = rng.choice(LLM_MODEL_SPECIES)
    else:
        model = "parametric"

    return Genome(
        estimator=estimator,
        model=model,
        risk_appetite=round(rng.uniform(0.02, 0.18), 4),
        edge_threshold=round(rng.uniform(0.01, 0.18), 4),
        source_weights=_random_weights(rng).normalized(),
        herd_bias=round(rng.uniform(-1.0, 1.0), 4),
        query_budget=round(rng.uniform(0.1, 2.0), 4),
        persona=rng.choice(PERSONA_TRAITS),
    )


def mutate_genome(
    parent: Genome,
    rng: random.Random,
    *,
    mutation_rate: float = 0.18,
) -> Genome:
    """Create a nearby child genome for offline population evolution."""

    estimator = parent.estimator
    model = parent.model
    if rng.random() < mutation_rate * 0.35:
        estimator = "llm" if parent.estimator == "poisson" else "poisson"
    if estimator == "llm":
        if parent.estimator != "llm" or rng.random() < mutation_rate:
            model = rng.choice(LLM_MODEL_SPECIES)
    else:
        model = "parametric"

    persona = parent.persona
    if rng.random() < mutation_rate:
        persona = rng.choice(PERSONA_TRAITS)

    weights = parent.source_weights.normalized()
    mutated_weights = SourceWeights(
        stats=_mutate_positive(weights.stats, rng, mutation_rate=mutation_rate),
        odds=_mutate_positive(weights.odds, rng, mutation_rate=mutation_rate),
        news=_mutate_positive(weights.news, rng, mutation_rate=mutation_rate),
        debate=_mutate_positive(weights.debate, rng, mutation_rate=mutation_rate),
    ).normalized()

    return Genome(
        estimator=estimator,
        model=model,
        risk_appetite=round(_mutate_bounded(parent.risk_appetite, rng, 0.02, 0.2, mutation_rate), 4),
        edge_threshold=round(_mutate_bounded(parent.edge_threshold, rng, 0.005, 0.2, mutation_rate), 4),
        source_weights=mutated_weights,
        herd_bias=round(_mutate_bounded(parent.herd_bias, rng, -1.0, 1.0, mutation_rate), 4),
        query_budget=round(_mutate_bounded(parent.query_budget, rng, 0.05, 3.0, mutation_rate), 4),
        persona=persona,
    )


def _mutate_positive(value: float, rng: random.Random, *, mutation_rate: float) -> float:
    scale = 0.55 * mutation_rate
    return max(0.01, value * (1.0 + rng.uniform(-scale, scale)))


def _mutate_bounded(
    value: float,
    rng: random.Random,
    lower: float,
    upper: float,
    mutation_rate: float,
) -> float:
    span = upper - lower
    mutated = value + rng.uniform(-span * mutation_rate, span * mutation_rate)
    return min(max(mutated, lower), upper)
