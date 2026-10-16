"""Minimal diagnostic persistence port; no production execution contract implementation."""

from typing import Protocol


class ReadinessProbe(Protocol):
    def ready(self) -> bool:
        """Confirm actual storage schema/policy health without modifying state."""
