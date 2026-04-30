from __future__ import annotations

from adapters.messaging.evolution.outbound_cache import (
    _CACHE_MAX_SIZE,
    OutboundMessageCache,
)


async def test_add_and_contains() -> None:
    cache = OutboundMessageCache()
    await cache.add("msg-001")
    assert await cache.contains("msg-001") is True


async def test_not_contains_unknown() -> None:
    cache = OutboundMessageCache()
    assert await cache.contains("msg-unknown") is False


async def test_add_multiple() -> None:
    cache = OutboundMessageCache()
    for i in range(10):
        await cache.add(f"msg-{i:03d}")
    assert await cache.size() == 10
    assert await cache.contains("msg-005") is True


async def test_contains_returns_false_after_eviction() -> None:
    cache = OutboundMessageCache()
    await cache.add("msg-old")
    cache._cache["msg-old"] = 0.0
    assert await cache.contains("msg-old") is False


async def test_size_within_max() -> None:
    cache = OutboundMessageCache()
    for i in range(_CACHE_MAX_SIZE + 10):
        await cache.add(f"msg-{i:06d}")
    assert await cache.size() <= _CACHE_MAX_SIZE
