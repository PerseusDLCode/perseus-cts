from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from perseus_cts.constants import TEI_NS


@dataclass
class TEIMetadata:
    """Descriptive metadata extracted from a TEI document header."""

    urn: str
    title: str
    author: str
    language: str  # BCP 47 / ISO 639-3: 'grc', 'lat', 'eng', etc.
    text_type: str  # 'verse' | 'prose' | 'drama'
    source_path: Path


@dataclass(frozen=True)
class WordOccurrence:
    xpath: str
    start: int
    end: int
    urn: str | None = None


@dataclass
class WordIndex:
    """Word-location index built from a TEI document body."""

    entries: dict[str, set[WordOccurrence]]


@dataclass(frozen=True)
class ChunkOccurrence:
    xpath: str
    element: str  # tag name of the source element: "l", "p", "lg", "ab"
    chunk: str
    urn: str | None = None


@dataclass
class ChunkIndex:
    """Chunk-location index built from a TEI document body."""

    entries: list[ChunkOccurrence] = field(default_factory=list)


@dataclass(frozen=True)
class CitationRecord:
    """One citable location in a TEI document, derived from citeStructure."""

    urn: str
    unit: str
    depth: int


@dataclass
class CitationChunk:
    """A citable chunk of a TEI document at a designated citation level."""

    base_urn: str
    cts_urn: str
    unit: str
    elements: list[etree._Element]
    prev_urn: str | None = None
    next_urn: str | None = None

    def to_xml(self) -> etree._Element:
        root = etree.Element("citationChunk", nsmap={"tei": TEI_NS})
        root.set("unit", self.unit)
        root.set("base_urn", self.base_urn)
        root.set("cts_urn", self.cts_urn)
        if self.prev_urn is not None:
            root.set("prev_urn", self.prev_urn)
        if self.next_urn is not None:
            root.set("next_urn", self.next_urn)

        elements = etree.SubElement(root, "elements")
        for e in self.elements:
            elements.append(e)
        return root
