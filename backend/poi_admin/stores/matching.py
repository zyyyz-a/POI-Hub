"""Transparent store-to-POI candidate scoring."""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass(frozen=True, slots=True)
class MatchInput:
    name: str
    address: str
    latitude: float | None = None
    longitude: float | None = None


@dataclass(frozen=True, slots=True)
class CandidateScore:
    total: float
    name: float
    address: float
    distance: float
    distance_meters: float | None

    def evidence(self) -> dict[str, float | None]:
        return {
            "name_score": self.name,
            "address_score": self.address,
            "distance_score": self.distance,
            "distance_meters": self.distance_meters,
        }


def normalize_text(value: str) -> str:
    """Normalize full-width forms, case, whitespace, and punctuation."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _similarity(left: str, right: str) -> float:
    normalized_left = normalize_text(left)
    normalized_right = normalize_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    return SequenceMatcher(None, normalized_left, normalized_right, autojunk=False).ratio()


def _distance_meters(left: MatchInput, right: MatchInput) -> float | None:
    if None in (left.latitude, left.longitude, right.latitude, right.longitude):
        return None
    assert left.latitude is not None
    assert left.longitude is not None
    assert right.latitude is not None
    assert right.longitude is not None
    radius = 6_371_000.0
    latitude_delta = math.radians(right.latitude - left.latitude)
    longitude_delta = math.radians(right.longitude - left.longitude)
    left_latitude = math.radians(left.latitude)
    right_latitude = math.radians(right.latitude)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(left_latitude)
        * math.cos(right_latitude)
        * math.sin(longitude_delta / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def score_candidate(store: MatchInput, poi: MatchInput) -> CandidateScore:
    """Score a suggestion without making any mapping decision."""

    name_score = _similarity(store.name, poi.name)
    address_score = _similarity(store.address, poi.address)
    distance_meters = _distance_meters(store, poi)
    distance_score = (
        0.5 if distance_meters is None else max(0.0, 1.0 - distance_meters / 2_000.0)
    )
    total = 0.45 * name_score + 0.35 * address_score + 0.20 * distance_score
    return CandidateScore(
        total=round(total, 6),
        name=round(name_score, 6),
        address=round(address_score, 6),
        distance=round(distance_score, 6),
        distance_meters=None if distance_meters is None else round(distance_meters, 3),
    )


__all__ = ["CandidateScore", "MatchInput", "normalize_text", "score_candidate"]
