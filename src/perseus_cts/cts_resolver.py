from __future__ import annotations

import re
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional

from lxml import etree

from perseus_cts.models import CitationChunk, CitationRecord
from perseus_cts.constants import NS, TEI_NS
from perseus_cts.models.document import LenientTEIDocument


_QUOTE = re.compile(r'(["\'][^"\']*["\'])')
_BARE_ELEMENT = re.compile(r'(?<![:\w@])([A-Za-z_][A-Za-z0-9_\-]*)(?![\w\-:(])')


def _prefix_match_expr(expr: str, prefix: str) -> str:
    """Prefix bare element names in a citeStructure @match expression."""
    parts = _QUOTE.split(expr)
    for i in range(0, len(parts), 2):
        parts[i] = _BARE_ELEMENT.sub(rf'{prefix}:\1', parts[i])
    return ''.join(parts)


def copy_before(
    element: etree._Element,
    stop: etree._Element | None,
) -> etree._Element:
    """Return a deep copy of element with all content at or after stop removed."""
    if stop is None:
        return deepcopy(element)

    new = etree.Element(element.tag, attrib=element.attrib)
    new.text = element.text
    for child in element:
        if child is stop:
            break
        if any(desc is stop for desc in child.iter()):
            new.append(copy_before(child, stop))
            break
        new.append(deepcopy(child))
    return new


def elements_between(
    root: etree._Element,
    start_ms: etree._Element,
    end_ms: etree._Element | None,
) -> list[etree._Element]:
    """Return top-level elements between two milestones in document order."""
    all_elements = list(root.iter())
    pos = {id(e): i for i, e in enumerate(all_elements)}

    start = pos[id(start_ms)]
    end = pos[id(end_ms)] if end_ms is not None else len(all_elements)

    hits = [e for e in all_elements if start < pos[id(e)] < end]
    hit_ids = {id(e) for e in hits}
    top = [e for e in hits if not any(id(a) in hit_ids for a in e.iterancestors())]

    return [copy_before(el, end_ms) for el in top]


@dataclass
class _CSNode:
    """One (citeStructure, candidate-element) pair at a single hierarchy level."""

    cs: etree._Element
    element: etree._Element
    suffix: str
    val: str
    unit: str
    children: list[etree._Element]


class ConfigurationError(Exception):
    """Raised when no usable citeStructure can be found or selected."""


class CitationError(Exception):
    """Raised when a URN is syntactically invalid or resolves to nothing."""


class CTSResolver:

    def __init__(
        self,
        tei_doc: LenientTEIDocument,
        refsDecl_id: str = "CTS",
    ) -> None:
        root = tei_doc.root

        try:
            self._base_urn = root.xpath(
                "/tei:TEI/tei:text/tei:body/@xml:base",
                namespaces=NS,
            )[0]
        except IndexError:
            raise ConfigurationError("Base CTS URN not declared on tei:body/@xml:base")

        try:
            self._root_cs = root.xpath(
                f"/tei:TEI/tei:teiHeader/tei:encodingDesc"
                f"/tei:refsDecl[@xml:id='{refsDecl_id}']/tei:citeStructure",
                namespaces=NS,
            )[0]
        except IndexError:
            raise ConfigurationError(
                f"No refsDecl with xml:id='{refsDecl_id}' found"
            )

        self._body = root.xpath(
            "/tei:TEI/tei:text/tei:body",
            namespaces=NS,
        )[0]

        doc_ns = etree.QName(self._body.tag).namespace
        if doc_ns == TEI_NS:
            self._doc_prefix = 'tei'
            self._ns_map = NS
        else:
            self._doc_prefix = '_doc'
            self._ns_map = {**NS, '_doc': doc_ns}

    def _match(self, expr: str, context: etree._Element) -> list:
        """Evaluate a citeStructure match expression against context."""
        return context.xpath(
            _prefix_match_expr(expr, self._doc_prefix),
            namespaces=self._ns_map,
        )

    def resolve(self, urn: str) -> etree._Element:
        """Return the element identified by the full CTS URN."""

        # split the urn into base and passage citation
        pattern = r'^(.+):([^:]+)$'
        m = re.match(pattern, urn)
        if m is None:
            raise CitationError(f"URN is not valid: {urn}")
        
        
        base, passage = m.group(1), m.group(2)
        if base != self._base_urn:
            raise CitationError("URN base does not match document."
                                f"Expected {self._base_urn}, got {base}")
        if not passage:
            raise CitationError(f"URN has no passage component: {urn!r}")

        return self._resolve_passage(
            passage,
            self._root_cs.xpath("tei:citeStructure", namespaces=NS),
            self._body,
        )

    def _resolve_passage(
        self,
        passage: str,
        cs_list: list[etree._Element],
        context: etree._Element,
    ) -> etree._Element:
        last_error: CitationError = CitationError(f"Cannot resolve passage {passage!r}")
        for cs in cs_list:
            try:
                return self._resolve_with_cs(passage, cs, context)
            except CitationError as exc:
                last_error = exc
        raise last_error

    def _resolve_with_cs(
        self,
        passage: str,
        cs: etree._Element,
        context: etree._Element,
    ) -> etree._Element:
        children = cs.xpath("tei:citeStructure", namespaces=NS)

        if children:
            next_delim = children[0].get("delim", ".")
            token, sep, rest = passage.partition(next_delim)
            if not sep:
                token = passage
                rest = ""
        else:
            token = passage
            rest = ""

        match_expr = cs.get("match", "")
        use_attr = cs.get("use", "@n")
        candidates: list[etree._Element] = self._match(match_expr, context)

        matched: Optional[etree._Element] = None
        if use_attr.startswith("@"):
            attr_name = use_attr[1:]
            for cand in candidates:
                if cand.get(attr_name) == token:
                    matched = cand
                    break

        if matched is None:
            raise CitationError(
                f"No element with {use_attr}={token!r} via match={match_expr!r}"
            )

        if rest:
            if not children:
                raise CitationError(
                    f"Passage has trailing component {rest!r} "
                    f"but citation hierarchy is exhausted"
                )
            return self._resolve_passage(rest, children, matched)
        return matched

    def generate(self, element: etree._Element) -> str:
        """Return the full CTS URN for a citable element."""
        path = self._find_path_to(element, self._root_cs, self._body)
        if path is None:
            raise CitationError(
                f"Element <{etree.QName(element.tag).localname}> "
                f"is not reachable via the active citeStructure"
            )
        parts: list[str] = []
        for cs, elem in path:
            delim = cs.get("delim")
            if delim is None:
                raise ConfigurationError(
                    f"<citeStructure unit={cs.get('unit')!r}> is missing required @delim"
                )
            use_attr = cs.get("use", "@n")
            val = elem.get(use_attr[1:], "") if use_attr.startswith("@") else ""
            parts.append(delim + val)
        return self._base_urn + "".join(parts)

    def _find_path_to(
        self,
        target: etree._Element,
        parent_cs: etree._Element,
        context: etree._Element,
    ) -> Optional[list[tuple[etree._Element, etree._Element]]]:
        for cs in parent_cs.xpath("tei:citeStructure", namespaces=NS):
            match_expr = cs.get("match", "")
            candidates: list[etree._Element] = self._match(match_expr, context)

            if any(cand is target for cand in candidates):
                return [(cs, target)]

            for cand in candidates:
                result = self._find_path_to(target, cs, cand)
                if result is not None:
                    return [(cs, cand)] + result

        return None

    @property
    def base_urn(self) -> str:
        return self._base_urn

    def citation_records(self, depth: int = -1) -> Iterator[CitationRecord]:
        """Yield CitationRecord objects at every citation level."""
        yield from self._records_recursive(
            "", self._root_cs.xpath("tei:citeStructure", namespaces=NS), self._body, 0, depth
        )

    def _walk_cs(
        self,
        suffix: str,
        cs_list: list[etree._Element],
        context: etree._Element,
    ) -> Iterator[_CSNode]:
        """Shared traversal primitive for records, toc, and chunk collection."""
        for cs in cs_list:
            match_expr = cs.get("match", "")
            use_attr = cs.get("use", "@n")
            delim = cs.get("delim", ":")
            unit = cs.get("unit", "")
            children = cs.xpath("tei:citeStructure", namespaces=NS)
            candidates: list[etree._Element] = self._match(match_expr, context)
            for cand in candidates:
                val = cand.get(use_attr[1:], "") if use_attr.startswith("@") else ""
                yield _CSNode(
                    cs=cs,
                    element=cand,
                    suffix=suffix + delim + val,
                    val=val,
                    unit=unit,
                    children=children,
                )

    def _records_recursive(
        self,
        suffix: str,
        cs_list: list[etree._Element],
        context: etree._Element,
        current_depth: int,
        max_depth: int,
    ) -> Iterator[CitationRecord]:
        for node in self._walk_cs(suffix, cs_list, context):
            if max_depth == -1 or current_depth <= max_depth:
                yield CitationRecord(
                    urn=self._base_urn + node.suffix,
                    unit=node.unit,
                    depth=current_depth,
                )
            if (max_depth == -1 or current_depth < max_depth) and node.children:
                yield from self._records_recursive(
                    node.suffix,
                    node.children,
                    node.element,
                    current_depth + 1,
                    max_depth,
                )

    def toc(self) -> list[dict]:
        """Return the full citation hierarchy as a list of nested TOC entries."""
        return self._toc_level(
            "", self._root_cs.xpath("tei:citeStructure", namespaces=NS), self._body, 0
        )

    def _toc_level(
        self,
        suffix: str,
        cs_list: list[etree._Element],
        context: etree._Element,
        depth: int,
    ) -> list[dict]:
        entries: list[dict] = []
        for idx, node in enumerate(self._walk_cs(suffix, cs_list, context), 1):
            label_val = node.val or str(idx)
            subpassages = (
                self._toc_level(node.suffix, node.children, node.element, depth + 1)
                if node.children
                else []
            )
            entries.append(
                {
                    "depth": depth,
                    "index": idx,
                    "label": f"{node.unit.capitalize()} {label_val}",
                    "subtype": node.unit,
                    "urn": self._base_urn + node.suffix,
                    "subpassages": subpassages,
                }
            )
        return entries

    def citations(self, depth: int = -1) -> Iterator[str]:
        """Yield every resolvable CTS URN in document order."""
        yield from (
            r.urn for r in self._records_recursive(
                "", self._root_cs.xpath("tei:citeStructure", namespaces=NS), self._body, 0, depth
            )
        )

    def chunks(self) -> Iterator[CitationChunk]:
        """Yield CitationChunk objects at the designated chunking level."""
        target_cs = self._find_chunk_cs()
        match_expr = target_cs.get("match", "")
        if "milestone" in match_expr:
            yield from self._milestone_chunks(target_cs)
        else:
            yield from self._div_chunks(target_cs)

    def _find_chunk_cs(self) -> etree._Element:
        found = self._find_cs_with_attr(self._root_cs, "n", "chunk")
        if found is not None:
            return found
        return self._penultimate_cs()

    def _find_cs_with_attr(
        self,
        parent_cs: etree._Element,
        attr: str,
        value: str,
    ) -> Optional[etree._Element]:
        for cs in parent_cs.xpath("tei:citeStructure", namespaces=NS):
            if cs.get(attr) == value:
                return cs
            found = self._find_cs_with_attr(cs, attr, value)
            if found is not None:
                return found
        return None

    def _penultimate_cs(self) -> etree._Element:
        path: list[etree._Element] = []
        cs = self._root_cs
        while True:
            children = cs.xpath("tei:citeStructure", namespaces=NS)
            if not children:
                break
            cs = children[0]
            path.append(cs)
        if not path:
            return self._root_cs
        if len(path) == 1:
            return path[0]
        return path[-2]

    def _div_chunks(self, target_cs: etree._Element) -> Iterator[CitationChunk]:
        unit = target_cs.get("unit", "")
        pairs = self._candidates_at_level(target_cs)
        for i, (elem, urn) in enumerate(pairs):
            yield CitationChunk(
                base_urn=urn.rsplit(":", 1)[0],
                cts_urn=urn,
                unit=unit,
                elements=[elem],
                prev_urn=pairs[i - 1][1] if i > 0 else None,
                next_urn=pairs[i + 1][1] if i + 1 < len(pairs) else None,
            )

    def _milestone_chunks(self, target_cs: etree._Element) -> Iterator[CitationChunk]:
        match_expr = target_cs.get("match", "")
        use_attr = target_cs.get("use", "@n")
        unit = target_cs.get("unit", "")
        delim = target_cs.get("delim", " ")

        milestones: list[etree._Element] = self._match(match_expr, self._body)

        def _urn(ms: etree._Element) -> str:
            val = ms.get(use_attr[1:], "") if use_attr.startswith("@") else ""
            return self._base_urn + delim + val

        for i, ms in enumerate(milestones):
            ms_next = milestones[i + 1] if i + 1 < len(milestones) else None
            yield CitationChunk(
                base_urn=self._base_urn,
                cts_urn=_urn(ms),
                unit=unit,
                elements=elements_between(self._body, ms, ms_next),
                prev_urn=_urn(milestones[i - 1]) if i > 0 else None,
                next_urn=_urn(ms_next) if ms_next is not None else None,
            )

    def _candidates_at_level(
        self,
        target_cs: etree._Element,
    ) -> list[tuple[etree._Element, str]]:
        result: list[tuple[etree._Element, str]] = []
        self._collect_cs_elements(
            "",
            self._root_cs.xpath("tei:citeStructure", namespaces=NS),
            self._body,
            target_cs,
            result,
        )
        return result

    def _collect_cs_elements(
        self,
        suffix: str,
        cs_list: list[etree._Element],
        context: etree._Element,
        target_cs: etree._Element,
        result: list[tuple[etree._Element, str]],
    ) -> None:
        for node in self._walk_cs(suffix, cs_list, context):
            if node.cs is target_cs:
                result.append((node.element, self._base_urn + node.suffix))
            elif node.children:
                self._collect_cs_elements(
                    node.suffix, node.children, node.element, target_cs, result
                )
