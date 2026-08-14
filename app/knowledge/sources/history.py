"""History source: a completed task's title + description as indexed text.

The indexed-text contract: content = the completed task's `title + description`
joined as plain text, mirroring the query-side text built for /memory/similar
(D-08) so retrieval matches what was indexed.
"""


class HistorySource:
    """A completed task's history document — content is used as-is."""

    def __init__(self, content: str) -> None:
        self.content = content

    def extract(self) -> str:
        return self.content
