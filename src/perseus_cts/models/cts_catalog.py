"""CTS catalog parser — reads __cts__.xml metadata files.

Provides data classes (CTSGroup, CTSWork, CTSVersion) and a CTSCatalog
that indexes all __cts__.xml files under a directory tree, enabling
lookup of textgroup, work, and version metadata by CTS URN.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from perseus_cts.constants import CTS_NS, XML_PARSER

_CTS_MAP = {"ti": CTS_NS}


@dataclass
class CTSVersion:
    """Metadata for a single edition, translation, or commentary version."""

    urn: str
    work_urn: str
    lang: str
    label: str
    description: str
    version_type: str
    memberof: str | None = None
    about: str | None = None
    source_path: Path | None = None


_DEFAULT_TITLE_LANG = "eng"


@dataclass
class CTSWork:
    """Metadata for a single work, including its versions."""

    urn: str
    group_urn: str
    titles: dict[str, str]
    versions: list[CTSVersion]
    genre: str | None = None
    genre_confidence: str | None = None
    source_path: Path | None = None

    def title_for(self, language: str, default_lang: str = _DEFAULT_TITLE_LANG) -> str:
        """Return the title matching `language`, falling back to `default_lang`.

        Never falls back to whatever title happens to be first in the dict
        (e.g. the Greek or Latin title), since that would be wrong for
        readers of an unrelated language.
        """
        if language and language in self.titles:
            return self.titles[language]
        return self.titles.get(default_lang, "")


@dataclass
class CTSGroup:
    """Metadata for a textgroup (author/collection), including its works."""

    urn: str
    group_names: dict[str, str]
    works: list[CTSWork]
    source_path: Path | None = None


class CTSCatalog:
    """Parses and indexes all __cts__.xml files under one or more root directories.

    Accepts a single path or a list of paths, enabling aggregation across
    multiple corpora (e.g. canonical-greekLit + canonical-latinLit).

    Provides O(1) lookup of CTSGroup, CTSWork, and CTSVersion by URN,
    and helper methods to link editions ↔ translations within a work.
    """

    def __init__(self, roots: Path | str | list[Path | str]) -> None:
        self._roots = [Path(r) for r in (roots if isinstance(roots, list) else [roots])]
        for root in self._roots:
            if not root.exists():
                raise FileNotFoundError(f"CTS catalog root not found: {root}")
        self._groups: dict[str, CTSGroup] = {}
        self._works: dict[str, CTSWork] = {}
        self._versions: dict[str, CTSVersion] = {}
        self._load()

    def _load(self) -> None:
        for root in self._roots:
            for cts_path in sorted(root.rglob("__cts__.xml")):
                try:
                    tree = etree.parse(str(cts_path), XML_PARSER)
                    root_el = tree.getroot()
                    tag = etree.QName(root_el.tag).localname
                    if tag == "textgroup":
                        self._parse_group(root_el, cts_path)
                    elif tag == "work":
                        self._parse_work(root_el, cts_path)
                    elif tag == "TextInventory":
                        for child in root_el:
                            child_tag = etree.QName(child.tag).localname
                            if child_tag == "textgroup":
                                self._parse_group(child, cts_path)
                except Exception:
                    pass

    def _parse_group(self, root: etree._Element, source_path: Path) -> None:
        urn = root.get("urn", "")
        if not urn:
            return
        group_names: dict[str, str] = {}
        for name_el in root.findall("ti:groupname", _CTS_MAP):
            lang = name_el.get("{http://www.w3.org/XML/1998/namespace}lang", "")
            text = (name_el.text or "").strip()
            if lang and text:
                group_names[lang] = text
        self._groups[urn] = CTSGroup(
            urn=urn,
            group_names=group_names,
            works=[],
            source_path=source_path,
        )

    def _parse_work(self, root: etree._Element, source_path: Path) -> None:
        urn = root.get("urn", "")
        group_urn = root.get("groupUrn", "")
        if not urn:
            return

        titles: dict[str, str] = {}
        for title_el in root.findall("ti:title", _CTS_MAP):
            lang = title_el.get("{http://www.w3.org/XML/1998/namespace}lang", "")
            text = (title_el.text or "").strip()
            if lang and text:
                titles[lang] = text

        versions: list[CTSVersion] = []
        for version_type in ("edition", "translation", "commentary"):
            for ver_el in root.findall(f"ti:{version_type}", _CTS_MAP):
                v = self._parse_version(ver_el, version_type, source_path)
                if v is not None:
                    versions.append(v)

        genre_el = root.find("ti:genre", _CTS_MAP)
        genre = (genre_el.text or "").strip() if genre_el is not None else None
        genre_confidence = (
            genre_el.get("confidence", "") if genre_el is not None else None
        )

        work = CTSWork(
            urn=urn,
            group_urn=group_urn,
            titles=titles,
            versions=versions,
            genre=genre,
            genre_confidence=genre_confidence,
            source_path=source_path,
        )
        self._works[urn] = work

        for v in versions:
            self._versions[v.urn] = v

        if group_urn in self._groups:
            self._groups[group_urn].works.append(work)

    def _parse_version(
        self,
        el: etree._Element,
        version_type: str,
        source_path: Path,
    ) -> CTSVersion | None:
        urn = el.get("urn", "")
        work_urn = el.get("workUrn", "")
        if not urn:
            return None
        lang = el.get("{http://www.w3.org/XML/1998/namespace}lang", "")

        label_el = el.find("ti:label", _CTS_MAP)
        label = (label_el.text or "").strip() if label_el is not None else ""

        desc_el = el.find("ti:description", _CTS_MAP)
        description = (desc_el.text or "").strip() if desc_el is not None else ""

        memberof_el = el.find("ti:memberof", _CTS_MAP)
        memberof = (
            memberof_el.get("collection", "") if memberof_el is not None else None
        )

        about_el = el.find("ti:about", _CTS_MAP)
        about = about_el.get("urn") if about_el is not None else None

        return CTSVersion(
            urn=urn,
            work_urn=work_urn,
            lang=lang,
            label=label,
            description=description,
            version_type=version_type,
            memberof=memberof,
            about=about,
            source_path=source_path,
        )

    @property
    def groups(self) -> dict[str, CTSGroup]:
        return self._groups

    @property
    def works(self) -> dict[str, CTSWork]:
        return self._works

    @property
    def versions(self) -> dict[str, CTSVersion]:
        return self._versions

    def group_for(self, urn: str) -> CTSGroup | None:
        if urn in self._groups:
            return self._groups[urn]
        work = self.work_for(urn)
        if work is not None:
            return self._groups.get(work.group_urn)
        return None

    def work_for(self, urn: str) -> CTSWork | None:
        if urn in self._works:
            return self._works[urn]
        version = self._versions.get(urn)
        if version is not None:
            return self._works.get(version.work_urn)
        return None

    def version_for(self, urn: str) -> CTSVersion | None:
        return self._versions.get(urn)

    def translations_of(self, urn: str) -> list[CTSVersion]:
        work = self.work_for(urn)
        if work is None:
            return []
        return [v for v in work.versions if v.version_type == "translation"]

    def editions_of(self, urn: str) -> list[CTSVersion]:
        work = self.work_for(urn)
        if work is None:
            return []
        return [v for v in work.versions if v.version_type == "edition"]

    def commentaries_of(self, urn: str) -> list[CTSVersion]:
        """Return commentary versions whose <ti:about> covers the given work/version urn.

        A commentary's `about` urn may name a whole textgroup, a whole work, or
        a citation subrange of a work, so versions are matched by URN-prefix
        overlap in either direction rather than exact equality.
        """
        work = self.work_for(urn)
        if work is None:
            return []

        return [
            v
            for v in self._versions.values()
            if v.version_type == "commentary"
            and v.about is not None
            and (v.about.startswith(work.urn) or work.urn.startswith(v.about))
        ]
