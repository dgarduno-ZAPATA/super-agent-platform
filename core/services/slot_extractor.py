from __future__ import annotations

import re
import unicodedata

from core.domain.slots import LeadSlots, SlotExtractionResult


class SlotExtractor:
    _GENERIC_NAME_WORDS = {
        "hola",
        "buenas",
        "gracias",
        "claro",
        "perfecto",
        "si",
        "sí",
        "no",
        "ok",
        "oye",
        "eso",
        "bien",
    }

    _CITY_BLOCKLIST = {
        "mexico",
        "aqui",
        "alli",
        "alla",
        "ahi",
        "casa",
        "oficina",
        "trabajo",
        "carretera",
    }

    _VEHICLE_KEYWORDS = {
        "camion",
        "tractocamion",
        "volteo",
        "pipa",
        "rabon",
        "torton",
        "trailer",
        "remolque",
        "caja",
        "plataforma",
        "grua",
        "freightliner",
        "international",
        "kenworth",
        "peterbilt",
        "cascadia",
        "prostar",
        "durastar",
        "lonestar",
    }

    def extract(self, text: str, existing: LeadSlots) -> SlotExtractionResult:
        raw_text = text or ""

        name, name_match = self._extract_name(raw_text)
        phone, phone_match = self._extract_phone(raw_text)
        city, city_match = self._extract_city(raw_text)
        vehicle_interest, vehicle_match = self._extract_vehicle_interest(raw_text)
        budget, budget_match = self._extract_budget(raw_text)
        contact_preference, contact_match = self._extract_contact_preference(raw_text)

        merged_slots = LeadSlots(
            name=name if name is not None else existing.name,
            city=city if city is not None else existing.city,
            vehicle_interest=(
                vehicle_interest if vehicle_interest is not None else existing.vehicle_interest
            ),
            budget=budget if budget is not None else existing.budget,
            phone=phone if phone is not None else existing.phone,
            contact_preference=(
                contact_preference
                if contact_preference is not None
                else existing.contact_preference
            ),
        )

        raw_matches: dict[str, str] = {}
        if name_match is not None:
            raw_matches["name"] = name_match
        if phone_match is not None:
            raw_matches["phone"] = phone_match
        if city_match is not None:
            raw_matches["city"] = city_match
        if vehicle_match is not None:
            raw_matches["vehicle_interest"] = vehicle_match
        if budget_match is not None:
            raw_matches["budget"] = budget_match
        if contact_match is not None:
            raw_matches["contact_preference"] = contact_match

        extraction_method = "regex" if raw_matches else "none"
        return SlotExtractionResult(
            slots=merged_slots,
            extraction_method=extraction_method,
            raw_matches=raw_matches,
        )

    def _extract_name(self, text: str) -> tuple[str | None, str | None]:
        patterns = [
            r"\bme\s+llamo\s+(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})",
            r"\bmi\s+nombre\s+es\s+(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})",
            r"\ble\s+habla\s+(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})",
            r"\bhabla\s+(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})",
            r"\bme\s+puede\s+llamar\s+(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})",
            r"\bpuedes\s+llamarme\s+(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})",
            r"\bsoy\s+(?!de\b)(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            raw_name = (match.group("name") or "").strip(" .,!?:;\t\n\r")
            raw_name = " ".join(raw_name.split())
            if not raw_name:
                continue
            normalized = self._normalize_text(raw_name)
            if normalized in self._GENERIC_NAME_WORDS:
                return None, None
            if re.search(r"\d", raw_name):
                return None, None
            if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{2,40}", raw_name):
                return None, None
            return raw_name, match.group(0).strip()
        return None, None

    def _extract_phone(self, text: str) -> tuple[str | None, str | None]:
        for match in re.finditer(r"\+?\d[\d\s\-]{8,20}\d", text):
            raw = match.group(0).strip()
            digits = re.sub(r"\D", "", raw)
            if len(digits) == 12 and digits.startswith("52"):
                digits = digits[2:]
            if len(digits) == 10 and digits[0] in "123456789":
                return digits, raw
        return None, None

    def _extract_city(self, text: str) -> tuple[str | None, str | None]:
        anchored_patterns = [
            r"^\s*(?:en|de)\s+(?P<city>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{3,40})\s*$",
            r"\b(?:soy de|estoy en|trabajo en|estamos en|ubicados en|somos de)\s+"
            r"(?P<city>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{3,40}?)(?=$|[,.!?;]|\s+y\s)",
        ]
        for pattern in anchored_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            city = " ".join((match.group("city") or "").strip().split())
            if not city:
                continue
            if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ ]{3,40}", city):
                continue
            normalized = self._normalize_text(city)
            if normalized in self._CITY_BLOCKLIST:
                return None, None
            return city, match.group(0).strip()
        return None, None

    def _extract_vehicle_interest(self, text: str) -> tuple[str | None, str | None]:
        trigger_pattern = (
            r"\b(?:busco|quiero|necesito|me interesa|tengo interes en|"
            r"tengo interés en|estoy buscando|que tienen de|qué tienen de)\s+"
            r"(?P<interest>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9 ]{1,80}?)(?=$|[,.!?;])"
        )
        match = re.search(trigger_pattern, text, flags=re.IGNORECASE)
        if not match:
            return None, None

        interest = " ".join((match.group("interest") or "").strip().split())
        if not interest:
            return None, None

        normalized = self._normalize_text(interest)
        normalized = re.sub(r"^(un|una|uno|la|el|los|las)\s+", "", normalized).strip()
        if not normalized:
            return None, None

        has_keyword = any(keyword in normalized for keyword in self._VEHICLE_KEYWORDS)
        if not has_keyword:
            return None, None

        return normalized, match.group(0).strip()

    def _extract_budget(self, text: str) -> tuple[float | None, str | None]:
        normalized_text = self._normalize_text(text)

        range_match = re.search(
            r"entre\s+(\d+(?:[.,]\d+)?)\s+y\s+(\d+(?:[.,]\d+)?)\s+"
            r"(millones?|millon|mdp|mil|pesos)",
            normalized_text,
        )
        if range_match:
            first_value = self._amount_from_number_and_unit(
                range_match.group(1), range_match.group(3)
            )
            second_value = self._amount_from_number_and_unit(
                range_match.group(2), range_match.group(3)
            )
            if first_value is not None and second_value is not None:
                return (first_value + second_value) / 2.0, range_match.group(0)

        compound_match = re.search(
            r"(?:un|uno|1)\s+millon(?:es)?\s+(\d+(?:[.,]\d+)?)\s+mil",
            normalized_text,
        )
        if compound_match:
            thousands = self._parse_number(compound_match.group(1))
            if thousands is not None:
                return 1_000_000.0 + (thousands * 1_000.0), compound_match.group(0)

        amount_match = re.search(
            r"(\d+(?:[.,]\d+)?)\s*(millones?|millon|mdp|mil|pesos)",
            normalized_text,
        )
        if amount_match:
            amount = self._amount_from_number_and_unit(amount_match.group(1), amount_match.group(2))
            if amount is not None:
                return amount, amount_match.group(0)

        grouped_number_match = re.search(r"\b\d{1,3}(?:[.,]\d{3})+\b", normalized_text)
        if grouped_number_match:
            parsed = self._parse_number(grouped_number_match.group(0))
            if parsed is not None:
                return float(parsed), grouped_number_match.group(0)

        return None, None

    def _extract_contact_preference(self, text: str) -> tuple[str | None, str | None]:
        normalized_text = self._normalize_text(text)

        whatsapp_match = re.search(r"\bpor\s+whatsapp\b", normalized_text)
        if whatsapp_match:
            return "whatsapp", whatsapp_match.group(0)

        call_match = re.search(r"\b(llamame|marcame|prefiero\s+llamada)\b", normalized_text)
        if call_match:
            return "llamada", call_match.group(0)

        message_match = re.search(
            r"\b(mandame\s+mensaje|prefiero\s+mensaje|mejor\s+por\s+escrito)\b",
            normalized_text,
        )
        if message_match:
            return "mensaje", message_match.group(0)

        return None, None

    def _amount_from_number_and_unit(self, value: str, unit: str) -> float | None:
        numeric_value = self._parse_number(value)
        if numeric_value is None:
            return None

        normalized_unit = self._normalize_text(unit)
        if normalized_unit in {"millon", "millones", "mdp"}:
            return numeric_value * 1_000_000.0
        if normalized_unit == "mil":
            return numeric_value * 1_000.0
        if normalized_unit == "pesos":
            return numeric_value
        return None

    @staticmethod
    def _parse_number(raw: str) -> float | None:
        value = raw.strip()
        if not value:
            return None

        if "," in value and "." in value:
            if value.rfind(".") > value.rfind(","):
                candidate = value.replace(",", "")
            else:
                candidate = value.replace(".", "").replace(",", ".")
        elif "," in value:
            parts = value.split(",")
            if len(parts) > 1 and all(part.isdigit() and len(part) == 3 for part in parts[1:]):
                candidate = "".join(parts)
            else:
                candidate = value.replace(",", ".")
        elif "." in value:
            parts = value.split(".")
            if len(parts) > 1 and all(part.isdigit() and len(part) == 3 for part in parts[1:]):
                candidate = "".join(parts)
            else:
                candidate = value
        else:
            candidate = value

        try:
            return float(candidate)
        except ValueError:
            return None

    @staticmethod
    def _normalize_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
        lowered = without_accents.casefold()
        return re.sub(r"\s+", " ", lowered).strip()


def slots_to_legacy_dict(slots: LeadSlots) -> dict[str, object]:
    """
    Convierte LeadSlots al dict de claves legacy que consume
    el flujo actual (inbound_handler, guards FSM, CRM worker).
    Solo incluye claves con valor no-None.
    """
    result: dict[str, object] = {}
    if slots.name is not None:
        result["name"] = slots.name
    if slots.vehicle_interest is not None:
        result["vehicle_interest"] = slots.vehicle_interest
        result["vehiculo_interes"] = slots.vehicle_interest
    if slots.city is not None:
        result["city"] = slots.city
        result["ciudad"] = slots.city
    if slots.budget is not None:
        result["budget"] = slots.budget
    if slots.phone is not None:
        result["phone"] = slots.phone
    if slots.contact_preference is not None:
        result["contact_preference"] = slots.contact_preference
    return result
