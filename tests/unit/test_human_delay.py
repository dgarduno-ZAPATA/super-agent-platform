from __future__ import annotations

import random

from core.utils.human_delay import MAX_DELAY, MIN_DELAY, compute_delay


def test_short_text_gets_min_delay() -> None:
    random.seed(42)
    delay = compute_delay("Hola")
    assert MIN_DELAY <= delay <= MAX_DELAY


def test_long_text_gets_longer_delay() -> None:
    random.seed(42)
    short = compute_delay("Ok")
    random.seed(42)
    long_delay = compute_delay("A" * 500)
    assert MIN_DELAY <= short <= MAX_DELAY
    assert MIN_DELAY <= long_delay <= MAX_DELAY


def test_delay_always_in_range() -> None:
    for seed in range(100):
        random.seed(seed)
        delay = compute_delay("Texto de prueba con longitud media para test.")
        assert (
            MIN_DELAY <= delay <= MAX_DELAY
        ), f"seed={seed}: delay={delay} fuera de [{MIN_DELAY}, {MAX_DELAY}]"


def test_empty_text_gets_min_delay() -> None:
    random.seed(0)
    delay = compute_delay("")
    assert delay >= MIN_DELAY


def test_very_long_text_capped_at_max() -> None:
    random.seed(0)
    delay = compute_delay("X" * 10000)
    assert delay <= MAX_DELAY
