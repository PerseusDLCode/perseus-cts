"""Tests for perseus_cts.chunker.Chunker."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from perseus_cts.chunker import Chunker
from perseus_cts.models.document import LenientTEIDocument

DATA_DIR = Path(__file__).parent / "data"
TRACHINIAE_PATH = DATA_DIR / "tlg0011.tlg001.perseus-grc2.xml"


@pytest.fixture
def trachiniae_doc():
    return LenientTEIDocument(TRACHINIAE_PATH)


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
