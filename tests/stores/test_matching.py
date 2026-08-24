from __future__ import annotations

from poi_admin.stores.matching import MatchInput, normalize_text, score_candidate


def test_exact_name_and_nearby_address_are_high_confidence() -> None:
    store = MatchInput(
        name="西湖门店",
        address="杭州市西湖区孤山路1号",
        latitude=30.2500,
        longitude=120.1600,
    )
    poi = MatchInput(
        name="西湖门店",
        address="浙江省杭州市西湖区孤山路1号",
        latitude=30.2501,
        longitude=120.1601,
    )

    score = score_candidate(store, poi)

    assert score.total >= 0.9
    assert score.name == 1.0
    assert score.distance_meters is not None
    assert score.distance_meters < 20


def test_matching_is_normalized_and_exposes_component_scores() -> None:
    store = MatchInput("湖滨店（旗舰店）", "湖滨路 2 号", 30.25, 120.17)
    poi = MatchInput("湖滨店(旗舰店)", "湖滨路2号", 31.25, 121.17)

    score = score_candidate(store, poi)

    assert normalize_text(store.name) == normalize_text(poi.name)
    assert score.name == 1.0
    assert score.address == 1.0
    assert score.distance < 0.1
    assert 0 <= score.total <= 1
