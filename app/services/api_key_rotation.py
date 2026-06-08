from __future__ import annotations

from threading import Lock


class APIKeyRotator:
    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self._index = 0
        self._lock = Lock()

    def __len__(self) -> int:
        return len(self.keys)

    def candidates(self) -> list[tuple[int, str]]:
        if not self.keys:
            return []
        with self._lock:
            start = self._index
            self._index = (self._index + 1) % len(self.keys)
        return [
            ((start + offset) % len(self.keys), self.keys[(start + offset) % len(self.keys)])
            for offset in range(len(self.keys))
        ]


_rotator_cache: dict[tuple[str, ...], APIKeyRotator] = {}
_rotator_cache_lock = Lock()


def get_shared_rotator(keys: list[str]) -> APIKeyRotator:
    fingerprint = tuple(keys)
    with _rotator_cache_lock:
        if fingerprint not in _rotator_cache:
            _rotator_cache[fingerprint] = APIKeyRotator(keys)
        return _rotator_cache[fingerprint]
