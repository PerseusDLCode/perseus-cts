from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from perseus_cts.models.document import TEIDocument


class Corpus:
    """A collection of TEI source documents under a root directory.

    Discovers all .xml files recursively under root, excluding CTS
    catalog files (__cts__.xml).  Documents are loaded lazily.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        if not self._root.exists():
            raise FileNotFoundError(f"Corpus root not found: {self._root}")

    @property
    def root(self) -> Path:
        return self._root

    def documents(self) -> Iterator[TEIDocument]:
        """Yield TEIDocuments for all XML files under the corpus root."""
        from perseus_cts.models.document import TEIDocument  # noqa: PLC0415

        failures: list[tuple[Path, Exception]] = []
        for xml_path in sorted(self._root.rglob("*.xml")):
            if xml_path.name == "__cts__.xml":
                continue
            try:
                yield TEIDocument.from_path(xml_path)
            except Exception as exc:
                failures.append((xml_path, exc))

        if failures:
            print(f"Warning: skipped {len(failures)} file(s) due to parse errors:")
            for path, exc in failures:
                print(f"  {path}: {exc}")

    def document(self, urn: str) -> TEIDocument:
        """Return the TEIDocument whose metadata.urn matches urn."""
        for doc in self.documents():
            if doc.metadata.urn == urn:
                return doc
        raise KeyError(f"No document found with URN: {urn}")
