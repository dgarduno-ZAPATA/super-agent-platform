from __future__ import annotations

from core.services.handoff_service import _build_advisor_alert


def test_alert_contains_name() -> None:
    msg = _build_advisor_alert("Diego", "5214461051272", "volteo", None, None)
    assert "Diego" in msg


def test_alert_contains_wa_link() -> None:
    msg = _build_advisor_alert(None, "+52 446 105 1272", None, None, None)
    assert "wa.me/524461051272" in msg


def test_alert_unknown_name_uses_prospecto() -> None:
    msg = _build_advisor_alert(None, "5214461051272", None, None, None)
    assert "Prospecto" in msg


def test_urgency_alta_with_budget() -> None:
    msg = _build_advisor_alert("Ana", "5214461051272", "tractocamion", None, 1_500_000.0)
    assert "🔴 Alta" in msg


def test_urgency_alta_with_city() -> None:
    msg = _build_advisor_alert("Ana", "5214461051272", None, "Guadalajara", None)
    assert "🔴 Alta" in msg


def test_urgency_media_with_vehicle_only() -> None:
    msg = _build_advisor_alert(None, "5214461051272", "volteo", None, None)
    assert "🟡 Media" in msg


def test_urgency_normal_no_data() -> None:
    msg = _build_advisor_alert(None, "5214461051272", None, None, None)
    assert "🟢 Normal" in msg


def test_city_appears_when_provided() -> None:
    msg = _build_advisor_alert(None, "5214461051272", None, "Monterrey", None)
    assert "Monterrey" in msg


def test_city_absent_when_not_provided() -> None:
    msg = _build_advisor_alert(None, "5214461051272", None, None, None)
    assert "Ciudad:" not in msg


def test_phone_digits_only_in_link() -> None:
    msg = _build_advisor_alert(None, "+52-446-105-1272", None, None, None)
    assert "wa.me/524461051272" in msg
