"""Note source: inline text knowledge, zero extraction."""



class NoteSource:
    """A text note attached to a task — content is used as-is."""

    def __init__(self, content: str) -> None:
        self.content = content

    def extract(self) -> str:
        return self.content
