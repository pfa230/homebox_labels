from dataclasses import dataclass


@dataclass(frozen=True)
class LabelContent:
    """Textual payload to render into a label."""

    title: str
    content: str
    url: str
    path_text: str = ""
    categories_text: str = ""
