from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perseus_cts.models import CitationChunk
from perseus_cts.models.document import LenientTEIDocument
from perseus_cts.cts_resolver import (
    CitationError,
    ConfigurationError,
    CTSResolver as ReferenceParser,
    auto_chunk_units,
    available_refsDecl_ids,
)

TEI_NS = "http://www.tei-c.org/ns/1.0"
DATA_DIR = Path(__file__).parent / "data"


def write_xml(tmp_path: Path, xml: str) -> Path:
    p = tmp_path / "test.xml"
    p.write_text(textwrap.dedent(xml), encoding="utf-8")
    return p


APOLOGY_BASE = "urn:cts:greekLit:tlg0059.tlg002.perseus-grc2"

APOLOGY_XML = f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <encodingDesc>
          <refsDecl xml:id="CTS">
            <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
              <citeStructure unit="section" delim=":" match="tei:div[@type='textpart']" use="@n"/>
            </citeStructure>
          </refsDecl>
        </encodingDesc>
      </teiHeader>
      <text>
        <body xml:base="{APOLOGY_BASE}">
          <div type="textpart" subtype="section" n="17"><p>ὅτι μέν...</p></div>
          <div type="textpart" subtype="section" n="18"><p>τοῦτο...</p></div>
          <div type="textpart" subtype="section" n="19"><p>ἴσως...</p></div>
        </body>
      </text>
    </TEI>
"""

THUCYDIDES_BASE = "urn:cts:greekLit:tlg0003.tlg001.perseus-grc2"

THUCYDIDES_XML = f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <encodingDesc>
          <refsDecl xml:id="CTS">
            <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
              <citeStructure unit="book" delim=":" match="tei:div[@subtype='book']" use="@n">
                <citeStructure unit="chapter" delim="." match="tei:div[@subtype='chapter']" use="@n">
                  <citeStructure unit="section" delim="." match="tei:div[@subtype='section']" use="@n"/>
                </citeStructure>
              </citeStructure>
            </citeStructure>
          </refsDecl>
        </encodingDesc>
      </teiHeader>
      <text>
        <body xml:base="{THUCYDIDES_BASE}">
          <div type="textpart" subtype="book" n="1">
            <div type="textpart" subtype="chapter" n="1">
              <div type="textpart" subtype="section" n="1"><p>Θουκυδίδης...</p></div>
              <div type="textpart" subtype="section" n="2"><p>text</p></div>
              <div type="textpart" subtype="section" n="3"><p>text</p></div>
            </div>
            <div type="textpart" subtype="chapter" n="2">
              <div type="textpart" subtype="section" n="1"><p>text</p></div>
              <div type="textpart" subtype="section" n="2"><p>text</p></div>
            </div>
          </div>
          <div type="textpart" subtype="book" n="2">
            <div type="textpart" subtype="chapter" n="1">
              <div type="textpart" subtype="section" n="1"><p>text</p></div>
            </div>
          </div>
        </body>
      </text>
    </TEI>
"""


@pytest.fixture
def apology_doc(tmp_path):
    return LenientTEIDocument(write_xml(tmp_path, APOLOGY_XML))


@pytest.fixture
def apology_parser(apology_doc):
    return ReferenceParser(apology_doc)


@pytest.fixture
def thucydides_doc(tmp_path):
    return LenientTEIDocument(write_xml(tmp_path, THUCYDIDES_XML))


@pytest.fixture
def thucydides_parser(thucydides_doc):
    return ReferenceParser(thucydides_doc)


BAD_DELIM_BASE = "urn:cts:greekLit:tlg0000.tlg000.test-grc1"

BAD_DELIM_XML = f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <encodingDesc>
          <refsDecl xml:id="CTS">
            <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
              <citeStructure unit="section" delim="." match="tei:div[@type='textpart']" use="@n"/>
            </citeStructure>
          </refsDecl>
        </encodingDesc>
      </teiHeader>
      <text>
        <body xml:base="{BAD_DELIM_BASE}">
          <div type="textpart" n="1"><p>text</p></div>
        </body>
      </text>
    </TEI>
"""


def test_first_level_dot_delim_raises(tmp_path):
    doc = LenientTEIDocument(write_xml(tmp_path, BAD_DELIM_XML))
    with pytest.raises(ConfigurationError, match="delim"):
        ReferenceParser(doc)


class TestApologyConstructor:
    def test_no_default_single_cs_succeeds(self, tmp_path):
        xml = f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <TEI xmlns="http://www.tei-c.org/ns/1.0">
              <teiHeader>
                <encodingDesc>
                  <refsDecl xml:id="CTS">
                    <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
                      <citeStructure unit="section" delim=":" match="tei:div[@type='textpart']" use="@n"/>
                    </citeStructure>
                  </refsDecl>
                </encodingDesc>
              </teiHeader>
              <text>
                <body xml:base="{APOLOGY_BASE}">
                  <div type="textpart" n="1"><p>text</p></div>
                </body>
              </text>
            </TEI>
        """
        doc = LenientTEIDocument(write_xml(tmp_path, xml))
        assert ReferenceParser(doc) is not None

    def test_no_cite_structure_raises(self, tmp_path):
        xml = f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <TEI xmlns="http://www.tei-c.org/ns/1.0">
              <teiHeader>
                <encodingDesc>
                  <refsDecl n="CTS">
                    <cRefPattern n="section" matchPattern="(\\w+)"
                                 replacementPattern="#xpath(...)">
                      <p>section</p>
                    </cRefPattern>
                  </refsDecl>
                </encodingDesc>
              </teiHeader>
              <text>
                <body xml:base="{APOLOGY_BASE}">
                  <div type="textpart" n="1"><p>text</p></div>
                </body>
              </text>
            </TEI>
        """
        doc = LenientTEIDocument(write_xml(tmp_path, xml))
        with pytest.raises(ConfigurationError):
            ReferenceParser(doc)

    def test_body_n_without_xml_base_raises(self, tmp_path):
        xml = f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <TEI xmlns="http://www.tei-c.org/ns/1.0">
              <teiHeader>
                <encodingDesc>
                  <refsDecl xml:id="CTS">
                    <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
                      <citeStructure unit="section" delim=":" match="tei:div[@type='textpart']" use="@n"/>
                    </citeStructure>
                  </refsDecl>
                </encodingDesc>
              </teiHeader>
              <text>
                <body n="{APOLOGY_BASE}">
                  <div type="textpart" n="1"><p>text</p></div>
                </body>
              </text>
            </TEI>
        """
        doc = LenientTEIDocument(write_xml(tmp_path, xml))
        with pytest.raises(ConfigurationError):
            ReferenceParser(doc)

    def test_nonexistent_refsDecl_id_raises(self, apology_doc):
        with pytest.raises(ConfigurationError):
            ReferenceParser(apology_doc, refsDecl_id="no_such_id")

    def test_explicit_refsDecl_id_selects_correct_decl(self, apology_doc):
        assert ReferenceParser(apology_doc, refsDecl_id="CTS") is not None


class TestApologyResolve:
    def test_resolve_known_section(self, apology_parser):
        elem = apology_parser.resolve(f"{APOLOGY_BASE}:17")
        assert elem.get("n") == "17"
        assert elem.get("type") == "textpart"

    def test_resolve_wrong_base_raises(self, apology_parser):
        with pytest.raises(CitationError):
            apology_parser.resolve("urn:cts:greekLit:tlg9999.tlg001.foo:17")

    def test_resolve_nonexistent_section_raises(self, apology_parser):
        with pytest.raises(CitationError):
            apology_parser.resolve(f"{APOLOGY_BASE}:99")


class TestApologyGenerate:
    def test_generate_known_section(self, apology_doc, apology_parser):
        body = apology_doc.root.find(f".//{{{TEI_NS}}}body")
        div_17 = next(d for d in body.findall(f"{{{TEI_NS}}}div") if d.get("n") == "17")
        assert apology_parser.generate(div_17) == f"{APOLOGY_BASE}:17"

    def test_generate_unreachable_element_raises(self, apology_doc, apology_parser):
        p = apology_doc.root.find(f".//{{{TEI_NS}}}p")
        with pytest.raises(CitationError):
            apology_parser.generate(p)


class TestApologyCitations:
    def test_citations_all_levels_count(self, apology_parser):
        assert len(list(apology_parser.citations(depth=-1))) == 3

    def test_citations_depth_zero_same_as_all(self, apology_parser):
        assert len(list(apology_parser.citations(depth=0))) == 3

    def test_citations_document_order(self, apology_parser):
        assert list(apology_parser.citations()) == [
            f"{APOLOGY_BASE}:17",
            f"{APOLOGY_BASE}:18",
            f"{APOLOGY_BASE}:19",
        ]


class TestThucydidesResolve:
    def test_resolve_full_three_level(self, thucydides_parser):
        elem = thucydides_parser.resolve(f"{THUCYDIDES_BASE}:1.1.3")
        assert elem.get("subtype") == "section"
        assert elem.get("n") == "3"
        chapter = elem.getparent()
        assert chapter.get("subtype") == "chapter"
        assert chapter.get("n") == "1"
        book = chapter.getparent()
        assert book.get("subtype") == "book"
        assert book.get("n") == "1"

    def test_resolve_partial_book(self, thucydides_parser):
        elem = thucydides_parser.resolve(f"{THUCYDIDES_BASE}:1")
        assert elem.get("subtype") == "book"
        assert elem.get("n") == "1"

    def test_resolve_partial_chapter(self, thucydides_parser):
        elem = thucydides_parser.resolve(f"{THUCYDIDES_BASE}:1.2")
        assert elem.get("subtype") == "chapter"
        assert elem.get("n") == "2"


class TestThucydidesGenerate:
    def _get(self, doc, **attrs):
        root = doc.root
        for div in root.iter(f"{{{TEI_NS}}}div"):
            if all(div.get(k) == v for k, v in attrs.items()):
                return div
        raise KeyError(attrs)

    def test_generate_section_full_urn(self, thucydides_doc, thucydides_parser):
        book1 = self._get(thucydides_doc, subtype="book", n="1")
        ch1 = next(
            d for d in book1 if d.get("subtype") == "chapter" and d.get("n") == "1"
        )
        sec3 = next(
            d for d in ch1 if d.get("subtype") == "section" and d.get("n") == "3"
        )
        assert thucydides_parser.generate(sec3) == f"{THUCYDIDES_BASE}:1.1.3"

    def test_generate_book_partial_urn(self, thucydides_doc, thucydides_parser):
        book1 = self._get(thucydides_doc, subtype="book", n="1")
        assert thucydides_parser.generate(book1) == f"{THUCYDIDES_BASE}:1"


class TestThucydidesCitations:
    def test_citations_depth_zero_books_only(self, thucydides_parser):
        urns = list(thucydides_parser.citations(depth=0))
        assert urns == [
            f"{THUCYDIDES_BASE}:1",
            f"{THUCYDIDES_BASE}:2",
        ]

    def test_citations_depth_one_books_and_chapters(self, thucydides_parser):
        urns = list(thucydides_parser.citations(depth=1))
        assert len(urns) == 5
        assert f"{THUCYDIDES_BASE}:1" in urns
        assert f"{THUCYDIDES_BASE}:1.1" in urns
        assert f"{THUCYDIDES_BASE}:1.2" in urns
        assert f"{THUCYDIDES_BASE}:2" in urns
        assert f"{THUCYDIDES_BASE}:2.1" in urns

    def test_citations_all_levels_count(self, thucydides_parser):
        assert len(list(thucydides_parser.citations(depth=-1))) == 11

    def test_citations_document_order(self, thucydides_parser):
        urns = list(thucydides_parser.citations(depth=-1))
        assert urns[0] == f"{THUCYDIDES_BASE}:1"
        assert urns[1] == f"{THUCYDIDES_BASE}:1.1"
        assert urns[2] == f"{THUCYDIDES_BASE}:1.1.1"
        assert urns[-1] == f"{THUCYDIDES_BASE}:2.1.1"


class TestTOC:
    def test_returns_list(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert isinstance(result, list)

    def test_top_level_count_equals_book_count(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert len(result) == 2

    def test_top_level_depth_is_zero(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert all(e["depth"] == 0 for e in result)

    def test_top_level_index_is_one_based(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert [e["index"] for e in result] == [1, 2]

    def test_top_level_subtype_is_book(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert all(e["subtype"] == "book" for e in result)

    def test_top_level_label(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert result[0]["label"] == "Book 1"
        assert result[1]["label"] == "Book 2"

    def test_top_level_urn(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert result[0]["urn"] == f"{THUCYDIDES_BASE}:1"
        assert result[1]["urn"] == f"{THUCYDIDES_BASE}:2"

    def test_subpassages_are_chapters(self, thucydides_parser):
        result = thucydides_parser.toc()
        for entry in result[0]["subpassages"]:
            assert entry["subtype"] == "chapter"
            assert entry["depth"] == 1

    def test_chapter_index_restarts_per_book(self, thucydides_parser):
        result = thucydides_parser.toc()
        assert [e["index"] for e in result[0]["subpassages"]] == [1, 2]
        assert [e["index"] for e in result[1]["subpassages"]] == [1]

    def test_chapters_are_the_chunk_level_with_no_section_subpassages(
        self, thucydides_parser
    ):
        # No citeStructure carries n="chunk", so the penultimate level
        # (chapter) is the chunk level (see _find_chunk_cs), and toc()
        # stops there rather than descending into sections.
        result = thucydides_parser.toc()
        chapter = result[0]["subpassages"][0]
        assert chapter["subpassages"] == []

    def test_leaf_subpassages_empty(self, thucydides_parser):
        result = thucydides_parser.toc()
        for chapter in result[0]["subpassages"]:
            assert chapter["subpassages"] == []

    def test_single_level_doc(self, apology_parser):
        result = apology_parser.toc()
        assert len(result) == 3
        assert all(e["depth"] == 0 for e in result)
        assert all(e["subpassages"] == [] for e in result)

    def test_toc_without_n_attr_uses_idx_for_label_not_urn(self, tmp_path):
        base = "urn:cts:greekLit:tlg0001.tlg001.test"
        xml = textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <TEI xmlns="{TEI_NS}">
              <teiHeader>
                <encodingDesc>
                  <refsDecl xml:id="CTS">
                    <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
                      <citeStructure unit="book" delim=":" match="tei:div[@type='textpart']"/>
                    </citeStructure>
                  </refsDecl>
                </encodingDesc>
              </teiHeader>
              <text>
                <body xml:base="{base}">
                  <div type="textpart"><p>one</p></div>
                  <div type="textpart"><p>two</p></div>
                </body>
              </text>
            </TEI>
        """)
        path = tmp_path / "no_n.xml"
        path.write_text(xml, encoding="utf-8")
        doc = LenientTEIDocument(path)
        result = ReferenceParser(doc).toc()
        assert len(result) == 2
        assert result[0]["label"] == "Book 1"
        assert result[1]["label"] == "Book 2"
        assert result[0]["urn"] == base + ":"
        assert result[1]["urn"] == base + ":"


class TestTOCUnitSchemeMap:
    """With a unit_scheme_map, toc() recurses to the true leaf and stamps
    each entry's target scheme, instead of stopping at the resolver's own
    chunk level (see auto_chunk_units and Chunker.compile)."""

    def test_recurses_past_own_chunk_level_into_sections(self, thucydides_parser):
        # thucydides_parser's own default chunk level is "chapter" (no
        # n="chunk" -> penultimate fallback); passing a map should still
        # surface "section" subpassages beneath each chapter.
        result = thucydides_parser.toc({"chapter": "", "section": "section"})
        chapter = result[0]["subpassages"][0]
        assert [s["subtype"] for s in chapter["subpassages"]] == ["section", "section", "section"]

    def test_entries_carry_scheme_from_map(self, thucydides_parser):
        result = thucydides_parser.toc({"chapter": "", "section": "section"})
        book, chapter = result[0], result[0]["subpassages"][0]
        section = chapter["subpassages"][0]
        assert book["scheme"] is None
        assert chapter["scheme"] == ""
        assert section["scheme"] == "section"

    def test_unmapped_unit_yields_none_scheme(self, thucydides_parser):
        result = thucydides_parser.toc({"chapter": ""})
        chapter = result[0]["subpassages"][0]
        section = chapter["subpassages"][0]
        assert chapter["scheme"] == ""
        assert section["scheme"] is None

    def test_no_map_keeps_old_behavior_and_omits_scheme_key(self, thucydides_parser):
        result = thucydides_parser.toc()
        chapter = result[0]["subpassages"][0]
        assert chapter["subpassages"] == []
        assert "scheme" not in chapter


class TestChunksDivBased:
    def test_returns_citation_chunk_objects(self, thucydides_parser):
        result = list(thucydides_parser.chunks())
        assert all(isinstance(c, CitationChunk) for c in result)

    def test_chunk_count_equals_chapter_count(self, thucydides_parser):
        result = list(thucydides_parser.chunks())
        assert len(result) == 3

    def test_chunks_are_chapter_level(self, thucydides_parser):
        result = list(thucydides_parser.chunks())
        assert all(c.unit == "chapter" for c in result)

    def test_each_chunk_has_one_element(self, thucydides_parser):
        result = list(thucydides_parser.chunks())
        assert all(len(c.elements) == 1 for c in result)

    def test_chunk_urns_are_correct(self, thucydides_parser):
        urns = [c.cts_urn for c in thucydides_parser.chunks()]
        assert urns == [
            f"{THUCYDIDES_BASE}:1.1",
            f"{THUCYDIDES_BASE}:1.2",
            f"{THUCYDIDES_BASE}:2.1",
        ]

    def test_prev_next_navigation(self, thucydides_parser):
        chunks = list(thucydides_parser.chunks())
        assert chunks[0].prev_urn is None
        assert chunks[0].next_urn == f"{THUCYDIDES_BASE}:1.2"
        assert chunks[1].prev_urn == f"{THUCYDIDES_BASE}:1.1"
        assert chunks[1].next_urn == f"{THUCYDIDES_BASE}:2.1"
        assert chunks[2].prev_urn == f"{THUCYDIDES_BASE}:1.2"
        assert chunks[2].next_urn is None

    def test_single_level_uses_that_level(self, apology_parser):
        result = list(apology_parser.chunks())
        assert len(result) == 3
        assert all(c.unit == "section" for c in result)

    def test_n_chunk_attr_overrides_penultimate(self, tmp_path):
        xml = f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <TEI xmlns="http://www.tei-c.org/ns/1.0">
              <teiHeader>
                <encodingDesc>
                  <refsDecl xml:id="CTS">
                    <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
                      <citeStructure unit="book" delim=":" match="tei:div[@subtype='book']" use="@n">
                        <citeStructure unit="chapter" delim="." match="tei:div[@subtype='chapter']" use="@n">
                          <citeStructure unit="section" delim="." match="tei:div[@subtype='section']" use="@n" n="chunk"/>
                        </citeStructure>
                      </citeStructure>
                    </citeStructure>
                  </refsDecl>
                </encodingDesc>
              </teiHeader>
              <text>
                <body xml:base="{THUCYDIDES_BASE}">
                  <div type="textpart" subtype="book" n="1">
                    <div type="textpart" subtype="chapter" n="1">
                      <div type="textpart" subtype="section" n="1"><p>A</p></div>
                      <div type="textpart" subtype="section" n="2"><p>B</p></div>
                    </div>
                  </div>
                </body>
              </text>
            </TEI>"""
        p = tmp_path / "chunk.xml"
        p.write_text(xml, encoding="utf-8")
        parser = ReferenceParser(LenientTEIDocument(p))
        result = list(parser.chunks())
        assert len(result) == 2
        assert all(c.unit == "section" for c in result)


HERODOTUS_XML = f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <encodingDesc>
          <refsDecl xml:id="CTS">
            <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
              <citeStructure unit="book" delim=":" match="tei:div[@subtype='book']" use="@n">
                <citeStructure unit="chapter" delim="." match="tei:div[@subtype='chapter']" use="@n" n="chunk">
                  <citeStructure unit="section" delim="." match="tei:div[@subtype='section']" use="@n"/>
                </citeStructure>
              </citeStructure>
            </citeStructure>
          </refsDecl>
        </encodingDesc>
      </teiHeader>
      <text>
        <body xml:base="{THUCYDIDES_BASE}">
          <div type="textpart" subtype="book" n="1">
            <div type="textpart" subtype="chapter" n="1">
              <div type="textpart" subtype="section" n="1"><p>a</p></div>
              <div type="textpart" subtype="section" n="2"><p>b</p></div>
            </div>
          </div>
        </body>
      </text>
    </TEI>
"""


class TestAutoChunkUnits:
    """auto_chunk_units derives a depth-based routing scheme for the level
    adjacent to the configured default, without requiring a second refsDecl
    (see canonical-greekLit's hand-written CTS-chapter/CTS-section pairs for
    Thucydides/Herodotus, which this is meant to make unnecessary)."""

    def test_two_level_hierarchy_yields_nothing(self, apology_doc):
        assert auto_chunk_units(apology_doc) == []

    def test_default_at_penultimate_level_yields_deepest_unit(self, thucydides_doc):
        # thucydides_parser has no n="chunk", so the default chunk level is
        # the penultimate ("chapter") — the deeper "section" level is the
        # one worth exposing as an auto scheme.
        assert auto_chunk_units(thucydides_doc) == ["section"]

    def test_default_at_deepest_level_yields_penultimate_unit(self, tmp_path):
        xml = THUCYDIDES_XML.replace(
            'match="tei:div[@subtype=\'section\']" use="@n"/>',
            'match="tei:div[@subtype=\'section\']" use="@n" n="chunk"/>',
        )
        p = write_xml(tmp_path, xml)
        doc = LenientTEIDocument(p)
        assert auto_chunk_units(doc) == ["chapter"]

    def test_default_at_shallower_explicit_level_yields_deepest_unit(self, tmp_path):
        p = write_xml(tmp_path, HERODOTUS_XML)
        doc = LenientTEIDocument(p)
        assert auto_chunk_units(doc) == ["section"]

    def test_single_level_hierarchy_yields_nothing(self, tmp_path):
        p = write_xml(tmp_path, MILESTONE_XML)
        doc = LenientTEIDocument(p)
        assert auto_chunk_units(doc) == []

    def test_chunk_unit_override_chunks_at_that_level(self, thucydides_doc):
        resolver = ReferenceParser(thucydides_doc, chunk_unit="section")
        result = list(resolver.chunks())
        assert all(c.unit == "section" for c in result)
        assert len(result) == 6

    def test_chunk_unit_override_sets_synthetic_refsDecl_id(self, thucydides_doc):
        resolver = ReferenceParser(thucydides_doc, chunk_unit="section")
        assert resolver.refsDecl_id == "CTS-section"

    def test_chunk_unit_override_unknown_unit_raises(self, thucydides_doc):
        resolver = ReferenceParser(thucydides_doc, chunk_unit="paragraph")
        with pytest.raises(ConfigurationError):
            list(resolver.chunks())


MILESTONE_BASE = "urn:cts:myexample:author.work.edition"

MILESTONE_XML = f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <encodingDesc>
          <refsDecl xml:id="CTS">
            <citeStructure match="//tei:milestone[@unit='card']"
                           unit="card" delim=" " use="@n" n="chunk"/>
          </refsDecl>
        </encodingDesc>
      </teiHeader>
      <text>
        <body xml:base="{MILESTONE_BASE}">
          <milestone unit="card" n="1"/>
          <div><p>card 1 content</p></div>
          <milestone unit="card" n="2"/>
          <div><p>card 2 content</p></div>
          <milestone unit="card" n="3"/>
          <div><p>card 3 content</p></div>
        </body>
      </text>
    </TEI>"""


@pytest.fixture
def milestone_parser(tmp_path):
    p = tmp_path / "milestone.xml"
    p.write_text(MILESTONE_XML, encoding="utf-8")
    return ReferenceParser(LenientTEIDocument(p))


class TestChunksMilestoneBased:
    def test_returns_citation_chunk_objects(self, milestone_parser):
        result = list(milestone_parser.chunks())
        assert all(isinstance(c, CitationChunk) for c in result)

    def test_chunk_count_equals_milestone_count(self, milestone_parser):
        result = list(milestone_parser.chunks())
        assert len(result) == 3

    def test_chunks_are_card_unit(self, milestone_parser):
        result = list(milestone_parser.chunks())
        assert all(c.unit == "card" for c in result)

    def test_chunk_urns(self, milestone_parser):
        urns = [c.cts_urn for c in milestone_parser.chunks()]
        assert urns == [
            f"{MILESTONE_BASE} 1",
            f"{MILESTONE_BASE} 2",
            f"{MILESTONE_BASE} 3",
        ]

    def test_prev_next_navigation(self, milestone_parser):
        chunks = list(milestone_parser.chunks())
        assert chunks[0].prev_urn is None
        assert chunks[0].next_urn == f"{MILESTONE_BASE} 2"
        assert chunks[2].prev_urn == f"{MILESTONE_BASE} 2"
        assert chunks[2].next_urn is None

    def test_each_chunk_contains_correct_content(self, milestone_parser):
        from lxml import etree as _etree

        chunks = list(milestone_parser.chunks())
        divs0 = [
            e for e in chunks[0].elements if _etree.QName(e.tag).localname == "div"
        ]
        assert len(divs0) == 1
        assert divs0[0][0].text == "card 1 content"
        divs1 = [
            e for e in chunks[1].elements if _etree.QName(e.tag).localname == "div"
        ]
        assert divs1[0][0].text == "card 2 content"


# ---------------------------------------------------------------------------
# XPath @use support (range URN / drama pattern)
# ---------------------------------------------------------------------------


def test_flat_line_structure_raises_on_chunks(tmp_path):
    base = "urn:cts:greekLit:tlg0000.tlg000.test-grc1"
    xml = textwrap.dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <TEI xmlns="{TEI_NS}">
          <teiHeader>
            <encodingDesc>
              <refsDecl xml:id="CTS">
                <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
                  <citeStructure unit="line" delim=":" match=".//tei:l" use="@n"/>
                </citeStructure>
              </refsDecl>
            </encodingDesc>
          </teiHeader>
          <text><body xml:base="{base}">
            <div type="episode"><l n="1">one</l><l n="2">two</l></div>
          </body></text>
        </TEI>
    """)
    p = tmp_path / "flat_line.xml"
    p.write_text(xml, encoding="utf-8")
    parser = ReferenceParser(LenientTEIDocument(p))
    with pytest.raises(ConfigurationError, match="unit='line'"):
        list(parser.chunks())


DRAMA_BASE = "urn:cts:greekLit:tlg0000.tlg000.test-grc1"

DRAMA_XML = f"""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <encodingDesc>
          <refsDecl xml:id="CTS">
            <citeStructure match="/tei:TEI/tei:text/tei:body" use="@xml:base">
              <citeStructure unit="scene" delim=":"
                             match=".//div[@type='textpart']"
                             use="concat((.//l)[1]/@n, '-', (.//l)[last()]/@n)"
                             n="chunk"/>
              <citeStructure unit="line" delim=":" match=".//l" use="@n"/>
            </citeStructure>
          </refsDecl>
        </encodingDesc>
      </teiHeader>
      <text>
        <body xml:base="{DRAMA_BASE}">
          <div type="textpart" subtype="episode" n="1">
            <l n="1">line one</l>
            <l n="2">line two</l>
            <l n="3">line three</l>
          </div>
          <div type="textpart" subtype="episode" n="2">
            <l n="4">line four</l>
            <l n="5">line five</l>
          </div>
        </body>
      </text>
    </TEI>"""


@pytest.fixture
def drama_parser(tmp_path):
    p = tmp_path / "drama.xml"
    p.write_text(DRAMA_XML, encoding="utf-8")
    return ReferenceParser(LenientTEIDocument(p))


class TestXPathUse:
    def test_chunk_count_equals_scene_count(self, drama_parser):
        assert len(list(drama_parser.chunks())) == 2

    def test_chunks_are_scene_unit(self, drama_parser):
        assert all(c.unit == "scene" for c in drama_parser.chunks())

    def test_chunk_urns_are_line_ranges(self, drama_parser):
        urns = [c.cts_urn for c in drama_parser.chunks()]
        assert urns == [f"{DRAMA_BASE}:1-3", f"{DRAMA_BASE}:4-5"]

    def test_prev_next_navigation(self, drama_parser):
        chunks = list(drama_parser.chunks())
        assert chunks[0].prev_urn is None
        assert chunks[0].next_urn == f"{DRAMA_BASE}:4-5"
        assert chunks[1].prev_urn == f"{DRAMA_BASE}:1-3"
        assert chunks[1].next_urn is None

    def test_resolve_line_still_works(self, drama_parser):
        elem = drama_parser.resolve(f"{DRAMA_BASE}:3")
        assert elem.text == "line three"

    def test_resolve_line_from_second_scene(self, drama_parser):
        elem = drama_parser.resolve(f"{DRAMA_BASE}:4")
        assert elem.text == "line four"

    def test_generate_line_element(self, drama_parser, tmp_path):
        p = tmp_path / "drama.xml"
        p.write_text(DRAMA_XML, encoding="utf-8")
        doc = LenientTEIDocument(p)
        parser = ReferenceParser(doc)
        line = parser.resolve(f"{DRAMA_BASE}:2")
        assert parser.generate(line) == f"{DRAMA_BASE}:2"

    def test_citations_include_scene_and_line_levels(self, drama_parser):
        urns = list(drama_parser.citations())
        assert f"{DRAMA_BASE}:1-3" in urns
        assert f"{DRAMA_BASE}:1" in urns


# ---------------------------------------------------------------------------
# Trachiniae fixture — passes once the citeStructure is added to the file
# ---------------------------------------------------------------------------

TRACHINIAE_PATH = DATA_DIR / "tlg0011.tlg001.perseus-grc2.xml"
TRACHINIAE_BASE = "urn:cts:greekLit:tlg0011.tlg001.perseus-grc2"


@pytest.fixture
def trachiniae_parser():
    return ReferenceParser(LenientTEIDocument(TRACHINIAE_PATH))


class TestTrachinaeMilestoneChunks:
    def test_resolver_initializes(self, trachiniae_parser):
        assert trachiniae_parser is not None

    def test_chunks_are_scene_unit(self, trachiniae_parser):
        chunks = list(trachiniae_parser.chunks())
        assert all(c.unit == "scene" for c in chunks)

    def test_chunk_urns_are_line_ranges(self, trachiniae_parser):
        urns = [c.cts_urn for c in trachiniae_parser.chunks()]
        assert all("-" in u.split(":")[-1] for u in urns)

    def test_first_chunk_starts_at_line_1(self, trachiniae_parser):
        chunks = list(trachiniae_parser.chunks())
        first_passage = chunks[0].cts_urn.split(":")[-1]
        assert first_passage.startswith("1-")

    def test_resolve_first_line(self, trachiniae_parser):
        elem = trachiniae_parser.resolve(f"{TRACHINIAE_BASE}:1")
        assert elem.get("n") == "1"

    def test_chunks_are_fewer_than_lines(self, trachiniae_parser):
        chunks = list(trachiniae_parser.chunks())
        lines = list(trachiniae_parser.citations(depth=0))
        assert len(chunks) < len(lines)


# ---------------------------------------------------------------------------
# Trachiniae — alternate card-based citeStructure (CTS-card refsDecl)
# ---------------------------------------------------------------------------


@pytest.fixture
def trachiniae_card_parser():
    return ReferenceParser(LenientTEIDocument(TRACHINIAE_PATH), refsDecl_id="CTS-card")


class TestTrachiniaeCardChunks:
    def test_resolver_initializes(self, trachiniae_card_parser):
        assert trachiniae_card_parser is not None

    def test_chunks_are_card_unit(self, trachiniae_card_parser):
        chunks = list(trachiniae_card_parser.chunks())
        assert all(c.unit == "card" for c in chunks)

    def test_chunk_count_equals_card_milestone_count(self, trachiniae_card_parser):
        chunks = list(trachiniae_card_parser.chunks())
        assert len(chunks) == 65

    def test_first_chunk_urn_is_card_one(self, trachiniae_card_parser):
        chunks = list(trachiniae_card_parser.chunks())
        assert chunks[0].cts_urn == f"{TRACHINIAE_BASE}:1"

    def test_card_chunks_are_more_numerous_than_scene_chunks(
        self, trachiniae_card_parser, trachiniae_parser
    ):
        card_chunks = list(trachiniae_card_parser.chunks())
        scene_chunks = list(trachiniae_parser.chunks())
        assert len(card_chunks) > len(scene_chunks)

    def test_toc_is_flat_list_of_card_entries(self, trachiniae_card_parser):
        toc = trachiniae_card_parser.toc()
        assert len(toc) == 65
        assert all(entry["subtype"] == "card" for entry in toc)
        assert all(entry["subpassages"] == [] for entry in toc)
        assert toc[0]["urn"] == f"{TRACHINIAE_BASE}:1"

    def test_citations_yields_every_card_urn(self, trachiniae_card_parser):
        urns = list(trachiniae_card_parser.citations())
        assert len(urns) == 65
        assert urns[0] == f"{TRACHINIAE_BASE}:1"

    def test_resolve_a_card(self, trachiniae_card_parser):
        elem = trachiniae_card_parser.resolve(f"{TRACHINIAE_BASE}:49")
        assert elem.get("n") == "49"

    def test_generate_round_trips_resolve(self, trachiniae_card_parser):
        elem = trachiniae_card_parser.resolve(f"{TRACHINIAE_BASE}:49")
        assert trachiniae_card_parser.generate(elem) == f"{TRACHINIAE_BASE}:49"


class TestAvailableRefsDeclIds:
    def test_trachiniae_declares_both_schemes(self):
        doc = LenientTEIDocument(TRACHINIAE_PATH)
        assert available_refsDecl_ids(doc) == ["CTS", "CTS-card"]

    def test_apology_declares_single_scheme(self, apology_doc):
        assert available_refsDecl_ids(apology_doc) == ["CTS"]
