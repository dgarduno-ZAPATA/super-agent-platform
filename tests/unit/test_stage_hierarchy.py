from adapters.crm.monday_adapter import _can_advance_stage

HIERARCHY = [
    "Nuevo",
    "Conversando",
    "Calificando",
    "Listo para Handoff",
    "Handoff Hecho",
]
TERMINAL = ["Handoff Hecho"]
SPECIAL: list[str] = []


def test_advance_allowed() -> None:
    assert (
        _can_advance_stage(
            "Conversando",
            "Calificando",
            HIERARCHY,
            TERMINAL,
            SPECIAL,
        )
        is True
    )


def test_retreat_blocked() -> None:
    assert (
        _can_advance_stage(
            "Calificando",
            "Conversando",
            HIERARCHY,
            TERMINAL,
            SPECIAL,
        )
        is False
    )


def test_special_stage_always_allowed() -> None:
    # Special is empty in production today; this test validates logic with a synthetic special.
    special = ["Sin Interes"]
    assert (
        _can_advance_stage(
            "Calificando",
            "Sin Interes",
            HIERARCHY,
            TERMINAL,
            special,
        )
        is True
    )


def test_reopen_from_terminal() -> None:
    assert (
        _can_advance_stage(
            "Handoff Hecho",
            "Conversando",
            HIERARCHY,
            TERMINAL,
            SPECIAL,
        )
        is True
    )


def test_reopen_from_non_terminal_blocked() -> None:
    assert (
        _can_advance_stage(
            "Calificando",
            "Conversando",
            HIERARCHY,
            TERMINAL,
            SPECIAL,
        )
        is False
    )


def test_unknown_new_stage_allowed() -> None:
    assert (
        _can_advance_stage(
            "Conversando",
            "Etapa Nueva",
            HIERARCHY,
            TERMINAL,
            SPECIAL,
        )
        is True
    )


def test_same_stage_blocked() -> None:
    assert (
        _can_advance_stage(
            "Calificando",
            "Calificando",
            HIERARCHY,
            TERMINAL,
            SPECIAL,
        )
        is False
    )
