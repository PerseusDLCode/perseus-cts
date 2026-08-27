from __future__ import annotations

import re
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Optional, cast

from lxml import etree

from perseus_cts.constants import NS, TEI_NS, XML_NS
from perseus_cts.models import CitationChunk, CitationRecord
from perseus_cts.models.document import LenientTEIDocument

_QUOTE = re.compile(r'(["\'][^"\']*["\'])')
_BARE_ELEMENT = re.compile(r"(?<![:\w@])([A-Za-z_][A-Za-z0-9_\-]*)(?![\w\-:(])")

# TEI's own model.milestoneLike class: empty markers that punctuate a
# document rather than contain it. A citeStructure matching any of these
# chunks by collecting everything *between* consecutive markers (see
# _milestone_chunks), rather than treating each match as a self-contained
# chunk (see _div_chunks).
_MILESTONE_LIKE_ELEMENTS = {"milestone", "pb", "cb", "lb", "gb"}


def _attr_name(attr: str) -> str:
    """Resolve a citeStructure @use/@match attribute name (e.g. from the
    "@xml:id" shorthand) to the form etree.Element.get() actually accepts.

    lxml's .get() only recognizes the "xml:" prefix via Clark notation
    ("{http://www.w3.org/XML/1998/namespace}id"), not the literal string
    "xml:id" -- passing the prefixed form through unchanged always misses,
    silently returning "" for every element (e.g. use="@xml:id" on a
    milestone-based citeStructure)."""
    if attr.startswith("xml:"):
        return f"{{{XML_NS}}}{attr[4:]}"
    return attr


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


def _tail_copy(
    parent: etree._Element,
    marker: etree._Element,
    stop: etree._Element | None,
) -> tuple[etree._Element | None, bool]:
    """Copy of `parent` holding only the content after `marker` (a direct
    child of parent, whose own .tail starts the copy) and before `stop` (a
    descendant of parent, if given).

    Returns (copy, stop_found); copy is None when there is nothing after
    `marker` within `parent` before `stop`/parent's end, so the caller
    doesn't have to filter out empty shells."""
    new = etree.Element(parent.tag, attrib=cast(dict[str, str], parent.attrib))
    new.text = marker.tail
    has_content = bool(marker.tail and marker.tail.strip())
    seen_marker = False
    stop_found = False
    for child in parent:
        if not seen_marker:
            if child is marker:
                seen_marker = True
            continue
        if child is stop:
            stop_found = True
            break
        if stop is not None and any(desc is stop for desc in child.iter()):
            new.append(copy_before(child, stop))
            has_content = True
            stop_found = True
            break
        new.append(deepcopy(child))
        has_content = True
    if not has_content:
        return None, stop_found
    return new, stop_found


def elements_between(
    root: etree._Element,
    start_ms: etree._Element,
    end_ms: etree._Element | None,
) -> list[etree._Element]:
    """Return top-level elements between two milestones in document order,
    reopening any ancestor elements the milestones interrupt.

    A milestone marking a chunk boundary is frequently *inside* running
    prose (e.g. a chapter break mid-<p>) rather than a direct sibling of
    the content it delimits, so this can't simply scan flat document
    position: content immediately after start_ms is that same paragraph's
    tail text and later siblings, not a self-contained "hit" element of
    its own. This walks start_ms's ancestor chain from the bottom up,
    peeling off "everything after this point" at each level (via
    _tail_copy) until end_ms is found or the walk reaches `root`, then
    continues across `root`'s own following siblings the same way
    copy_before already does for a single-container stop point."""
    fragments: list[etree._Element] = []

    node = start_ms
    parent = node.getparent()
    while parent is not None and parent is not root:
        frag, stop_found = _tail_copy(parent, node, end_ms)
        if frag is not None:
            fragments.append(frag)
        if stop_found:
            return fragments
        node = parent
        parent = node.getparent()

    for sib in node.itersiblings():
        if not isinstance(sib.tag, str):
            continue
        if sib is end_ms:
            break
        if end_ms is not None and any(desc is end_ms for desc in sib.iter()):
            fragments.append(copy_before(sib, end_ms))
            break
        fragments.append(deepcopy(sib))

    return fragments


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
        self._refsDecl_id = f"{refsDecl_id}-{chunk_unit}" if chunk_unit else refsDecl_id
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

    def _eval_use(
        self,
        cs: etree._Element,
        cand: etree._Element,
        context: etree._Element | None = None,
    ) -> str:
        """Evaluate a citeStructure @use expression against a candidate element.

        Supports the @attr shorthand, the TEI-spec-sanctioned positional
        function use="position()", and arbitrary XPath expressions.

        position() has no meaning evaluated as a one-off query against a
        single element (lxml raises "Invalid context position") -- per the
        spec it names the candidate's 1-based rank among everything cs's own
        @match selected from ``context``, so it must be computed from that
        candidate list rather than handed to cand.xpath() like other @use
        expressions. This only recognizes the exact, unadorned "position()"
        form (the one seen in practice, e.g. Shakespeare's globe
        citeStructures); position() embedded in a larger expression (e.g.
        concat('L', position())) isn't given real XPath context-position
        semantics here and would evaluate as if position() answers node-set
        size 1's position, i.e. always "1"."""
        use_attr = cs.get("use", "@n")
        if use_attr.startswith("@"):
            return cand.get(_attr_name(use_attr[1:]), "")
        if use_attr.strip() == "position()" and context is not None:
            candidates = self._match(cs.get("match", ""), context)
            for i, c in enumerate(candidates, 1):
                if c is cand:
                    return str(i)
            return ""
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
        for cand in candidates:
            if self._eval_use(cs, cand, context) == token:
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
        for cs, elem, ctx in path:
            delim = cs.get("delim")
            if delim is None:
                raise ConfigurationError(
                    f"<citeStructure unit={cs.get('unit')!r}> is missing required @delim"
                )
            val = self._eval_use(cs, elem, ctx)
            parts.append(delim + val)
        return self._base_urn + "".join(parts)

    def _find_path_to(
        self,
        target: etree._Element,
        cs_list: list[etree._Element],
        context: etree._Element,
    ) -> Optional[list[tuple[etree._Element, etree._Element, etree._Element]]]:
        for cs in cs_list:
            match_expr = cs.get("match", "")
            candidates: list[etree._Element] = self._match(match_expr, context)

            if any(cand is target for cand in candidates):
                return [(cs, target, context)]

            children: list[etree._Element] = cast(
                list[etree._Element], cs.xpath("tei:citeStructure", namespaces=NS)
            )
            if not children:
                continue

            for cand in candidates:
                result = self._find_path_to(target, children, cand)
                if result is not None:
                    return [(cs, cand, context)] + result

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
                val = self._eval_use(cs, cand, context)
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
        if (
            unit_scheme_map is None
            and chunk_cs is self._root_cs
            and self._is_wrapper_cs(chunk_cs)
        ):
            # The whole document is the one chunk (see _whole_document_chunk)
            # — there is nothing beneath it to page between.
            return []
        branches = self._chunk_branches(chunk_cs)
        # Every structural sibling stops recursion at its own chunking
        # level, same as chunks() -- for the branch owning chunk_cs that's
        # chunk_cs itself; every other structural sibling (e.g. a
        # "prologue" that declares its own nested "line" citeStructure
        # purely for fine-grained citation, mirroring act > scene > line)
        # stops at _branch_chunk_cs(cs), so that optional deeper level
        # doesn't leak into the TOC as if it were real subpassages.
        stop_cs = {
            chunk_cs if self._branch_contains(cs, chunk_cs) else self._branch_chunk_cs(cs)
            for cs in branches
        }
        return self._toc_level("", branches, self._body, 0, stop_cs, unit_scheme_map)

    def _toc_level(
        self,
        suffix: str,
        cs_list: list[etree._Element],
        context: etree._Element,
        depth: int,
        stop_cs: set[etree._Element],
        unit_scheme_map: dict[str, str] | None,
    ) -> list[dict]:
        if not cs_list:
            return []
        # A level may hold more than one citeStructure sibling (e.g. a
        # play's act/induction/prologue/epilogue/chorus, all matched
        # against the same body context) -- these are alternative unit
        # types occupying the same structural level, not a chain, so every
        # one of them must be matched and walked (mirrors _walk_cs), not
        # just cs_list[0].
        tagged_entries: list[tuple[etree._Element, dict]] = []
        for cs in cs_list:
            cs_children: list[etree._Element] = cast(
                list[etree._Element], cs.xpath("tei:citeStructure", namespaces=NS)
            )
            is_chunk_level = cs in stop_cs
            # Only stop recursion at the chunk level in the single-scheme
            # (no map) case — with a map, every level down to the true leaf
            # is wanted so each paginated level can carry its own link.
            stop_recursion = unit_scheme_map is None and is_chunk_level
            match_expr = cs.get("match", "")
            delim = cs.get("delim", ":")
            unit = cs.get("unit", "")
            candidates = self._match(match_expr, context)
            for idx, cand in enumerate(candidates, 1):
                val = self._eval_use(cs, cand, context)
                new_suffix = suffix + delim + val
                subpassages = (
                    self._toc_level(
                        new_suffix, cs_children, cand, depth + 1, stop_cs, unit_scheme_map
                    )
                    if cs_children and not stop_recursion
                    else []
                )
                label_val = val or str(idx)
                # Tragedy's "scene" divs (episode/choral/etc.) don't use @n for
                # citation -- `use` above computes a line range instead -- so
                # @n is free for an editor to hand-author an explicit display
                # label (e.g. n="Parodos", n="First Stasimon", n="Monody") on
                # divs they've actually checked. Only scene-unit divs honor
                # this: other schemes (e.g. Thucydides book/chapter/section)
                # already use @n to build the citation itself via `use="@n"`,
                # so overriding their label here would be redundant, not new
                # behavior, but keeping the override scoped to "scene" avoids
                # any chance of it doing something unintended for those.
                explicit_label = cand.get("n") if unit == "scene" else None
                entry = {
                    "depth": depth,
                    "index": idx,
                    "label": explicit_label or f"{unit.capitalize()} {label_val}",
                    "subtype": unit,
                    "urn": self._base_urn + new_suffix,
                    "subpassages": subpassages,
                }
                if unit_scheme_map is not None:
                    entry["scheme"] = unit_scheme_map.get(unit)
                tagged_entries.append((cand, entry))

        if len(cs_list) > 1:
            # Sibling unit types can interleave in the source document
            # (e.g. a "prologue" div before "act" 1, or an "epilogue" div
            # after the last act) -- restore document order across them.
            # context.iter() walks in document order, so a single pass
            # gives every matched candidate's relative position regardless
            # of which citeStructure or how deep beneath context it matched.
            doc_order = {id(el): i for i, el in enumerate(context.iter())}
            tagged_entries.sort(key=lambda pair: doc_order.get(id(pair[0]), 0))

        return [entry for _, entry in tagged_entries]

    def citations(self, depth: int = -1) -> Iterator[str]:
        """Yield every resolvable CTS URN in document order."""
        yield from (
            r.urn
            for r in self._records_recursive(
                "", self._root_level_cs_list(), self._body, 0, depth
            )
        )

    def chunks(self) -> Iterator[CitationChunk]:
        """Yield CitationChunk objects at the designated chunking level.

        ``_find_chunk_cs`` locates one primary target level (the
        citeStructure marked n="chunk", or the usual penultimate-level
        fallback) by searching the *whole* citeStructure tree, which is
        correct as long as the tree has a single root-level branch. A
        document like a play, whose refsDecl declares "act" (containing
        the chunked "scene" level) alongside structural siblings such as
        "prologue"/"induction"/"epilogue"/"chorus" (see _chunk_branches),
        has more than one such branch -- each of those siblings has no
        chunked descendant of its own and would silently contribute zero
        chunks if only the primary target were used. Every other
        *structural* root-level branch (see _chunk_branches) is therefore
        given its own natural chunking level (_branch_chunk_cs) and all
        branches' chunks are merged into one document-ordered sequence, so
        a reader can actually open (and page prev/next through) a
        "Prologue" or "Induction" the same as any scene.
        """
        target_cs = self._find_chunk_cs()
        if target_cs is self._root_cs and self._is_wrapper_cs(target_cs):
            yield self._whole_document_chunk(target_cs)
            return

        branches = self._chunk_branches(target_cs)
        branch_targets = [
            target_cs if self._branch_contains(cs, target_cs) else self._branch_chunk_cs(cs)
            for cs in branches
        ]

        if len(branch_targets) == 1:
            yield from self._chunks_for_target(branch_targets[0])
            return

        all_chunks = [
            chunk for bt in branch_targets for chunk in self._chunks_for_target(bt)
        ]
        doc_order = {id(el): i for i, el in enumerate(self._body.iter())}
        all_chunks.sort(key=lambda c: doc_order.get(id(c.elements[0]), 0))

        for i, chunk in enumerate(all_chunks):
            chunk.prev_urn = all_chunks[i - 1].cts_urn if i > 0 else None
            chunk.next_urn = all_chunks[i + 1].cts_urn if i + 1 < len(all_chunks) else None
            yield chunk

    def _chunk_branches(self, chunk_cs: etree._Element) -> list[etree._Element]:
        """Return the root-level citeStructure branches that get their own
        toc()/chunks() entries.

        Most documents have exactly one branch, returned unchanged. A
        document may declare more (see _root_level_cs_list) for two very
        different reasons, which this must tell apart:

        - Genuine structural divisions, matched against the same element
          type as the branch that owns ``chunk_cs`` -- e.g. a play's
          "prologue"/"induction"/"epilogue"/"chorus", declared as
          div-matching siblings of "act" (which contains the chunked
          "scene" level). These belong in the TOC and get their own
          chunks (see _branch_chunk_cs), same as any scene.

        - An alternate, finer-grained citation path layered on top of the
          real structure -- overwhelmingly a "line" citeStructure matching
          bare ``l``/content elements already reachable *inside* the
          chunked branch (the extremely common card+line / scene+line
          pattern across this corpus). Walking this as its own branch
          would flood the TOC and filesystem with one entry per line; it
          stays resolvable via resolve()/generate()/citations(), just not
          listed or chunked on its own.

        The heuristic: a sibling only counts as a structural division when
        its own @match targets the same element type as the branch owning
        the chunk level.
        """
        root_list = self._root_level_cs_list()
        if len(root_list) == 1:
            return root_list
        owning_branch = next(
            (cs for cs in root_list if self._branch_contains(cs, chunk_cs)), None
        )
        if owning_branch is None:
            return root_list
        owning_name = _match_local_name(owning_branch.get("match", ""))
        return [
            cs
            for cs in root_list
            if cs is owning_branch or _match_local_name(cs.get("match", "")) == owning_name
        ]

    def _chunks_for_target(self, target_cs: etree._Element) -> Iterator[CitationChunk]:
        match_expr = target_cs.get("match", "")
        if _match_local_name(match_expr) in _MILESTONE_LIKE_ELEMENTS:
            yield from self._milestone_chunks(target_cs)
        else:
            yield from self._div_chunks(target_cs)

    def _branch_contains(
        self, branch_cs: etree._Element, target_cs: etree._Element
    ) -> bool:
        """True when ``target_cs`` is ``branch_cs`` itself or one of its
        descendant citeStructure levels."""
        if branch_cs is target_cs:
            return True
        return any(
            self._branch_contains(child, target_cs)
            for child in cast(
                list[etree._Element],
                branch_cs.xpath("tei:citeStructure", namespaces=NS),
            )
        )

    def _branch_chunk_cs(self, branch_cs: etree._Element) -> etree._Element:
        """Return the chunking-level citeStructure for one root-level
        branch: the descendant explicitly marked n="chunk" within it, or
        (absent one) branch_cs itself.

        Unlike the primary branch (whose _find_chunk_cs fallback descends
        to the *penultimate* level when nothing is explicitly marked --
        appropriate there because self._root_cs is always a throwaway
        wrapper, never itself a real citable level), branch_cs here is
        already a real, independently matchable level -- e.g. a play's
        "prologue", which may declare its own nested "line" citeStructure
        purely for fine-grained citation (mirroring "act" > "scene" >
        "line"), without ever marking a chunk level of its own. Absent an
        explicit n="chunk", the sanest default is branch_cs itself (one
        chunk per matched prologue/induction/epilogue/chorus div), not an
        auto-descent into that finer level -- descending would either
        over-fragment a branch several levels deep or, for a single
        nested child like "line", silently produce one chunk per line.
        """
        if branch_cs.get("n") == "chunk":
            return branch_cs
        found = self._find_cs_with_attr(branch_cs, "n", "chunk")
        if found is not None:
            return found
        return branch_cs

    def _is_wrapper_cs(self, cs: etree._Element) -> bool:
        """True when ``cs`` merely wraps deeper citeStructure levels (e.g.
        the conventional match="/TEI/text/body" top level) rather than
        being itself a real, matchable citation level.

        A flat, single-level scheme (e.g. CTS-card's milestone-based card
        citeStructure) has no nested tei:citeStructure children, so
        ``self._root_cs`` there already *is* the one real level — n="chunk"
        found on it must resolve through the normal div/milestone chunk
        machinery, not _whole_document_chunk (which only applies when
        root_cs is a genuine non-matchable wrapper around child levels)."""
        return bool(cs.xpath("tei:citeStructure", namespaces=NS))

    def _whole_document_chunk(self, target_cs: etree._Element) -> CitationChunk:
        """Return the single CitationChunk for a document whose n="chunk" is
        declared on the refsDecl's top-level wrapper citeStructure itself
        (e.g. a short, undivided work like Horace's Ars Poetica), rather
        than on some citeStructure beneath it.

        The wrapper's own @match/@use (conventionally
        "/TEI/text/body"/"@xml:base") is pure document-structure
        boilerplate shared by every citeStructure in the corpus, and
        _root_level_cs_list always skips it when walking citation levels —
        it carries no per-chunk value worth reading here. "1" stands in as
        the sole passage token, keeping cts_urn in the same base_urn:passage
        shape every other chunk (and _chunk_filename) expects, since there
        is exactly one chunk to number.
        """
        return CitationChunk(
            base_urn=self._base_urn,
            cts_urn=f"{self._base_urn}:1",
            unit=target_cs.get("unit", ""),
            elements=list(self._body),
        )

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
        if self._root_cs.get("n") == "chunk":
            return self._root_cs
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
        return self._deepest_chain_in(self._root_cs)

    def _deepest_chain_in(self, cs: etree._Element) -> list[etree._Element]:
        """Return the citeStructure levels from ``cs`` down to its deepest
        (first-child) leaf, in order -- the branch-scoped generalization of
        _deepest_chain, used by _branch_chunk_cs for siblings of the
        document's primary root-level branch."""
        path: list[etree._Element] = []
        node = cs
        while True:
            children: list[etree._Element] = cast(
                list[etree._Element], node.xpath("tei:citeStructure", namespaces=NS)
            )
            if not children:
                break
            node = children[0]
            path.append(node)
        return path

    def _penultimate_cs(self) -> etree._Element:
        return self._penultimate_in(self._root_cs)

    def _penultimate_in(self, cs: etree._Element) -> etree._Element:
        path = self._deepest_chain_in(cs)
        if not path:
            return cs
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

        def _val(ms: etree._Element) -> str:
            return ms.get(_attr_name(use_attr[1:]), "") if use_attr.startswith("@") else ""

        # Like every other citeStructure level, a milestone-like level's
        # @match is relative to its *parent* level's matched element (e.g.
        # book.card: "milestone[@unit='card']" is meant to run against each
        # matched book div, not against body). _milestone_contexts finds
        # those parent-matched elements, prefixed with the URN suffix
        # accumulated down to them, so nested milestone schemes resolve
        # against the right context and get a complete URN.
        milestones: list[tuple[etree._Element, str]] = [
            (ms, prefix + delim + _val(ms))
            for prefix, context in self._milestone_contexts(target_cs)
            for ms in self._match(match_expr, context)
        ]

        def _urn(suffix: str) -> str:
            return self._base_urn + suffix

        for i, (ms, suffix) in enumerate(milestones):
            ms_next = milestones[i + 1][0] if i + 1 < len(milestones) else None
            yield CitationChunk(
                base_urn=self._base_urn,
                cts_urn=_urn(suffix),
                unit=unit,
                elements=elements_between(self._body, ms, ms_next),
                prev_urn=_urn(milestones[i - 1][1]) if i > 0 else None,
                next_urn=_urn(milestones[i + 1][1]) if i + 1 < len(milestones) else None,
            )

    def _milestone_contexts(
        self, target_cs: etree._Element
    ) -> list[tuple[str, etree._Element]]:
        """Return (urn_suffix, context_element) pairs — one per matched
        ancestor path — against which a milestone-like citeStructure's own
        @match should be evaluated.

        A flat, unnested milestone scheme (target_cs is itself a top-level
        citeStructure, e.g. CTS-card's single-level card scheme) matches
        directly against the document body, as before. A nested scheme
        (e.g. book.card) instead matches against each element matched by
        target_cs's parent level, mirroring how _walk_cs threads context
        through every other citeStructure level.
        """
        root_list = self._root_level_cs_list()
        if target_cs in root_list:
            return [("", self._body)]
        return self._find_milestone_parents("", root_list, self._body, target_cs)

    def _find_milestone_parents(
        self,
        suffix: str,
        cs_list: list[etree._Element],
        context: etree._Element,
        target_cs: etree._Element,
    ) -> list[tuple[str, etree._Element]]:
        results: list[tuple[str, etree._Element]] = []
        for node in self._walk_cs(suffix, cs_list, context):
            if target_cs in node.children:
                results.append((node.suffix, node.element))
            elif node.children:
                results.extend(
                    self._find_milestone_parents(
                        node.suffix, node.children, node.element, target_cs
                    )
                )
        return results

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
