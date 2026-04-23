from core.fsm.guards import build_default_guard_registry


def test_default_guards_behave_as_expected() -> None:
    guards = build_default_guard_registry()

    assert guards["always"]({}) is True
    assert guards["has_phone_number"]({"phone": "5214421234567"}) is True
    assert guards["has_phone_number"]({}) is False
    assert guards["is_not_silenced"]({"is_silenced": False}) is True
    assert guards["is_not_silenced"]({"is_silenced": True}) is False
    assert guards["opt_out_detected"]({"opt_out_detected": True}) is True
    assert guards["opt_out_detected"]({}) is False
    assert guards["has_name"]({"name": "Estefania"}) is True
    assert guards["has_name"]({}) is False


def test_user_requested_document_guard() -> None:
    guards = build_default_guard_registry()
    guard = guards["user_requested_document"]

    assert guard({"inbound_text": "mándame la ficha"}) is True
    assert guard({"inbound_text": "quiero el PDF de la unidad"}) is True
    assert guard({"inbound_text": "me puedes enviar el documento"}) is True
    assert guard({"inbound_text": "necesito la ficha técnica"}) is True
    assert guard({"inbound_text": "dame la corrida"}) is True
    assert guard({"inbound_text": "cuales son las especificaciones"}) is True
    assert guard({"inbound_text": "ok"}) is False
    assert guard({"inbound_text": "Hola"}) is False
    assert guard({"inbound_text": "tienes camiones?"}) is False
    assert guard({"inbound_text": ""}) is False
    assert guard({}) is False
