from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perseus_cts.models.cts_catalog import CTSCatalog, CTSGroup, CTSWork, CTSVersion

from conftest import write_cts


GROUP_CTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:textgroup xmlns:ti="http://chs.harvard.edu/xmlns/cts"
                  projid="greekLit:tlg0012" urn="urn:cts:greekLit:tlg0012">
      <ti:groupname xml:lang="eng">Homer</ti:groupname>
    </ti:textgroup>
""")

WORK_CTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
             groupUrn="urn:cts:greekLit:tlg0012"
             projid="greekLit:tlg001"
             urn="urn:cts:greekLit:tlg0012.tlg001"
             xml:lang="grc">
      <ti:title xml:lang="eng">Iliad</ti:title>
      <ti:edition urn="urn:cts:greekLit:tlg0012.tlg001.perseus-grc2"
                  workUrn="urn:cts:greekLit:tlg0012.tlg001" xml:lang="grc">
        <ti:label xml:lang="grc">Ἰλιάς</ti:label>
        <ti:description xml:lang="mul">Homer. Homeri Opera. Oxford, 1908-1920.</ti:description>
      </ti:edition>
      <ti:translation urn="urn:cts:greekLit:tlg0012.tlg001.perseus-eng3"
                      workUrn="urn:cts:greekLit:tlg0012.tlg001" xml:lang="eng">
        <ti:label xml:lang="eng">Iliad</ti:label>
        <ti:description xml:lang="eng">Homer. The Iliad, Volume 1-2. Murray, 1924-1925.</ti:description>
      </ti:translation>
      <ti:translation urn="urn:cts:greekLit:tlg0012.tlg001.perseus-eng4"
                      workUrn="urn:cts:greekLit:tlg0012.tlg001" xml:lang="eng">
        <ti:label xml:lang="eng">Iliad</ti:label>
        <ti:description xml:lang="eng">Homer. The Iliad. Butler, 1898.</ti:description>
        <ti:memberof collection="Perseus:collection:Greco-Roman"/>
      </ti:translation>
      <ti:genre confidence="high">verse-epic</ti:genre>
    </ti:work>
""")

COMMENTARY_CTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
             groupUrn="urn:cts:greekLit:viaf001"
             urn="urn:cts:greekLit:viaf001.viaf001"
             xml:lang="eng">
      <ti:title xml:lang="eng">Commentary on the Iliad</ti:title>
      <ti:commentary workUrn="urn:cts:greekLit:viaf001.viaf001"
                     urn="urn:cts:greekLit:viaf001.viaf001.perseus-eng1" xml:lang="eng">
        <ti:label xml:lang="eng">Commentary on the Iliad</ti:label>
        <ti:description xml:lang="eng">A commentary.</ti:description>
        <ti:about urn="urn:cts:greekLit:tlg0012.tlg001"/>
      </ti:commentary>
    </ti:work>
""")

WORK_ODYSSEY_CTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
             groupUrn="urn:cts:greekLit:tlg0012"
             projid="greekLit:tlg002"
             urn="urn:cts:greekLit:tlg0012.tlg002"
             xml:lang="grc">
      <ti:title xml:lang="eng">Odyssey</ti:title>
      <ti:edition urn="urn:cts:greekLit:tlg0012.tlg002.perseus-grc2"
                  workUrn="urn:cts:greekLit:tlg0012.tlg002" xml:lang="grc">
        <ti:label xml:lang="grc">Ὀδύσσεια</ti:label>
        <ti:description xml:lang="eng">Homer. The Odyssey, Volume 1-2. Murray, 1919.</ti:description>
      </ti:edition>
      <ti:translation urn="urn:cts:greekLit:tlg0012.tlg002.perseus-eng3"
                      workUrn="urn:cts:greekLit:tlg0012.tlg002" xml:lang="eng">
        <ti:label xml:lang="eng">Odyssey</ti:label>
        <ti:description xml:lang="eng">Homer. The Odyssey, Volume 1-2. Murray, 1919.</ti:description>
      </ti:translation>
    </ti:work>
""")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestCTSCatalogConstruction:

    def test_accepts_valid_root(self, tmp_path):
        catalog = CTSCatalog(tmp_path)
        assert catalog.groups == {}

    def test_accepts_string_root(self, tmp_path):
        catalog = CTSCatalog(str(tmp_path))
        assert catalog.groups == {}

    def test_raises_on_missing_root(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CTSCatalog(tmp_path / "nonexistent")

    def test_accepts_list_of_roots(self, tmp_path):
        greek = tmp_path / "greekLit"
        latin = tmp_path / "latinLit"
        greek.mkdir()
        latin.mkdir()
        latin_cts = GROUP_CTS.replace(
            "urn:cts:greekLit:tlg0012", "urn:cts:latinLit:phi1017"
        ).replace("Homer", "Seneca")
        write_cts(greek, "__cts__.xml", content=GROUP_CTS)
        write_cts(latin, "__cts__.xml", content=latin_cts)
        catalog = CTSCatalog([greek, latin])
        assert "urn:cts:greekLit:tlg0012" in catalog.groups
        assert "urn:cts:latinLit:phi1017" in catalog.groups
        assert len(catalog.groups) == 2

    def test_multi_root_aggregates_works(self, tmp_path):
        greek = tmp_path / "greekLit"
        latin = tmp_path / "latinLit"
        greek.mkdir()
        latin.mkdir()
        write_cts(greek, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(greek, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        latin_work = WORK_CTS.replace("greekLit", "latinLit")
        write_cts(latin, "phi1017", "__cts__.xml", content=latin_work)
        catalog = CTSCatalog([greek, latin])
        assert len(catalog.works) == 2
        assert len(catalog.versions) == 6  # 3 from Iliad + 3 from Latin version

    def test_raises_on_missing_root_in_list(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CTSCatalog([tmp_path, tmp_path / "nonexistent"])


# ---------------------------------------------------------------------------
# Group-level parsing
# ---------------------------------------------------------------------------

class TestGroupParsing:

    def test_parses_group_cts(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        catalog = CTSCatalog(tmp_path)
        assert "urn:cts:greekLit:tlg0012" in catalog.groups

    def test_group_has_metadata(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        catalog = CTSCatalog(tmp_path)
        group = catalog.groups["urn:cts:greekLit:tlg0012"]
        assert isinstance(group, CTSGroup)
        assert group.urn == "urn:cts:greekLit:tlg0012"
        assert group.group_names == {"eng": "Homer"}
        assert group.works == []

    def test_group_has_source_path(self, tmp_path):
        path = write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        catalog = CTSCatalog(tmp_path)
        group = catalog.groups["urn:cts:greekLit:tlg0012"]
        assert group.source_path == path

    def test_multiple_groups(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        odyssey_group = GROUP_CTS.replace("tlg0012", "tlg0013").replace(
            "urn:cts:greekLit:tlg0012", "urn:cts:greekLit:tlg0013"
        ).replace("Homer", "Hesiod")
        write_cts(tmp_path, "tlg0013", "__cts__.xml", content=odyssey_group)
        catalog = CTSCatalog(tmp_path)
        assert len(catalog.groups) == 2

    def test_ignores_group_without_urn(self, tmp_path):
        no_urn = GROUP_CTS.replace('urn="urn:cts:greekLit:tlg0012"', "")
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=no_urn)
        catalog = CTSCatalog(tmp_path)
        assert len(catalog.groups) == 0


# ---------------------------------------------------------------------------
# Work-level parsing
# ---------------------------------------------------------------------------

class TestWorkParsing:

    def test_parses_work_cts(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        assert "urn:cts:greekLit:tlg0012.tlg001" in catalog.works

    def test_work_has_metadata(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        work = catalog.works["urn:cts:greekLit:tlg0012.tlg001"]
        assert isinstance(work, CTSWork)
        assert work.urn == "urn:cts:greekLit:tlg0012.tlg001"
        assert work.group_urn == "urn:cts:greekLit:tlg0012"
        assert work.titles == {"eng": "Iliad"}
        assert work.genre == "verse-epic"
        assert work.genre_confidence == "high"

    def test_work_parses_versions(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        work = catalog.works["urn:cts:greekLit:tlg0012.tlg001"]
        assert len(work.versions) == 3

    def test_work_versions_indexed(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        assert "urn:cts:greekLit:tlg0012.tlg001.perseus-grc2" in catalog.versions
        assert "urn:cts:greekLit:tlg0012.tlg001.perseus-eng3" in catalog.versions
        assert "urn:cts:greekLit:tlg0012.tlg001.perseus-eng4" in catalog.versions

    def test_version_has_metadata(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        edition = catalog.versions["urn:cts:greekLit:tlg0012.tlg001.perseus-grc2"]
        assert isinstance(edition, CTSVersion)
        assert edition.urn == "urn:cts:greekLit:tlg0012.tlg001.perseus-grc2"
        assert edition.work_urn == "urn:cts:greekLit:tlg0012.tlg001"
        assert edition.lang == "grc"
        assert edition.label == "Ἰλιάς"
        assert edition.version_type == "edition"
        assert edition.memberof is None

    def test_translation_version_type(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        t = catalog.versions["urn:cts:greekLit:tlg0012.tlg001.perseus-eng3"]
        assert t.version_type == "translation"
        assert t.lang == "eng"

    def test_version_with_memberof(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        t = catalog.versions["urn:cts:greekLit:tlg0012.tlg001.perseus-eng4"]
        assert t.memberof == "Perseus:collection:Greco-Roman"

    def test_work_without_genre(self, tmp_path):
        no_genre = WORK_CTS.replace('<ti:genre confidence="high">verse-epic</ti:genre>', "")
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=no_genre)
        catalog = CTSCatalog(tmp_path)
        work = catalog.works["urn:cts:greekLit:tlg0012.tlg001"]
        assert work.genre is None
        assert work.genre_confidence is None

    def test_ignores_work_without_urn(self, tmp_path):
        no_urn = WORK_CTS.replace('urn="urn:cts:greekLit:tlg0012.tlg001"', "")
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=no_urn)
        catalog = CTSCatalog(tmp_path)
        assert len(catalog.works) == 0


# ---------------------------------------------------------------------------
# Hierarchy linking (group → work → version)
# ---------------------------------------------------------------------------

class TestHierarchyLinking:

    def test_work_linked_to_group(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        group = catalog.groups["urn:cts:greekLit:tlg0012"]
        assert len(group.works) == 1
        assert group.works[0].urn == "urn:cts:greekLit:tlg0012.tlg001"

    def test_multiple_works_in_group(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        write_cts(tmp_path, "tlg0012", "tlg002", "__cts__.xml", content=WORK_ODYSSEY_CTS)
        catalog = CTSCatalog(tmp_path)
        group = catalog.groups["urn:cts:greekLit:tlg0012"]
        assert len(group.works) == 2
        urns = {w.urn for w in group.works}
        assert urns == {
            "urn:cts:greekLit:tlg0012.tlg001",
            "urn:cts:greekLit:tlg0012.tlg002",
        }

    def test_work_without_group_still_indexed(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        catalog = CTSCatalog(tmp_path)
        assert "urn:cts:greekLit:tlg0012.tlg001" in catalog.works
        # No group to link to
        assert "urn:cts:greekLit:tlg0012" not in catalog.groups


# ---------------------------------------------------------------------------
# Lookup methods
# ---------------------------------------------------------------------------

class TestLookup:

    @pytest.fixture
    def catalog(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        write_cts(tmp_path, "tlg0012", "tlg002", "__cts__.xml", content=WORK_ODYSSEY_CTS)
        return CTSCatalog(tmp_path)

    def test_group_for_by_group_urn(self, catalog):
        group = catalog.group_for("urn:cts:greekLit:tlg0012")
        assert group is not None
        assert group.group_names == {"eng": "Homer"}

    def test_group_for_by_work_urn(self, catalog):
        group = catalog.group_for("urn:cts:greekLit:tlg0012.tlg001")
        assert group is not None
        assert group.urn == "urn:cts:greekLit:tlg0012"

    def test_group_for_by_version_urn(self, catalog):
        group = catalog.group_for("urn:cts:greekLit:tlg0012.tlg001.perseus-grc2")
        assert group is not None
        assert group.urn == "urn:cts:greekLit:tlg0012"

    def test_group_for_unknown_urn(self, catalog):
        assert catalog.group_for("urn:cts:greekLit:unknown") is None

    def test_work_for_by_work_urn(self, catalog):
        work = catalog.work_for("urn:cts:greekLit:tlg0012.tlg001")
        assert work is not None
        assert work.titles == {"eng": "Iliad"}

    def test_work_for_by_version_urn(self, catalog):
        work = catalog.work_for("urn:cts:greekLit:tlg0012.tlg001.perseus-grc2")
        assert work is not None
        assert work.urn == "urn:cts:greekLit:tlg0012.tlg001"

    def test_work_for_unknown_urn(self, catalog):
        assert catalog.work_for("urn:cts:greekLit:unknown") is None

    def test_version_for_match(self, catalog):
        v = catalog.version_for("urn:cts:greekLit:tlg0012.tlg001.perseus-grc2")
        assert v is not None
        assert v.label == "Ἰλιάς"

    def test_version_for_unknown(self, catalog):
        assert catalog.version_for("urn:cts:greekLit:unknown") is None


# ---------------------------------------------------------------------------
# Edition / translation linking
# ---------------------------------------------------------------------------

class TestEditionTranslationLinking:

    @pytest.fixture
    def catalog(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        return CTSCatalog(tmp_path)

    def test_translations_of_by_work_urn(self, catalog):
        translations = catalog.translations_of("urn:cts:greekLit:tlg0012.tlg001")
        assert len(translations) == 2
        assert all(t.version_type == "translation" for t in translations)

    def test_translations_of_by_edition_urn(self, catalog):
        translations = catalog.translations_of(
            "urn:cts:greekLit:tlg0012.tlg001.perseus-grc2"
        )
        assert len(translations) == 2

    def test_translations_of_by_translation_urn(self, catalog):
        translations = catalog.translations_of(
            "urn:cts:greekLit:tlg0012.tlg001.perseus-eng3"
        )
        assert len(translations) == 2

    def test_translations_of_unknown_urn(self, catalog):
        assert catalog.translations_of("urn:cts:unknown") == []

    def test_editions_of_by_work_urn(self, catalog):
        editions = catalog.editions_of("urn:cts:greekLit:tlg0012.tlg001")
        assert len(editions) == 1
        assert editions[0].version_type == "edition"
        assert editions[0].lang == "grc"

    def test_editions_of_by_translation_urn(self, catalog):
        editions = catalog.editions_of(
            "urn:cts:greekLit:tlg0012.tlg001.perseus-eng3"
        )
        assert len(editions) == 1
        assert editions[0].urn == "urn:cts:greekLit:tlg0012.tlg001.perseus-grc2"

    def test_editions_of_unknown_urn(self, catalog):
        assert catalog.editions_of("urn:cts:unknown") == []

    def test_commentaries_of_by_work_urn(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        write_cts(tmp_path, "viaf001", "viaf001", "__cts__.xml", content=COMMENTARY_CTS)
        catalog = CTSCatalog(tmp_path)
        commentaries = catalog.commentaries_of("urn:cts:greekLit:tlg0012.tlg001")
        assert len(commentaries) == 1
        assert commentaries[0].urn == "urn:cts:greekLit:viaf001.viaf001.perseus-eng1"
        assert commentaries[0].about == "urn:cts:greekLit:tlg0012.tlg001"

    def test_commentaries_of_by_version_urn(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        write_cts(tmp_path, "viaf001", "viaf001", "__cts__.xml", content=COMMENTARY_CTS)
        catalog = CTSCatalog(tmp_path)
        commentaries = catalog.commentaries_of(
            "urn:cts:greekLit:tlg0012.tlg001.perseus-grc2"
        )
        assert len(commentaries) == 1

    def test_commentaries_of_no_match(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg002", "__cts__.xml", content=WORK_ODYSSEY_CTS)
        write_cts(tmp_path, "viaf001", "viaf001", "__cts__.xml", content=COMMENTARY_CTS)
        catalog = CTSCatalog(tmp_path)
        assert catalog.commentaries_of("urn:cts:greekLit:tlg0012.tlg002") == []

    def test_commentaries_of_unknown_urn(self, tmp_path):
        catalog = CTSCatalog(tmp_path)
        assert catalog.commentaries_of("urn:cts:unknown") == []

    def test_no_mutual_interference(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        write_cts(tmp_path, "tlg0012", "tlg001", "__cts__.xml", content=WORK_CTS)
        write_cts(tmp_path, "tlg0012", "tlg002", "__cts__.xml", content=WORK_ODYSSEY_CTS)
        catalog = CTSCatalog(tmp_path)
        iliad_translations = catalog.translations_of("urn:cts:greekLit:tlg0012.tlg001")
        odyssey_translations = catalog.translations_of("urn:cts:greekLit:tlg0012.tlg002")
        assert len(iliad_translations) == 2
        assert len(odyssey_translations) == 1


# ---------------------------------------------------------------------------
# TextInventory wrapper
# ---------------------------------------------------------------------------

class TestTextInventoryWrapper:

    def test_parses_textgroup_inside_text_inventory(self, tmp_path):
        ti_xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <ti:TextInventory xmlns:ti="http://chs.harvard.edu/xmlns/cts">
              <ti:textgroup urn="urn:cts:greekLit:tlg0011">
                <ti:groupname xml:lang="eng">Sophocles</ti:groupname>
              </ti:textgroup>
            </ti:TextInventory>
        """)
        write_cts(tmp_path, "__cts__.xml", content=ti_xml)
        catalog = CTSCatalog(tmp_path)
        assert "urn:cts:greekLit:tlg0011" in catalog.groups
        assert catalog.groups["urn:cts:greekLit:tlg0011"].group_names == {"eng": "Sophocles"}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_directory(self, tmp_path):
        catalog = CTSCatalog(tmp_path)
        assert len(catalog.groups) == 0
        assert len(catalog.works) == 0
        assert len(catalog.versions) == 0

    def test_malformed_xml_ignored(self, tmp_path):
        bad = tmp_path / "tlg0001" / "__cts__.xml"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("<unclosed>", encoding="utf-8")
        catalog = CTSCatalog(tmp_path)
        assert len(catalog.groups) == 0

    def test_mixed_valid_and_malformed(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        bad = tmp_path / "tlg0001" / "__cts__.xml"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text("<unclosed>", encoding="utf-8")
        catalog = CTSCatalog(tmp_path)
        assert "urn:cts:greekLit:tlg0012" in catalog.groups

    def test_properties_return_dicts(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        catalog = CTSCatalog(tmp_path)
        assert isinstance(catalog.groups, dict)
        assert isinstance(catalog.works, dict)
        assert isinstance(catalog.versions, dict)

    def test_properties_are_repeatable(self, tmp_path):
        write_cts(tmp_path, "tlg0012", "__cts__.xml", content=GROUP_CTS)
        catalog = CTSCatalog(tmp_path)
        first = catalog.groups
        second = catalog.groups
        assert first == second
