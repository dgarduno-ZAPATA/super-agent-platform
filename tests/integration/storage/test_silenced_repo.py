from __future__ import annotations

from adapters.storage.repositories.silenced_repo import PostgresSilencedUserRepository
from tests.integration.storage.conftest import run_async


def test_silenced_repo_silence_check_and_unsilence(clean_silenced_tables: None) -> None:
    repo = PostgresSilencedUserRepository()
    phone = "5214421234503"

    run_async(repo.silence(phone=phone, reason="opt_out", silenced_by="test-suite"))
    is_silenced = run_async(repo.is_silenced(phone))

    assert is_silenced is True

    run_async(repo.unsilence(phone))
    still_silenced = run_async(repo.is_silenced(phone))

    assert still_silenced is False
