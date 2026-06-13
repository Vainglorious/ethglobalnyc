"""Console formatting helpers for Colony CLI runs."""

from __future__ import annotations

from .models import DebateClaim, RoundResult


def print_final_feed(result: RoundResult) -> None:
    print("\nDebate feed:")
    for claim in result.claims:
        print(_claim_line(claim))


def print_debate_quality(result: RoundResult) -> None:
    summary = result.summary
    print(
        "Debate quality: "
        f"disputes={summary.get('dispute_count', 0)} "
        f"rate={float(summary.get('dispute_rate', 0.0)):.0%} "
        f"subjects={summary.get('subject_count', 0)} "
        f"critique_types={summary.get('critique_type_count', 0)} "
        f"subject_shifts={summary.get('subject_shift_count', 0)} "
        f"carried_claims={summary.get('carried_claim_count', 0)}"
    )


def print_room_debug(result: RoundResult, *, max_claim_chars: int = 220) -> None:
    if not result.rooms:
        return

    print("\nRoom debate debug:")
    for room in result.rooms:
        probability = (
            "n/a"
            if room.synthesis_home_probability is None
            else f"{room.synthesis_home_probability:.1%}"
        )
        print(
            f"- {room.room_id} topic={room.evidence_focus} "
            f"participants={len(room.participant_ids)} "
            f"representatives={len(room.representative_ids)} "
            f"home={probability}"
        )
        for claim in room.claims:
            message = _shorten(claim.message, max_claim_chars)
            dispute = ""
            if claim.dispute:
                critique = str(claim.dispute.get("critique_type") or "dispute").replace("_", "-")
                target = str(claim.dispute.get("target_speaker_name") or "previous")
                dispute = f" -> {critique} on {target}"
            print(
                f"  - {claim.speaker_name} [{claim.debate_role}/{claim.access_tier}] "
                f"{claim.stated_home_probability:.1%}: {message}{dispute}"
            )


def _claim_line(claim: DebateClaim) -> str:
    tags = ", ".join(claim.evidence_tags) if claim.evidence_tags else "no dominant source"
    return (
        f"- [{claim.model} | {claim.access_tier}/{claim.visible_findings} | "
        f"{claim.claim_type} | {tags}] {claim.message}"
    )


def _shorten(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    clipped = cleaned[: limit - 3].rstrip(" .")
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0].rstrip(" .")
    return f"{clipped}..."
