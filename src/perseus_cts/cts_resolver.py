from __future__ import annotations

import re
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional, cast

from lxml import etree

from perseus_cts.models import CitationChunk, CitationRecord
from perseus_cts.constants import NS, TEI_NS
from perseus_cts.models.document import LenientTEIDocument


_QUOTE = re.compile(r'(["\'][^"\']*["\'])')
_BARE_ELEMENT = re.compile(r"(?<![:\w@])([A-Za-z_][A-Za-z0-9_\-]*)(?![\w\-:(])")

# TEI's own model.milestoneLike class: empty markers that punctuate a
# document rather than contain it. A citeStructure matching any of these
# chunks by collecting everything *between* consecutive markers (see
# _milestone_chunks), rather than treating each match as a self-contained
# chunk (see _div_chunks).
_MILESTONE_LIKE_ELEMENTS = {"milestone", "pb", "cb", "lb", "gb"}


def _prefix_match_expr(expr: str, prefix: str) -> str:
    """Prefix bare element names in a citeStructure @match expression."""
    parts = _QUOTE.split(expr)
    for i in range(0, len(parts), 2):
        parts[i] = _BARE_ELEMENT.sub(rf"{prefix}:\1", parts[i])
    return "".join(parts)


def _match_local_name(match_expr: str) -> str:
    """Return the local element name of a citeStructure @match expression's
    final path step, stripping any namespace prefix and predicate."""
    last_step = match_expr.strip().split("/")[-1]
    if ":" in last_step:
        last_step = last_step.split(":", 1)[1]
    return last_step.split("[", 1)[0].strip()


def copy_before(
    element: etree._Element,
    stop: etree._Element | None,
) -> etree._Element:
    """Return a deep copy of element with all content at or after stop removed."""
    if stop is None:
        return deepcopy(element)

    new = etree.Element(element.tag, attrib=cast(dict[str, str], element.attrib))
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

    # Comments and PIs are non-content asides that can legally sit directly
    # in body (e.g. an editor's commented-out <div>); their .tag is a Cython
    # function rather than a string, which crashes etree.Element() in
    # copy_before if one is picked as a top-level hit.
    hits = [
        e
        for e in all_elements
        if start < pos[id(e)] < end and isinstance(e.tag, str)
    ]
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


def available_refsDecl_ids(tei_doc: LenientTEIDocument) -> list[str]:
    """Return the xml:id of every citeStructure-bearing refsDecl in a document.

    A document may declare more than one valid citation scheme for the same
    work (e.g. scene/line vs. card-based chunking for a tragedy); each is
    addressed via CTSResolver(tei_doc, refsDecl_id=...)."""
    return cast(
        list[str],
        tei_doc.root.xpath(
            "/tei:TEI/tei:teiHeader/tei:encodingDesc"
            "/tei:refsDecl[tei:citeStructure][@xml:id]/@xml:id",
            namespaces=NS,
        ),
    )


def auto_chunk_units(
    tei_doc: LenientTEIDocument, refsDecl_id: str = "CTS"
) -> list[str]:
    """Return unit names for automatically-derived, shallower chunking schemes.

    A hierarchy nested three or more citeStructure levels deep (e.g.
    book/chapter/section) always resolves an explicit or default chunk level
    at its deepest level, forcing every reader/navigation link to that finest
    granularity. This mirrors the same hierarchy one level shallower (e.g.
    book/chapter alone), so a corpus doesn't need to hand-duplicate its own
    citeStructure tree in a second refsDecl just to expose an intermediate
    navigation depth (contrast with e.g. tragedy's scene/card refsDecl pair,
    which encode two genuinely different citation schemes and so are not
    handled here). Returns [] for a two-level-or-shallower hierarchy, and
    also when ``refsDecl_id`` doesn't resolve (callers needn't guard).
    """
    try:
        resolver = CTSResolver(tei_doc, refsDecl_id=refsDecl_id)
    except ConfigurationError:
        return []
    chain = resolver._deepest_chain()
    if len(chain) < 3:
        return []
    default_chunk_cs = resolver._find_chunk_cs()
    # The two deepest levels are the ones worth exposing as alternate
    # granularities (e.g. book.chapter vs book.chapter.section) — whichever
    # of the two isn't already the configured default. A document may
    # explicitly chunk at either the shallower or the deeper of the pair
    # (compare Thucydides, whose default is the deepest "section" level,
    # against Herodotus, whose default is the shallower "chapter" level),
    # so this can't just assume which direction the auto scheme goes.
    if default_chunk_cs is chain[-1]:
        other = chain[-2]
    elif default_chunk_cs is chain[-2]:
        other = chain[-1]
    else:
        # Default chunk level isn't one of the two deepest — an unusual
        # configuration this heuristic isn't equipped to extend safely.
        return []
    return [other.get("unit", "")]


def section_scheme_unit(
    tei_doc: LenientTEIDocument, refsDecl_id: str = "CTS"
) -> str | None:
    """Return "section" if this refsDecl has an independently-linkable
    "section" citeStructure level, else None.

    Every "section" division is meant to be individually readable, even in a
    hierarchy only two levels deep (e.g. tragedy's chapter/section, which
    auto_chunk_units' three-level threshold skips as too shallow to need an
    auto-derived alternate scheme). This always exposes "section" as its own
    chunk scheme when the document declares one and it isn't already the
    configured default chunk level (which would make a second identical
    scheme pointless). Returns None when ``refsDecl_id`` doesn't resolve or
    the document has no "section" citeStructure level (callers needn't
    guard).
    """
    try:
        resolver = CTSResolver(tei_doc, refsDecl_id=refsDecl_id)
    except ConfigurationError:
        return None
    section_cs = resolver._find_cs_with_attr(resolver._root_cs, "unit", "section")
    if section_cs is None:
        return None
    try:
        default_chunk_cs = resolver._find_chunk_cs()
    except ConfigurationError:
        default_chunk_cs = None
    if section_cs is default_chunk_cs:
        return None
    return "section"


class CTSResolver:
    def __init__(
        self,
        tei_doc: LenientTEIDocument,
        refsDecl_id: str = "CTS",
        chunk_unit: str | None = None,
    ) -> None:
        self._refsDecl_id = (
            f"{refsDecl_id}-{chunk_unit}" if chunk_unit else refsDecl_id
        )
        self._chunk_unit_override = chunk_unit
        root = tei_doc.root

        try:
            self._base_urn = cast(
                list[str],
                root.xpath(
                    "/tei:TEI/tei:text/tei:body/@xml:base",
                    namespaces=NS,
                ),
            )[0]
        except IndexError:
            raise ConfigurationError("Base CTS URN not declared on tei:body/@xml:base")

        try:
            self._root_cs = cast(
                list[etree._Element],
                root.xpath(
                    f"/tei:TEI/tei:teiHeader/tei:encodingDesc"
                    f"/tei:refsDecl[@xml:id='{refsDecl_id}']/tei:citeStructure",
                    namespaces=NS,
                ),
            )[0]
        except IndexError:
            raise ConfigurationError(f"No refsDecl with xml:id='{refsDecl_id}' found")

        self._body = cast(
            list[etree._Element],
            root.xpath(
                "/tei:TEI/tei:text/tei:body",
                namespaces=NS,
            ),
        )[0]

        doc_ns = etree.QName(self._body.tag).namespace
        if doc_ns == TEI_NS:
            self._doc_prefix = "tei"
            self._ns_map = NS
        else:
            self._doc_prefix = "_doc"
            self._ns_map = {**NS, "_doc": doc_ns}

        for _cs in cast(
            list[etree._Element],
            self._root_cs.xpath("tei:citeStructure", namespaces=NS),
        ):
            _explicit = _cs.get("delim")
            if _explicit is not None and _explicit != ":":
                raise ConfigurationError(
                    f"First-level citeStructure declares delim={_explicit!r}; "
                    f"must be ':' (CTS passage separator)"
                )

    def _eval_use(self, cs: etree._Element, cand: etree._Element) -> str:
        """Evaluate a citeStructure @use expression against a candidate element.

        Supports both the @attr shorthand and arbitrary XPath expressions."""
        use_attr = cs.get("use", "@n")
        if use_attr.startswith("@"):
            return cand.get(use_attr[1:], "")
        results = cand.xpath(
            _prefix_match_expr(use_attr, self._doc_prefix),
            namespaces=self._ns_map,
        )
        if not isinstance(results, list):
            return str(results)
        return str(results[0]) if results else ""

    def _match(self, expr: str, context: etree._Element) -> list[etree._Element]:
        """Evaluate a citeStructure match expression against context."""
        return cast(
            list[etree._Element],
            context.xpath(
                _prefix_match_expr(expr, self._doc_prefix),
                namespaces=self._ns_map,
            ),
        )

    def _root_level_cs_list(self) -> list[etree._Element]:
        """Return the citeStructure levels to walk from the document root.

        Normally these are root_cs's children (root_cs itself being a mere
        wrapper matching the document body, e.g. match="/TEI/text/body").
        A document may instead declare a single flat citeStructure with no
        wrapper (e.g. milestone-based chunking) — in that case root_cs IS
        the one level, so it is returned directly."""
        children = cast(
            list[etree._Element],
            self._root_cs.xpath("tei:citeStructure", namespaces=NS),
        )
        return children if children else [self._root_cs]

    def resolve(self, urn: str) -> etree._Element:
        """Return the element identified by the full CTS URN."""

        # split the urn into base and passage citation
        pattern = r"^(.+):([^:]+)$"
        m = re.match(pattern, urn)
        if m is None:
            raise CitationError(f"URN is not valid: {urn}")

        base, passage = m.group(1), m.group(2)
        if base != self._base_urn:
            raise CitationError(
                "URN base does not match document."
                f"Expected {self._base_urn}, got {base}"
            )
        if not passage:
            raise CitationError(f"URN has no passage component: {urn!r}")

        return self._resolve_passage(passage, self._root_level_cs_list(), self._body)

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
        children: list[etree._Element] = cast(
            list[etree._Element], cs.xpath("tei:citeStructure", namespaces=NS)
        )

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
        path = self._find_path_to(element, self._root_level_cs_list(), self._body)
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
            val = self._eval_use(cs, elem)
            parts.append(delim + val)
        return self._base_urn + "".join(parts)

    def _find_path_to(
        self,
        target: etree._Element,
        cs_list: list[etree._Element],
        context: etree._Element,
    ) -> Optional[list[tuple[etree._Element, etree._Element]]]:
        for cs in cs_list:
            match_expr = cs.get("match", "")
            candidates: list[etree._Element] = self._match(match_expr, context)

            if any(cand is target for cand in candidates):
                return [(cs, target)]

            children: list[etree._Element] = cast(
                list[etree._Element], cs.xpath("tei:citeStructure", namespaces=NS)
            )
            if not children:
                continue

            for cand in candidates:
                result = self._find_path_to(target, children, cand)
                if result is not None:
                    return [(cs, cand)] + result

        return None

    @property
    def base_urn(self) -> str:
        return self._base_urn

    @property
    def refsDecl_id(self) -> str:
        return self._refsDecl_id

    def citation_records(self, depth: int = -1) -> Iterator[CitationRecord]:
        """Yield CitationRecord objects at every citation level."""
        yield from self._records_recursive(
            "", self._root_level_cs_list(), self._body, 0, depth
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
            delim = cs.get("delim", ":")
            unit = cs.get("unit", "")
            children: list[etree._Element] = cast(
                list[etree._Element], cs.xpath("tei:citeStructure", namespaces=NS)
            )
            candidates: list[etree._Element] = self._match(match_expr, context)
            for cand in candidates:
                val = self._eval_use(cs, cand)
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

    def toc(self, unit_scheme_map: dict[str, str] | None = None) -> list[dict]:
        """Return the citation hierarchy as nested TOC entries.

        Without ``unit_scheme_map``, this stops at the chunk level (the
        citeStructure level marked n="chunk", or the penultimate level as a
        fallback — see _find_chunk_cs) rather than the deepest level in the
        document, since a TOC built all the way down to e.g. individual
        lines would be too granular for navigation.

        ``unit_scheme_map`` (unit name -> scheme slug, "" for the default/
        no-scheme reading view) instead recurses all the way to the
        document's true leaf, and stamps each entry with a "scheme" key
        (None when that entry's unit isn't in the map). This lets a caller
        with more than one *hierarchically nested* chunking scheme for the
        same underlying tree (e.g. book/chapter and book/chapter/section —
        see perseus_cts.cts_resolver.auto_chunk_units) render one combined
        TOC where every paginated level is independently linkable, not just
        the deepest one. Schemes that aren't a simple depth-truncation of
        the same tree (e.g. tragedy's scene vs. card, matched against
        entirely different elements) should not be included in the map;
        their units simply never appear while walking this tree, so passing
        an unrelated map is harmless but pointless.
        """
        chunk_cs = self._find_chunk_cs()
        return self._toc_level(
            "", self._root_level_cs_list(), self._body, 0, chunk_cs, unit_scheme_map
        )

    def _toc_level(
        self,
        suffix: str,
        cs_list: list[etree._Element],
        context: etree._Element,
        depth: int,
        chunk_cs: etree._Element,
        unit_scheme_map: dict[str, str] | None,
    ) -> list[dict]:
        if not cs_list:
            return []
        cs = cs_list[0]
        cs_children: list[etree._Element] = cast(
            list[etree._Element], cs.xpath("tei:citeStructure", namespaces=NS)
        )
        # When cs has no children of its own, treat remaining siblings as the next level
        sub_cs = cs_children if cs_children else cs_list[1:]
        is_chunk_level = cs is chunk_cs
        # Only stop recursion at the chunk level in the single-scheme
        # (no map) case — with a map, every level down to the true leaf is
        # wanted so each paginated level can carry its own link.
        stop_recursion = unit_scheme_map is None and is_chunk_level
        match_expr = cs.get("match", "")
        delim = cs.get("delim", ":")
        unit = cs.get("unit", "")
        candidates = self._match(match_expr, context)
        entries: list[dict] = []
        for idx, cand in enumerate(candidates, 1):
            val = self._eval_use(cs, cand)
            new_suffix = suffix + delim + val
            subpassages = (
                self._toc_level(
                    new_suffix, sub_cs, cand, depth + 1, chunk_cs, unit_scheme_map
                )
                if sub_cs and not stop_recursion
                else []
            )
            label_val = val or str(idx)
            entry = {
                "depth": depth,
                "index": idx,
                "label": f"{unit.capitalize()} {label_val}",
                "subtype": unit,
                "urn": self._base_urn + new_suffix,
                "subpassages": subpassages,
            }
            if unit_scheme_map is not None:
                entry["scheme"] = unit_scheme_map.get(unit)
            entries.append(entry)
        return entries

    def citations(self, depth: int = -1) -> Iterator[str]:
        """Yield every resolvable CTS URN in document order."""
        yield from (
            r.urn
            for r in self._records_recursive(
                "", self._root_level_cs_list(), self._body, 0, depth
            )
        )

    def chunks(self) -> Iterator[CitationChunk]:
        """Yield CitationChunk objects at the designated chunking level."""
        target_cs = self._find_chunk_cs()
        match_expr = target_cs.get("match", "")
        if _match_local_name(match_expr) in _MILESTONE_LIKE_ELEMENTS:
            yield from self._milestone_chunks(target_cs)
        else:
            yield from self._div_chunks(target_cs)

    def _find_chunk_cs(self) -> etree._Element:
        if self._chunk_unit_override is not None:
            found = self._find_cs_with_attr(
                self._root_cs, "unit", self._chunk_unit_override
            )
            if found is None:
                raise ConfigurationError(
                    f"No citeStructure with unit={self._chunk_unit_override!r} found"
                )
            return found
        found = self._find_cs_with_attr(self._root_cs, "n", "chunk")
        if found is not None:
            return found
        cs = self._penultimate_cs()
        if cs.get("unit") == "line":
            raise ConfigurationError(
                "Default chunk level resolved to unit='line'; add n=\"chunk\" "
                "to the intended chunk-level citeStructure (e.g. scene or card)"
            )
        return cs

    def _find_cs_with_attr(
        self,
        parent_cs: etree._Element,
        attr: str,
        value: str,
    ) -> Optional[etree._Element]:
        for cs in cast(
            list[etree._Element], parent_cs.xpath("tei:citeStructure", namespaces=NS)
        ):
            if cs.get(attr) == value:
                return cs
            found = self._find_cs_with_attr(cs, attr, value)
            if found is not None:
                return found
        return None

    def _deepest_chain(self) -> list[etree._Element]:
        """Return the citeStructure levels from the root wrapper down to the
        deepest (first-child) leaf, in order."""
        path: list[etree._Element] = []
        cs = self._root_cs
        while True:
            children: list[etree._Element] = cast(
                list[etree._Element], cs.xpath("tei:citeStructure", namespaces=NS)
            )
            if not children:
                break
            cs = children[0]
            path.append(cs)
        return path

    def _penultimate_cs(self) -> etree._Element:
        path = self._deepest_chain()
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
            cast(
                list[etree._Element],
                self._root_cs.xpath("tei:citeStructure", namespaces=NS),
            ),
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
