from app.services.cache_service import CacheService, ttl_for


def test_cache_set_get_delete_roundtrip() -> None:
    cache = CacheService()
    key = cache.build_key("price", "AAPL")

    cache.set(key, {"price": 100}, ttl_seconds=60)
    assert cache.get(key) == {"price": 100}

    deleted = cache.delete(key)
    assert deleted is True
    assert cache.get(key) is None

    cache.close()


def test_ttl_policy_keys_exist() -> None:
    assert ttl_for("price") == 300
    assert ttl_for("metrics") == 900
    assert ttl_for("profile") == 21600
