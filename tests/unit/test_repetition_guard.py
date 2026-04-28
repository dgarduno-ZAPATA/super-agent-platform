from __future__ import annotations

from core.services.repetition_guard import is_repetition, jaccard_similarity


def test_jaccard_identical() -> None:
    assert jaccard_similarity("hola cómo estás", "hola cómo estás") == 1.0


def test_jaccard_no_overlap() -> None:
    sim = jaccard_similarity("camión volteo rojo", "precio garantía crédito")
    assert sim == 0.0


def test_jaccard_partial() -> None:
    sim = jaccard_similarity("busco un camión de volteo", "tengo un camión disponible")
    assert 0.0 < sim < 1.0


def test_jaccard_empty_string() -> None:
    assert jaccard_similarity("", "algo de texto") == 0.0


def test_repetition_detected_above_threshold() -> None:
    prev = ["Tenemos varias opciones de camiones de volteo disponibles."]
    candidate = "Tenemos varias opciones de camiones de volteo disponibles hoy."
    assert is_repetition(candidate, prev) is True


def test_no_repetition_below_threshold() -> None:
    prev = ["Tenemos camiones disponibles."]
    candidate = "El precio depende del modelo y año de la unidad."
    assert is_repetition(candidate, prev) is False


def test_no_repetition_empty_history() -> None:
    assert is_repetition("cualquier respuesta", []) is False


def test_no_repetition_empty_candidate() -> None:
    assert is_repetition("", ["respuesta previa"]) is False


def test_lookback_only_last_3() -> None:
    old = "Tenemos camiones de volteo disponibles ahora mismo."
    prev = [old, "otro mensaje uno", "otro mensaje dos", "otro mensaje tres"]
    candidate = "Tenemos camiones de volteo disponibles ahora mismo."
    assert is_repetition(candidate, prev, lookback=3) is False


def test_custom_threshold() -> None:
    prev = ["Tenemos camiones disponibles en sucursal."]
    candidate = "Tenemos camiones disponibles en sucursal norte."
    assert is_repetition(candidate, prev, threshold=0.95) is False
    assert is_repetition(candidate, prev, threshold=0.5) is True
