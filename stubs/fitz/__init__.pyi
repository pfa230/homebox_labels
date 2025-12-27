from __future__ import annotations

from typing import Any, Iterator, Optional


class Pixmap:
    def tobytes(self, output: str = ...) -> bytes: ...


class Page:
    def get_pixmap(
        self,
        *,
        matrix: Any = ...,
        dpi: Optional[int] = ...,
        colorspace: Any = ...,
        clip: Any = ...,
        alpha: bool = ...,
        annots: bool = ...,
    ) -> Pixmap: ...


class Document:
    def __enter__(self) -> Document: ...
    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...
    def load_page(self, page_id: int) -> Page: ...
    def __iter__(self) -> Iterator[Page]: ...


def open(*, stream: bytes, filetype: str) -> Document: ...
