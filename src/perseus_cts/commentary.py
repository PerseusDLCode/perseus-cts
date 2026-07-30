"""Locate commentary links for a passage via TEI /TEI/standOff/linkGrp.

The pdlrefwk commentary corpus is heterogeneous: <link target="..."> values
range from full CTS URNs ("urn:cts:greekLit:tlg0011.tlg004:463-512 #anchor")
to bare citation ranges ("2.26-2.29 #anchor") that rely on the commentary's
own <ti:about> to supply the implied work. This module normalizes both forms
and matches them against the citation range of the passage being displayed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from perseus_cts.constants import NS, TEI_NS, XML_ID, XML_PARSER
from perseus_cts.models.cts_catalog import CTSCatalog, CTSVersion

_SEG_TAG = f"{{{TEI_NS}}}seg"
_DIV_TAG = f"{{{TEI_NS}}}div"

_SEGMENT = re.compile(r"^(\d*)(.*)$")

# div/@type values known to wrap one commentary entry's lemma/comment <seg>
# pair, keyed by the entry's line/passage reference (@n). Commentary sources
# are heterogeneous TEI conversions we don't control the markup of, so this
# is a recognized-value allow-list to extend as new conventions turn up,
# rather than a convention we can mandate upstream.
_LINE_REF_DIV_TYPES = frozenset({"commline"})


def _parse_segment(segment: str) -> tuple[int, str]:
    match = _SEGMENT.match(segment)
    digits, rest = match.groups() if match else ("", segment)
    return (int(digits), rest) if digits else (-1, rest)


def _parse_ref(ref: str) -> tuple[tuple[int, str], ...]:
    return tuple(_parse_segment(part) for part in ref.split("."))


def _parse_range(citation: str) -> tuple[str, str]:
    start, sep, end = citation.partition("-")
    return (start, end) if sep else (start, start)


def ranges_overlap(a: str, b: str) -> bool:
    """Return True if CTS citation ranges (or single refs) `a` and `b` overlap."""
    if not a or not b:
        return False
    a_start, a_end = _parse_range(a)
    b_start, b_end = _parse_range(b)
    return _parse_ref(a_start) <= _parse_ref(b_end) and _parse_ref(
        b_start
    ) <= _parse_ref(a_end)


def _urns_overlap(a: str, b: str) -> bool:
    return a.startswith(b) or b.startswith(a)


def _line_ref(seg: etree._Element | None) -> str | None:
    """Return the enclosing per-entry div's @n value for `seg`, if any.

    linkGrp targets only carry a coarse section range (e.g. "1-150" for an
    entire commentary section), too coarse to point a reader at a specific
    base-text line. Commentaries structure individual entries inside a div
    whose @type is one of _LINE_REF_DIV_TYPES (e.g. <div type="commline"
    n="LINE">), so that div's @n is the actual per-entry line/passage
    reference.
    """
    if seg is None:
        return None
    for ancestor in seg.iterancestors(_DIV_TAG):
        if ancestor.get("type") in _LINE_REF_DIV_TYPES:
            return ancestor.get("n")
    return None


def _parse_link_target(target: str) -> tuple[str | None, str, str]:
    """Split a <link target="..."> value into (work_urn, citation, anchor_id).

    `work_urn` is None when the target is a bare citation range with no
    "urn:cts:" prefix, in which case the citation is implicitly relative to
    the commentary's own <ti:about> work.
    """
    ref, _, anchor = target.strip().rpartition(" ")
    if not ref:
        ref = target.strip()
        anchor = ""
    anchor_id = anchor.lstrip("#")

    if ref.startswith("urn:cts:"):
        work_urn, _, citation = ref.rpartition(":")
        return work_urn, citation, anchor_id
    return None, ref, anchor_id


@dataclass
class CommentaryLink:
    """One <link> from a commentary's linkGrp that overlaps a displayed passage.

    `lemma` and `comment` are serialized XML (the raw <seg> element, tags
    included) associated with `anchor_id`: the comment is the <seg> whose
    @xml:id equals anchor_id, and the lemma is the <seg> whose @ana equals
    "#{anchor_id}". Either may be None if the commentary doesn't encode that
    pairing for this anchor. Callers render these with their own TEI-to-HTML
    pipeline (e.g. MVP's TEIParser).

    `line_ref` is the @n of the enclosing <div type="commline">, i.e. the
    specific base-text line/passage this entry comments on. It is None when
    the comment <seg> isn't found or isn't nested in a commline div. It is
    finer-grained than `target`'s citation, which only carries the coarse
    section range the whole linkGrp entry was matched against.
    """

    commentary_urn: str
    commentary_label: str
    target: str
    anchor_id: str
    line_ref: str | None = None
    lemma: str | None = None
    comment: str | None = None


@dataclass
class CommentaryLookup:
    """Result of looking up commentary links for a passage."""

    links: list[CommentaryLink] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _version_xml_path(version: CTSVersion) -> Path | None:
    if version.source_path is None:
        return None
    filename = version.urn.rsplit(":", 1)[-1] + ".xml"
    return version.source_path.parent / filename


@dataclass
class _SegIndex:
    """Lookup tables from anchor id to a commentary's lemma/comment <seg> elements.

    Keyed both exactly and case-folded, since the pdlrefwk corpus has
    linkGrp targets and <seg> ids that disagree in case for the same anchor
    (e.g. target "#Θανάτων_497" vs. xml:id "θανάτων_497").
    """

    comment_by_id: dict[str, etree._Element] = field(default_factory=dict)
    comment_by_id_ci: dict[str, etree._Element] = field(default_factory=dict)
    lemma_by_target: dict[str, etree._Element] = field(default_factory=dict)
    lemma_by_target_ci: dict[str, etree._Element] = field(default_factory=dict)

    @classmethod
    def build(cls, root: etree._Element) -> "_SegIndex":
        index = cls()
        for seg in root.iter(_SEG_TAG):
            xml_id = seg.get(XML_ID)
            if xml_id:
                index.comment_by_id.setdefault(xml_id, seg)
                index.comment_by_id_ci.setdefault(xml_id.casefold(), seg)
            ana = seg.get("ana")
            if ana:
                index.lemma_by_target.setdefault(ana, seg)
                index.lemma_by_target_ci.setdefault(ana.casefold(), seg)
        return index

    def comment_for(self, anchor_id: str) -> etree._Element | None:
        seg = self.comment_by_id.get(anchor_id)
        if seg is None:
            seg = self.comment_by_id_ci.get(anchor_id.casefold())
        return seg

    def lemma_for(self, anchor_id: str) -> etree._Element | None:
        target = f"#{anchor_id}"
        seg = self.lemma_by_target.get(target)
        if seg is None:
            seg = self.lemma_by_target_ci.get(target.casefold())
        return seg


def _seg_xml(seg: etree._Element | None) -> str | None:
    if seg is None:
        return None
    return etree.tostring(seg, encoding="unicode", with_tail=False)


def links_for_passage(
    catalog: CTSCatalog, work_urn: str, citation: str
) -> CommentaryLookup:
    """Return commentary links relevant to `citation` within `work_urn`.

    For each commentary associated with the work (via <ti:about>), the
    commentary's TEI file is parsed for /TEI/standOff/linkGrp. A commentary
    missing that element contributes a warning and no links.
    """
    result = CommentaryLookup()

    for commentary in catalog.commentaries_of(work_urn):
        xml_path = _version_xml_path(commentary)
        if xml_path is None or not xml_path.exists():
            result.warnings.append(f"Commentary source not found for {commentary.urn}")
            continue

        try:
            tree = etree.parse(str(xml_path), XML_PARSER)
        except etree.XMLSyntaxError:
            result.warnings.append(f"Commentary {commentary.urn} could not be parsed")
            continue

        root = tree.getroot()
        link_groups = root.findall("tei:standOff/tei:linkGrp", NS)
        if not link_groups:
            result.warnings.append(
                f"{commentary.label or commentary.urn} has no linkGrp; "
                "comments are unavailable"
            )
            continue

        seg_index = _SegIndex.build(root)

        for link_grp in link_groups:
            for link in link_grp.findall("tei:link", NS):
                target = link.get("target", "")
                if not target:
                    continue
                target_work, target_citation, anchor_id = _parse_link_target(target)
                if target_work is not None and not _urns_overlap(target_work, work_urn):
                    continue
                if not ranges_overlap(target_citation, citation):
                    continue
                comment_seg = seg_index.comment_for(anchor_id)
                line_ref = _line_ref(comment_seg)
                # `target_citation` is only the coarse section the whole
                # linkGrp entry belongs to (e.g. "141-496" shared by hundreds
                # of per-word entries spanning that entire section) — it can
                # overlap `citation` even though this particular entry's own
                # line, given by the finer per-entry `line_ref`, falls
                # outside the passage actually being displayed. Re-check
                # against that finer reference when we have one, so e.g.
                # requesting "205-496" doesn't pull in entries for line 141.
                if line_ref is not None and not ranges_overlap(line_ref, citation):
                    continue
                result.links.append(
                    CommentaryLink(
                        commentary_urn=commentary.urn,
                        commentary_label=commentary.label or commentary.urn,
                        target=target,
                        anchor_id=anchor_id,
                        line_ref=line_ref,
                        lemma=_seg_xml(seg_index.lemma_for(anchor_id)),
                        comment=_seg_xml(comment_seg),
                    )
                )

    return result
