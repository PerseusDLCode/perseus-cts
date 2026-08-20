from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from lxml import etree

from perseus_cts.commentary import _line_ref, links_for_passage, ranges_overlap
from perseus_cts.models.cts_catalog import CTSCatalog


GROUP_CTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:textgroup xmlns:ti="http://chs.harvard.edu/xmlns/cts"
                  urn="urn:cts:greekLit:tlg0011">
      <ti:groupname xml:lang="eng">Sophocles</ti:groupname>
    </ti:textgroup>
""")

WORK_CTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
             groupUrn="urn:cts:greekLit:tlg0011"
             urn="urn:cts:greekLit:tlg0011.tlg004"
             xml:lang="grc">
      <ti:title xml:lang="eng">Oedipus Tyrannus</ti:title>
      <ti:edition urn="urn:cts:greekLit:tlg0011.tlg004.perseus-grc2"
                  workUrn="urn:cts:greekLit:tlg0011.tlg004" xml:lang="grc">
        <ti:label xml:lang="grc">OT</ti:label>
        <ti:description xml:lang="eng">An edition.</ti:description>
      </ti:edition>
    </ti:work>
""")

COMMENTARY_CTS_TEMPLATE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
             groupUrn="urn:cts:greekLit:viaf001"
             urn="urn:cts:greekLit:viaf001.viaf{n}"
             xml:lang="eng">
      <ti:title xml:lang="eng">Commentary {n}</ti:title>
      <ti:commentary workUrn="urn:cts:greekLit:viaf001.viaf{n}"
                     urn="urn:cts:greekLit:viaf001.viaf{n}.perseus-eng1" xml:lang="eng">
        <ti:label xml:lang="eng">Jebb's Commentary</ti:label>
        <ti:description xml:lang="eng">A commentary.</ti:description>
        <ti:about urn="urn:cts:greekLit:tlg0011.tlg004"/>
      </ti:commentary>
    </ti:work>
""")

COMMENTARY_TEI_WITH_LINKGRP = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
        <teiHeader/>
        <text>
            <body>
                <div type="commline" n="497">
                    <p>
                        <seg type="lemma" ana="#thanaton_497">θανάτων</seg>
                        <seg type="comment" xml:id="thanaton_497">the genitive after <bibl n="foo">a bibl</bibl></seg>
                    </p>
                </div>
                <div type="commline" n="71">
                    <p>
                        <seg type="lemma" ana="#bare_71">lemma text</seg>
                        <seg type="comment" xml:id="bare_71">a bare comment</seg>
                    </p>
                </div>
            </body>
        </text>
        <standOff>
            <linkGrp type="commentary">
                <link target="urn:cts:greekLit:tlg0011.tlg004:463-512 #Thanaton_497"/>
                <link target="urn:cts:greekLit:tlg0011.tlg004:151-215 #Dios_151"/>
                <link target="1-150 #bare_71"/>
            </linkGrp>
        </standOff>
    </TEI>
""")

COMMENTARY_TEI_NO_LINKGRP = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
        <teiHeader/>
        <text><body/></text>
        <standOff/>
    </TEI>
""")


def write(directory: Path, *parts: str, content: str) -> Path:
    p = directory.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p


@pytest.fixture
def base_catalog_dir(tmp_path):
    write(tmp_path, "tlg0011", "__cts__.xml", content=GROUP_CTS)
    write(tmp_path, "tlg0011", "tlg004", "__cts__.xml", content=WORK_CTS)
    return tmp_path


class TestRangesOverlap:
    def test_identical_single_refs_overlap(self):
        assert ranges_overlap("497", "497")

    def test_disjoint_single_refs_do_not_overlap(self):
        assert not ranges_overlap("497", "498")

    def test_range_contains_point(self):
        assert ranges_overlap("463-512", "497")

    def test_point_contains_in_range(self):
        assert ranges_overlap("497", "463-512")

    def test_ranges_partially_overlap(self):
        assert ranges_overlap("463-512", "500-600")

    def test_ranges_do_not_overlap(self):
        assert not ranges_overlap("1-150", "216-462")

    def test_dotted_refs_overlap(self):
        assert ranges_overlap("1.332C", "1.332C")

    def test_dotted_refs_do_not_overlap(self):
        assert not ranges_overlap("1.332B", "1.332C")

    def test_empty_ref_never_overlaps(self):
        assert not ranges_overlap("", "497")
        assert not ranges_overlap("497", "")


def _seg_in_div(div_xml: str) -> etree._Element:
    root = etree.fromstring(
        f'<TEI xmlns="{"http://www.tei-c.org/ns/1.0"}">{div_xml}</TEI>'
    )
    return root.find(".//{http://www.tei-c.org/ns/1.0}seg")


class TestLineRef:
    def test_recognized_div_type_yields_its_n(self):
        seg = _seg_in_div(
            '<div type="commline" n="497"><seg type="comment">x</seg></div>'
        )
        assert _line_ref(seg) == "497"

    def test_unrecognized_div_type_yields_none(self):
        seg = _seg_in_div(
            '<div type="entry" n="497"><seg type="comment">x</seg></div>'
        )
        assert _line_ref(seg) is None

    def test_nearest_recognized_ancestor_wins(self):
        seg = _seg_in_div(
            '<div type="entry" n="outer">'
            '<div type="commline" n="497"><seg type="comment">x</seg></div>'
            "</div>"
        )
        assert _line_ref(seg) == "497"

    def test_none_seg_yields_none(self):
        assert _line_ref(None) is None


class TestLinksForPassage:
    def test_finds_overlapping_links_by_full_urn(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "463-512")

        assert result.warnings == []
        assert len(result.links) == 1
        assert result.links[0].anchor_id == "Thanaton_497"

    def test_finds_overlapping_links_by_bare_citation(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "1-150")

        assert len(result.links) == 1
        assert result.links[0].anchor_id == "bare_71"

    def test_no_links_outside_passage_range(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "700-862")

        assert result.links == []
        assert result.warnings == []

    def test_missing_linkgrp_produces_warning_and_no_links(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_NO_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "463-512")

        assert result.links == []
        assert len(result.warnings) == 1
        assert "linkGrp" in result.warnings[0]

    def test_no_commentaries_returns_empty_result(self, base_catalog_dir):
        catalog = CTSCatalog(base_catalog_dir)
        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "463-512")
        assert result.links == []
        assert result.warnings == []

    def test_multiple_commentaries_mix_of_linkgrp_and_missing(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        write(base_catalog_dir, "viaf001", "viaf002", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=2))
        write(base_catalog_dir, "viaf001", "viaf002",
              "viaf001.viaf2.perseus-eng1.xml", content=COMMENTARY_TEI_NO_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "463-512")

        assert len(result.links) == 1
        assert len(result.warnings) == 1

    def test_resolves_lemma_and_comment_by_exact_id(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "1-150")
        link = result.links[0]

        assert link.anchor_id == "bare_71"
        assert link.lemma == '<seg xmlns="http://www.tei-c.org/ns/1.0" type="lemma" ana="#bare_71">lemma text</seg>'
        assert link.comment == '<seg xmlns="http://www.tei-c.org/ns/1.0" type="comment" xml:id="bare_71">a bare comment</seg>'

    def test_resolves_lemma_and_comment_case_insensitively(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "463-512")
        link = result.links[0]

        assert link.anchor_id == "Thanaton_497"
        assert link.lemma is not None and "θανάτων" in link.lemma
        assert link.comment is not None and "the genitive after" in link.comment

    def test_line_ref_comes_from_enclosing_commline_div(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "463-512")
        link = result.links[0]

        assert link.anchor_id == "Thanaton_497"
        assert link.line_ref == "497"

    def test_line_ref_is_none_when_comment_is_missing(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "151-215")
        link = result.links[0]

        assert link.anchor_id == "Dios_151"
        assert link.line_ref is None

    def test_missing_lemma_or_comment_is_none(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        write(base_catalog_dir, "viaf001", "viaf001",
              "viaf001.viaf1.perseus-eng1.xml", content=COMMENTARY_TEI_WITH_LINKGRP)
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "151-215")
        link = result.links[0]

        assert link.anchor_id == "Dios_151"
        assert link.lemma is None
        assert link.comment is None

    def test_missing_source_file_produces_warning(self, base_catalog_dir):
        write(base_catalog_dir, "viaf001", "viaf001", "__cts__.xml",
              content=COMMENTARY_CTS_TEMPLATE.format(n=1))
        catalog = CTSCatalog(base_catalog_dir)

        result = links_for_passage(catalog, "urn:cts:greekLit:tlg0011.tlg004", "463-512")

        assert result.links == []
        assert len(result.warnings) == 1
        assert "not found" in result.warnings[0]
