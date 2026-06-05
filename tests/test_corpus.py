from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perseus_cts.models import Corpus
from perseus_cts.models.document import TEIDocument

DATA_DIR = Path(__file__).parent / "data"

MINIMAL_TEI = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <fileDesc>
          <titleStmt>
            <title>Minimal</title>
            <author>Nobody</author>
          </titleStmt>
          <publicationStmt><p>Test</p></publicationStmt>
          <sourceDesc><p>Test</p></sourceDesc>
        </fileDesc>
      </teiHeader>
      <text xml:lang="lat"><body><p>text</p></body></text>
    </TEI>
""")

MINIMAL_CTS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <ti:TextInventory xmlns:ti="http://chs.harvard.edu/xmlns/cts">
      <ti:textgroup urn="urn:cts:greekLit:tlg0011">
        <ti:groupname xml:lang="eng">Sophocles</ti:groupname>
      </ti:textgroup>
    </ti:TextInventory>
""")


def make_tei_file(directory: Path, name: str,
                  content: str = MINIMAL_TEI) -> Path:
    p = directory / name
    p.write_text(content, encoding="utf-8")
    return p


@pytest.fixture
def corpus_root(tmp_path):
    make_tei_file(tmp_path, "a.xml")
    make_tei_file(tmp_path, "b.xml")
    (tmp_path / "README.txt").write_text("not xml", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    make_tei_file(sub, "c.xml")
    return tmp_path


class TestCorpusConstruction:

    def test_accepts_valid_root(self, tmp_path):
        corpus = Corpus(tmp_path)
        assert corpus.root == tmp_path

    def test_accepts_string_root(self, tmp_path):
        corpus = Corpus(str(tmp_path))
        assert corpus.root == tmp_path

    def test_raises_on_missing_root(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Corpus(tmp_path / "nonexistent")


class TestCorpusDocuments:

    def test_yields_tei_documents(self, corpus_root):
        corpus = Corpus(corpus_root)
        docs = list(corpus.documents())
        assert all(isinstance(d, TEIDocument) for d in docs)

    def test_finds_all_xml_files(self, corpus_root):
        corpus = Corpus(corpus_root)
        paths = {d.path for d in corpus.documents()}
        assert corpus_root / "a.xml" in paths
        assert corpus_root / "b.xml" in paths
        assert corpus_root / "sub" / "c.xml" in paths

    def test_recurses_into_subdirectories(self, corpus_root):
        corpus = Corpus(corpus_root)
        paths = {d.path for d in corpus.documents()}
        assert corpus_root / "sub" / "c.xml" in paths

    def test_ignores_non_xml_files(self, corpus_root):
        corpus = Corpus(corpus_root)
        paths = {d.path for d in corpus.documents()}
        assert not any(p.suffix != ".xml" for p in paths)

    def test_document_count(self, corpus_root):
        corpus = Corpus(corpus_root)
        assert len(list(corpus.documents())) == 3

    def test_excludes_cts_catalog_files(self, tmp_path):
        make_tei_file(tmp_path, "text.xml")
        (tmp_path / "__cts__.xml").write_text(MINIMAL_CTS, encoding="utf-8")
        sub = tmp_path / "tlg0011"
        sub.mkdir()
        (sub / "__cts__.xml").write_text(MINIMAL_CTS, encoding="utf-8")

        corpus = Corpus(tmp_path)
        paths = {d.path for d in corpus.documents()}

        assert tmp_path / "text.xml" in paths
        assert tmp_path / "__cts__.xml" not in paths
        assert sub / "__cts__.xml" not in paths

    def test_tolerates_malformed_xml(self, tmp_path):
        make_tei_file(tmp_path, "good.xml")
        bad = tmp_path / "bad.xml"
        bad.write_text("<unclosed>", encoding="utf-8")

        corpus = Corpus(tmp_path)
        docs = list(corpus.documents())

        paths = {d.path for d in docs}
        assert tmp_path / "good.xml" in paths

    def test_empty_corpus_yields_nothing(self, tmp_path):
        corpus = Corpus(tmp_path)
        assert list(corpus.documents()) == []

    def test_documents_is_repeatable(self, corpus_root):
        corpus = Corpus(corpus_root)
        first = list(corpus.documents())
        second = list(corpus.documents())
        assert {d.path for d in first} == {d.path for d in second}


class TestCorpusDocumentLookup:

    def test_returns_document_by_urn(self, tmp_path):
        tei = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <TEI xmlns="http://www.tei-c.org/ns/1.0">
              <teiHeader>
                <fileDesc>
                  <titleStmt>
                    <title>Agamemnon</title><author>Seneca</author>
                  </titleStmt>
                  <publicationStmt><p>Test</p></publicationStmt>
                  <sourceDesc><p>Test</p></sourceDesc>
                </fileDesc>
              </teiHeader>
              <text xml:lang="lat">
                <body>
                  <div type="edition"
                       n="urn:cts:latinLit:phi1017.phi007.perseus-lat2">
                    <p>text</p>
                  </div>
                </body>
              </text>
            </TEI>
        """)
        make_tei_file(tmp_path, "seneca.xml", tei)
        corpus = Corpus(tmp_path)
        doc = corpus.document("urn:cts:latinLit:phi1017.phi007.perseus-lat2")
        assert isinstance(doc, TEIDocument)
        assert doc.metadata.urn == "urn:cts:latinLit:phi1017.phi007.perseus-lat2"

    def test_raises_key_error_on_unknown_urn(self, corpus_root):
        corpus = Corpus(corpus_root)
        with pytest.raises(KeyError):
            corpus.document("urn:cts:fakeNS:fake.fake.fake")


class TestCorpusOverDataDir:

    @pytest.fixture(scope="class")
    def corpus(self):
        return Corpus(DATA_DIR)

    def test_finds_corpus_fixtures(self, corpus):
        urns = {d.metadata.urn for d in corpus.documents()}
        assert "urn:cts:latinLit:phi1017.phi007.perseus-lat2" in urns
        assert "urn:cts:greekLit:tlg0011.tlg001.perseus-grc2" in urns
        assert "urn:cts:greekLit:tlg0057.tlg069.1st1K-grc1" in urns

    def test_seneca_in_corpus(self, corpus):
        doc = corpus.document(
            "urn:cts:latinLit:phi1017.phi007.perseus-lat2"
        )
        assert doc.metadata.title == "Agamemnon"

    def test_sophocles_in_corpus(self, corpus):
        doc = corpus.document(
            "urn:cts:greekLit:tlg0011.tlg001.perseus-grc2"
        )
        assert doc.metadata.author == "Sophocles"

    def test_galen_in_corpus(self, corpus):
        doc = corpus.document(
            "urn:cts:greekLit:tlg0057.tlg069.1st1K-grc1"
        )
        assert doc.metadata.text_type == "prose"


class TestCorpusInvariants:

    @pytest.fixture(params=list(DATA_DIR.glob("*.xml")),
                    ids=lambda p: p.name)
    def doc_from_corpus(self, request):
        doc = TEIDocument.from_path(request.param)
        if not doc.metadata.urn:
            pytest.skip(f"{request.param.name} has no CTS URN; not a corpus document")
        corpus = Corpus(DATA_DIR)
        return corpus.document(doc.metadata.urn)

    def test_document_has_path(self, doc_from_corpus):
        assert doc_from_corpus.path.exists()

    def test_document_urn_is_non_empty(self, doc_from_corpus):
        assert doc_from_corpus.metadata.urn != ""
