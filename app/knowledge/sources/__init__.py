"""Source registry wiring: note + history are live; file/url are stubs for later phases."""

from app.knowledge.sources.base import NotImplementedSource, source_registry
from app.knowledge.sources.history import HistorySource
from app.knowledge.sources.note import NoteSource
from app.models.knowledge import SourceType

source_registry.register(SourceType.NOTE, lambda payload: NoteSource(content=payload["content"]))
source_registry.register(
    SourceType.HISTORY, lambda payload: HistorySource(content=payload["content"])
)
source_registry.register(SourceType.FILE, NotImplementedSource)
source_registry.register(SourceType.URL, NotImplementedSource)

__all__ = ["source_registry", "NotImplementedSource", "NoteSource", "HistorySource"]
