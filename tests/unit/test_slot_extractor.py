from __future__ import annotations

import pytest

from core.domain.slots import LeadSlots
from core.services.slot_extractor import SlotExtractor, slots_to_legacy_dict


@pytest.fixture
def extractor() -> SlotExtractor:
    return SlotExtractor()


def test_name_me_llamo_diego(extractor: SlotExtractor) -> None:
    result = extractor.extract("me llamo Diego", LeadSlots())
    assert result.slots.name == "Diego"


def test_name_mi_nombre_es_ana_garcia(extractor: SlotExtractor) -> None:
    result = extractor.extract("mi nombre es Ana García", LeadSlots())
    assert result.slots.name == "Ana García"


def test_name_soy_juan(extractor: SlotExtractor) -> None:
    result = extractor.extract("soy Juan", LeadSlots())
    assert result.slots.name == "Juan"


def test_name_generic_word_is_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("me llamo hola", LeadSlots())
    assert result.slots.name is None


def test_name_gracias_is_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("gracias", LeadSlots())
    assert result.slots.name is None


def test_name_with_digits_is_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("me llamo 123", LeadSlots())
    assert result.slots.name is None


def test_phone_plain_10_digits(extractor: SlotExtractor) -> None:
    result = extractor.extract("mi número es 4461051272", LeadSlots())
    assert result.slots.phone == "4461051272"


def test_phone_with_plus_52(extractor: SlotExtractor) -> None:
    result = extractor.extract("+52 446 105 1272", LeadSlots())
    assert result.slots.phone == "4461051272"


def test_phone_with_52_and_hyphens(extractor: SlotExtractor) -> None:
    result = extractor.extract("llámame al 52-446-105-1272", LeadSlots())
    assert result.slots.phone == "4461051272"


def test_phone_non_phone_number_is_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("tengo 5 camiones", LeadSlots())
    assert result.slots.phone is None


def test_vehicle_interest_camion_volteo(extractor: SlotExtractor) -> None:
    result = extractor.extract("busco un camión de volteo", LeadSlots())
    assert result.slots.vehicle_interest == "camion de volteo"


def test_vehicle_interest_freightliner_cascadia(extractor: SlotExtractor) -> None:
    result = extractor.extract("necesito un Freightliner Cascadia", LeadSlots())
    assert result.slots.vehicle_interest == "freightliner cascadia"


def test_vehicle_interest_without_keyword_is_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("quiero algo para carga seca", LeadSlots())
    assert result.slots.vehicle_interest is None


def test_vehicle_interest_tractocamion(extractor: SlotExtractor) -> None:
    result = extractor.extract("me interesa un tractocamión", LeadSlots())
    assert result.slots.vehicle_interest == "tractocamion"


def test_vehicle_interest_busco_trabajo_is_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("busco trabajo", LeadSlots())
    assert result.slots.vehicle_interest is None


def test_budget_two_millones(extractor: SlotExtractor) -> None:
    result = extractor.extract("tengo 2 millones", LeadSlots())
    assert result.slots.budget == pytest.approx(2_000_000.0)


def test_budget_ochocientos_mil(extractor: SlotExtractor) -> None:
    result = extractor.extract("mi presupuesto es 800 mil", LeadSlots())
    assert result.slots.budget == pytest.approx(800_000.0)


def test_budget_between_one_and_two_millones(extractor: SlotExtractor) -> None:
    result = extractor.extract("entre 1 y 2 millones", LeadSlots())
    assert result.slots.budget == pytest.approx(1_500_000.0)


def test_budget_ambiguous_plain_number_is_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("tengo 1000", LeadSlots())
    assert result.slots.budget is None


def test_merge_keeps_existing_name_without_new_name(extractor: SlotExtractor) -> None:
    existing = LeadSlots(name="Diego")
    result = extractor.extract("busco volteo", existing)
    assert result.slots.name == "Diego"


def test_merge_overwrites_name_when_new_explicit_name(extractor: SlotExtractor) -> None:
    existing = LeadSlots(name="Diego")
    result = extractor.extract("me llamo Carlos", existing)
    assert result.slots.name == "Carlos"


def test_merge_keeps_existing_vehicle_interest_without_new_value(extractor: SlotExtractor) -> None:
    existing = LeadSlots(vehicle_interest="volteo")
    result = extractor.extract("gracias", existing)
    assert result.slots.vehicle_interest == "volteo"


def test_null_rule_ambiguous_text_returns_all_none(extractor: SlotExtractor) -> None:
    result = extractor.extract("ok, entendido", LeadSlots())
    assert result.slots == LeadSlots()


def test_null_rule_intent_without_explicit_slot(extractor: SlotExtractor) -> None:
    result = extractor.extract("quiero uno rojo", LeadSlots())
    assert result.slots.vehicle_interest is None


def test_slots_to_legacy_dict_vehicle_interest() -> None:
    slots = LeadSlots(vehicle_interest="volteo")
    legacy = slots_to_legacy_dict(slots)
    assert legacy["vehicle_interest"] == "volteo"
    assert legacy["vehiculo_interes"] == "volteo"


def test_slots_to_legacy_dict_city() -> None:
    slots = LeadSlots(city="Guadalajara")
    legacy = slots_to_legacy_dict(slots)
    assert legacy["city"] == "Guadalajara"
    assert legacy["ciudad"] == "Guadalajara"


def test_slots_to_legacy_dict_none_excluded() -> None:
    slots = LeadSlots()
    legacy = slots_to_legacy_dict(slots)
    assert len(legacy) == 0
