from __future__ import annotations

from argus.shared.idempotency import IdempotencyChecker, generate_idempotency_key


class TestIdempotencyKeyGeneration:
    def test_keys_are_unique(self) -> None:
        keys = {generate_idempotency_key() for _ in range(100)}
        assert len(keys) == 100

    def test_keys_are_strings(self) -> None:
        key = generate_idempotency_key()
        assert isinstance(key, str)
        assert len(key) > 0


class TestIdempotencyChecker:
    def test_new_key_is_not_processed(self, idempotency_checker: IdempotencyChecker) -> None:
        assert not idempotency_checker.is_processed("test-key-1")

    def test_marked_key_is_processed(self, idempotency_checker: IdempotencyChecker) -> None:
        idempotency_checker.mark_processed("test-key-1")
        assert idempotency_checker.is_processed("test-key-1")

    def test_different_key_not_processed(self, idempotency_checker: IdempotencyChecker) -> None:
        idempotency_checker.mark_processed("key-a")
        assert not idempotency_checker.is_processed("key-b")

    def test_generated_keys_round_trip(self, idempotency_checker: IdempotencyChecker) -> None:
        key = generate_idempotency_key()
        assert not idempotency_checker.is_processed(key)
        idempotency_checker.mark_processed(key)
        assert idempotency_checker.is_processed(key)

    def test_duplicate_mark_is_idempotent(self, idempotency_checker: IdempotencyChecker) -> None:
        key = generate_idempotency_key()
        idempotency_checker.mark_processed(key)
        idempotency_checker.mark_processed(key)
        assert idempotency_checker.is_processed(key)

    def test_key_expires_after_ttl(self, idempotency_checker: IdempotencyChecker) -> None:
        key = generate_idempotency_key()
        idempotency_checker.mark_processed(key, ttl_seconds=0)
        assert not idempotency_checker.is_processed(key)

    def test_cleanup_expired_keys(self, idempotency_checker: IdempotencyChecker) -> None:
        idempotency_checker.mark_processed("expired-key", ttl_seconds=0)
        idempotency_checker.mark_processed("valid-key", ttl_seconds=3600)
        cleaned = idempotency_checker.cleanup_expired()
        assert cleaned >= 1
        assert not idempotency_checker.is_processed("expired-key")
        assert idempotency_checker.is_processed("valid-key")

    def test_hash_consistency(self, idempotency_checker: IdempotencyChecker) -> None:
        key = "always-the-same-key"
        idempotency_checker.mark_processed(key)
        assert idempotency_checker.is_processed(key)
        # Same key on a new instance should detect it via DB persistence
        checker2 = IdempotencyChecker(db_path=idempotency_checker._db_path)
        assert checker2.is_processed(key)
