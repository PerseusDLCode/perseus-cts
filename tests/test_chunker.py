"""Tests for perseus_cts.chunker.Chunker."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from perseus_cts.chunker import Chunker
from perseus_cts.models.cts_catalog import CTSCatalog
from perseus_cts.models.document import LenientTEIDocument

from conftest import write_cts
from test_cts_resolver import THUCYDIDES_XML, write_xml

DATA_DIR = Path(__file__).parent / "data"
TRACHINIAE_PATH = DATA_DIR / "tlg0011.tlg001.perseus-grc2.xml"

TRACHINIAE_WORK_CTS = """\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
             groupUrn="urn:cts:greekLit:tlg0011"
             projid="greekLit:tlg001"
             urn="urn:cts:greekLit:tlg0011.tlg001"
             xml:lang="grc">
      <ti:title xml:lang="grc">Τραχίνιαι</ti:title>
      <ti:title xml:lang="eng">Trachiniae</ti:title>
      <ti:edition urn="urn:cts:greekLit:tlg0011.tlg001.perseus-grc2"
                  workUrn="urn:cts:greekLit:tlg0011.tlg001" xml:lang="grc">
        <ti:label xml:lang="grc">Τραχίνιαι</ti:label>
        <ti:description xml:lang="mul">Sophocles, ed. Perseus.</ti:description>
      </ti:edition>
    </ti:work>
"""

TRACHINIAE_WORK_CTS_NO_ENGLISH_TITLE = TRACHINIAE_WORK_CTS.replace(
    '<ti:title xml:lang="eng">Trachiniae</ti:title>\n', ""
)


@pytest.fixture
def trachiniae_doc():
    return LenientTEIDocument(TRACHINIAE_PATH)


def _make_trachiniae_catalog(tmp_path, content: str = TRACHINIAE_WORK_CTS) -> CTSCatalog:
    cts_dir = tmp_path / "catalog"
    write_cts(cts_dir, "tlg0011", "tlg001", "__cts__.xml", content=content)
    return CTSCatalog(cts_dir)


@pytest.fixture
def trachiniae_catalog(tmp_path):
    return _make_trachiniae_catalog(tmp_path)


class TestChunkerRefsDeclSelection:
    def test_default_compiles_scene_chunks(self, trachiniae_doc, tmp_path):
        chunker = Chunker(trachiniae_doc)
        chunker.compile(tmp_path)
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["refsDecl_id"] == "CTS"
        assert metadata["chunk_unit"] == "scene"

    def test_card_refs_decl_compiles_card_chunks(self, trachiniae_doc, tmp_path):
        chunker = Chunker(trachiniae_doc, refsDecl_id="CTS-card")
        chunker.compile(tmp_path)
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["refsDecl_id"] == "CTS-card"
        assert metadata["chunk_unit"] == "card"

        index = json.loads((tmp_path / "index.json").read_text())
        assert len(index["chunks"]) == 65


class TestChunkerAutoDepthScheme:
    """chunk_unit lets a caller compile an auto-derived, depth-based scheme
    (see perseus_cts.cts_resolver.auto_chunk_units) without a second refsDecl."""

    def test_chunk_unit_compiles_at_that_level(self, tmp_path):
        doc = LenientTEIDocument(write_xml(tmp_path, THUCYDIDES_XML))
        chunker = Chunker(doc, chunk_unit="section")
        output = tmp_path / "out"
        chunker.compile(output)
        metadata = json.loads((output / "metadata.json").read_text())
        assert metadata["refsDecl_id"] == "CTS-section"
        assert metadata["chunk_unit"] == "section"
        index = json.loads((output / "index.json").read_text())
        assert len(index["chunks"]) == 6

    def test_index_and_metadata_carry_word_count_and_pct(self, tmp_path):
        doc = LenientTEIDocument(write_xml(tmp_path, THUCYDIDES_XML))
        chunker = Chunker(doc, chunk_unit="section")
        output = tmp_path / "out"
        chunker.compile(output)

        metadata = json.loads((output / "metadata.json").read_text())
        assert metadata["document"]["word_count"] == 6

        index = json.loads((output / "index.json").read_text())
        assert [c["word_count"] for c in index["chunks"]] == [1, 1, 1, 1, 1, 1]
        for chunk in index["chunks"]:
            assert chunk["pct"] == pytest.approx(100 / 6, abs=0.01)
        assert sum(c["pct"] for c in index["chunks"]) == pytest.approx(100.0, abs=0.05)

    def test_unit_scheme_map_threads_through_to_toc(self, tmp_path):
        doc = LenientTEIDocument(write_xml(tmp_path, THUCYDIDES_XML))
        chunker = Chunker(doc, chunk_unit="section")
        output = tmp_path / "out"
        chunker.compile(output, unit_scheme_map={"chapter": "", "section": "section"})
        metadata = json.loads((output / "metadata.json").read_text())
        chapter = metadata["toc"][0]["subpassages"][0]
        assert chapter["scheme"] == ""
        assert chapter["subpassages"][0]["scheme"] == "section"


class TestChunkerCatalogTitle:
    """The document's title should come from __cts__.xml, matching the
    document's xml:lang and never defaulting to the Greek/Latin title."""

    def test_no_catalog_falls_back_to_tei_metadata(self, trachiniae_doc, tmp_path):
        chunker = Chunker(trachiniae_doc)
        chunker.compile(tmp_path)
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["document"]["title"] == trachiniae_doc.metadata.title

    def test_matches_document_language(
        self, trachiniae_doc, trachiniae_catalog, tmp_path
    ):
        # tlg0011.tlg001.perseus-grc2.xml declares xml:lang="grc" on <text>.
        chunker = Chunker(trachiniae_doc, catalog=trachiniae_catalog)
        chunker.compile(tmp_path)
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["document"]["title"] == "Τραχίνιαι"
        assert metadata["document"]["language"] == "grc"

    def test_defaults_to_english_when_no_language_match(
        self, trachiniae_doc, trachiniae_catalog
    ):
        # Simulate a document whose xml:lang isn't in the catalog's titles
        # (e.g. a translation edition); title should fall back to English,
        # never silently reuse the Greek title.
        chunker = Chunker(trachiniae_doc, catalog=trachiniae_catalog)
        assert chunker._catalog_title("fre") == "Trachiniae"

    def test_never_falls_back_to_greek_or_latin_without_match(
        self, trachiniae_doc, tmp_path
    ):
        catalog = _make_trachiniae_catalog(
            tmp_path, content=TRACHINIAE_WORK_CTS_NO_ENGLISH_TITLE
        )
        chunker = Chunker(trachiniae_doc, catalog=catalog)
        assert chunker._catalog_title("fre") == ""


TRACHINIAE_WORK_CTS_WITH_ABOUT = TRACHINIAE_WORK_CTS.replace(
    '<ti:description xml:lang="mul">Sophocles, ed. Perseus.</ti:description>\n',
    '<ti:description xml:lang="mul">Sophocles, ed. Perseus.</ti:description>\n'
    '        <ti:about urn="urn:cts:greekLit:tlg0011.tlg001"/>\n',
)


class TestChunkerCatalogAbout:
    """metadata.json's document.about records <ti:about>, letting mvp's
    siblings.py align a commentary's siblings to the work it comments on."""

    def test_about_recorded_when_present(self, trachiniae_doc, tmp_path):
        catalog = _make_trachiniae_catalog(
            tmp_path, content=TRACHINIAE_WORK_CTS_WITH_ABOUT
        )
        chunker = Chunker(trachiniae_doc, catalog=catalog)
        chunker.compile(tmp_path / "out")
        metadata = json.loads((tmp_path / "out" / "metadata.json").read_text())
        assert metadata["document"]["about"] == "urn:cts:greekLit:tlg0011.tlg001"

    def test_about_absent_defaults_to_none(
        self, trachiniae_doc, trachiniae_catalog, tmp_path
    ):
        chunker = Chunker(trachiniae_doc, catalog=trachiniae_catalog)
        chunker.compile(tmp_path)
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["document"]["about"] is None

    def test_about_none_without_catalog(self, trachiniae_doc, tmp_path):
        chunker = Chunker(trachiniae_doc)
        chunker.compile(tmp_path)
        metadata = json.loads((tmp_path / "metadata.json").read_text())
        assert metadata["document"]["about"] is None
