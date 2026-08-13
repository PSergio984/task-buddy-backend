"""Source abstraction: one interface per knowledge source type."""

from typing import Callable, Protocol

from app.models.knowledge import SourceType


class Source(Protocol):
    """A knowledge source that can produce plain text for ingestion."""

    def extract(self) -> str:
        """Return the source's text content (zero extraction for notes)."""
        ...


class NotImplementedSource:
    """Placeholder for future source types (file/url) — demonstrates extensibility."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def extract(self) -> str:
        raise NotImplementedError("This source type is not implemented yet")


class SourceRegistry:
    """Registry mapping SourceType to a factory producing a Source."""

    def __init__(self) -> None:
        self._factories: dict[SourceType, Callable[[dict], Source]] = {}

    def register(self, source_type: SourceType, factory: Callable[[dict], Source]) -> None:
        self._factories[source_type] = factory

    def create(self, source_type: SourceType, payload: dict) -> Source:
        factory = self._factories.get(source_type)
        if factory is None:
            raise KeyError(f"No source factory registered for {source_type}")
        return factory(payload)


source_registry = SourceRegistry()
