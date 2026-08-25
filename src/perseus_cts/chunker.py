"""Chunker - compiles a TEI document into CitationChunk XML files."""

from __future__ import annotations

import json
import re
from pathlib import Path

from lxml import etree

from perseus_cts.constants import TEI_NS, XML_LANG
from perseus_cts.cts_resolver import CTSResolver
from perseus_cts.models import CitationChunk, CTSCatalog, LenientTEIDocument


class Chunker:
    """Compiles a TEI document into CitationChunk XML files.

    Writes one XML file per chunk plus index.json and metadata.json."""

    def __init__(
        self,
        tei_doc: LenientTEIDocument,
        refsDecl_id: str = "CTS",
        catalog: CTSCatalog | None = None,
        chunk_unit: str | None = None,
    ) -> None:
        self.tei_doc: LenientTEIDocument = tei_doc
        self.cts_resolver = CTSResolver(
            tei_doc, refsDecl_id=refsDecl_id, chunk_unit=chunk_unit
        )
        self.catalog = catalog
        self._citation_chunks: list[CitationChunk] | None = None

    @property
    def citation_chunks(self) -> list[CitationChunk]:
        if self._citation_chunks is None:
            self._citation_chunks = list(self.cts_resolver.chunks())
        return self._citation_chunks

    def compile(
        self,
        output_path: Path,
        unit_scheme_map: dict[str, str] | None = None,
        **kwargs,
    ):
        output_path.mkdir(parents=True, exist_ok=True)
        index_entries: list[dict] = []
        for chunk in self.citation_chunks:
            fname = self._chunk_filename(chunk)
            index_entries.append({"file": fname, "cts_urn": chunk.cts_urn})
            (output_path / fname).write_bytes(
                etree.tostring(
                    chunk.to_xml(),
                    encoding="utf-8",
                    xml_declaration=True,
                    pretty_print=True,
                )
            )

        (output_path / "index.json").write_text(
            json.dumps({"chunks": index_entries}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        metadata = {
            "version": "1",
            "document": self._build_document_metadata(),
            "refsDecl_id": self.cts_resolver.refsDecl_id,
            "chunk_unit": self.citation_chunks[0].unit if self.citation_chunks else "",
            "toc": self.cts_resolver.toc(unit_scheme_map),
        }
        (output_path / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    _CTS_PATTERN = re.compile(r"urn:cts:[^:]+:[^:]+:(?P<passage>.+)$")

    @staticmethod
    def _chunk_filename(chunk: CitationChunk) -> str:
        """Return a safe XML filename derived from the passage component of the URN."""
        m = Chunker._CTS_PATTERN.match(chunk.cts_urn)
        if m is None:
            safe = re.sub(r"[^\w.-]", "_", chunk.cts_urn)
            return f"{safe}.xml"
        return f"{m['passage']}.xml"

    def _catalog_title(self, language: str) -> str:
        """Look up the work's title from __cts__.xml, matching the document's xml:lang."""
        if self.catalog is None:
            return ""
        work = self.catalog.work_for(self.cts_resolver.base_urn)
        if work is None:
            return ""
        return work.title_for(language)

    def _catalog_about(self) -> str | None:
        """Look up this version's <ti:about> urn from __cts__.xml, if any.

        Set on commentary versions to name the work/passage they comment on;
        recorded in metadata.json so mvp's siblings.py can align a
        commentary's sibling editions/translations to the work it is about
        rather than to its own (nonexistent) work family.
        """
        if self.catalog is None:
            return None
        version = self.catalog.version_for(self.cts_resolver.base_urn)
        if version is None:
            return None
        return version.about

    def _build_document_metadata(self) -> dict:
        NS = {"tei": TEI_NS}
        root = self.tei_doc.root

        language = ""
        for tag in ("tei:text", "tei:body"):
            el = root.find(f".//{tag}", NS)
            if el is not None and el.get(XML_LANG):
                language = el.get(XML_LANG)
                break
        if not language:
            lang_el = root.find(".//tei:langUsage/tei:language", NS)
            if lang_el is not None:
                language = lang_el.get("ident", "")

        title = self._catalog_title(language)
        if not title:
            title = self.tei_doc.metadata.title
        author = self.tei_doc.metadata.author

        monogr = root.find(".//tei:sourceDesc/tei:biblStruct/tei:monogr", NS)
        if monogr is not None:
            if not title:
                title = (monogr.findtext("tei:title", namespaces=NS) or "").strip()
            if not author:
                author = (monogr.findtext("tei:author", namespaces=NS) or "").strip()
            editors = [
                {"name": (ed.text or "").strip(), "role": ed.get("role", "")}
                for ed in monogr.findall("tei:editor", NS)
            ]
            imprint = monogr.find("tei:imprint", NS)
            pub_place = (
                (imprint.findtext("tei:pubPlace", namespaces=NS) or "").strip()
                if imprint is not None
                else ""
            )
            pub_date = ""
            if imprint is not None:
                for d in imprint.findall("tei:date", NS):
                    if d.get("type") == "published":
                        pub_date = (d.text or "").strip()
                        break
                if not pub_date:
                    pub_date = (
                        imprint.findtext("tei:date", namespaces=NS) or ""
                    ).strip()
        else:
            editors = [
                {"name": (ed.text or "").strip(), "role": ed.get("role", "")}
                for ed in root.findall(".//tei:titleStmt/tei:editor", NS)
            ]
            pub_stmt = root.find(".//tei:publicationStmt", NS)
            pub_place = (
                (pub_stmt.findtext("tei:pubPlace", namespaces=NS) or "").strip()
                if pub_stmt is not None
                else ""
            )
            pub_date = (
                (pub_stmt.findtext("tei:date", namespaces=NS) or "").strip()
                if pub_stmt is not None
                else ""
            )

        return {
            "base_urn": self.cts_resolver.base_urn,
            "title": title,
            "author": author,
            "language": language,
            "editors": editors,
            "pub_place": pub_place,
            "pub_date": pub_date,
            "about": self._catalog_about(),
        }
