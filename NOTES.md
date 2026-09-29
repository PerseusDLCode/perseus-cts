# perseus-cts: Architecture and Design Notes

*This document records the design reasoning behind the package. The code
documents what it does; this records why it does it that way, and what
decisions were made and deferred. Addressed to a future reader (likely the
author) who needs to reconstruct context after time away.*

---

## Why this package exists

`perseus-cts` was extracted from MinimumViablePerseus in June 2026 (PR #104,
branch `extraction-2`). The extraction rationale: the CTS resolver and chunker
are corpus-level infrastructure, not MVP-specific code. Other projects —
`corpus-tools`, future viewer implementations, the Schmidt Sciences grant work
— need to resolve CTS URNs and chunk TEI documents without importing from
MVP. The extraction makes the dependency explicit and the code independently
testable.

The package has 161 passing tests. MVP consumes it via:

```toml
"perseus-cts @ git+https://github.com/PerseusDLCode/perseus-cts.git"
```

---

## The central design decision: citeStructure as single source of truth

Everything in this package depends on `<citeStructure>`, not `<cRefPattern>`.
This is deliberate and worth understanding.

`<cRefPattern>` is the older TEI mechanism for declaring citation patterns. It
uses XPath replacement expressions to map citation strings to elements. It
works but is brittle: the expressions are evaluated against document structure
by an external tool, there's no standard for what "evaluating" one means, and
the Perseus corpus's refsDecls cannot be trusted because the encoding is
inconsistent (the refsDecls were often not updated when the document structure
changed).

`<citeStructure>` (introduced in TEI P5 4.x) is declarative: it describes
the citation hierarchy structurally — *this element type at this nesting
depth, identified by this attribute* — without encoding explicit paths. The
CTSResolver walks the citeStructure tree and the document tree in parallel.
This means:

1. The citeStructure is the canonical declaration of what is citable.
2. If the citeStructure doesn't match the document, the resolver fails
   loudly rather than silently returning wrong results.
3. The corpus normalization pipeline (`corpus-tools`) can generate
   citeStructures automatically from observed document structure and then
   validate that the resolver actually finds citations.

**The `<refsDecl xml:id="CTS">` convention**: CTSResolver requires that the
active refsDecl carry `xml:id="CTS"`. This makes the intended CTS refsDecl
unambiguous when a document has multiple refsDecl elements (common in
documents with both CTS and other citation schemes). The script
`scripts/set_refsDecl_xml_id.py` retrofits this attribute across the corpus.

---

## CTSResolver: what each method does and why

`CTSResolver.__init__` does three things and fails fast if any are missing:
- Reads `tei:body/@xml:base` as the base URN (e.g.
  `urn:cts:greekLit:tlg0001.tlg001.perseus-grc2`)
- Finds `refsDecl[@xml:id='CTS']/citeStructure` as the root of the citation
  hierarchy
- Determines the document's XML namespace prefix (TEI or non-TEI) for
  XPath evaluation

Both absences raise `ConfigurationError`, which is distinct from
`CitationError`. This distinction matters: a `ConfigurationError` means the
document isn't set up for CTS resolution (missing xml:base or refsDecl);
a `CitationError` means the document is configured but a specific passage
wasn't found.

### `_walk_cs` — the shared traversal primitive

All the substantive methods (`citation_records`, `toc`, `chunks`) are built
on `_walk_cs`. It takes a suffix (accumulated URN passage component), a list
of citeStructure elements, and a context element, and yields `_CSNode`
objects — one per matched element at that hierarchy level. The recursive
structure mirrors the citeStructure hierarchy: each node's element becomes
the context for walking its children.

Understanding `_walk_cs` is sufficient to understand the whole resolver.

### `citation_records` and the annotation surface

`citation_records(depth=-1)` yields `CitationRecord` objects — one per
citable location in the document, at every level of the hierarchy. Each
record carries a URN, a unit name (e.g. "book", "section"), and a depth.

This is what was called the **annotation surface** in discussions with Greg
and Charles: the complete set of valid URNs over which annotations can be
attached. If an external system (morphological tagger, commentary linker)
wants to anchor its output to specific passages, it needs to know which URNs
are valid. `citation_records()` provides that.

Charles's Flask implementation uses external servers for morphology and (at
least as of June 2026) has not integrated the annotation surface declaration.
Whether this matters depends on whether MVP ever needs to resolve annotations
back to specific passage URNs. It will matter for the reference works (LSJ,
commentaries), where citation-linking is the core feature.

### `resolve` and `generate` — round-trip URN ↔ element

`resolve(urn)` → element: takes a full CTS URN and returns the lxml element
it identifies. Walks the passage component token by token, using each
citeStructure level's `@match` and `@use` to find the matching child element.

`generate(element)` → URN: the inverse — given an element, walks up the
citeStructure to assemble its URN. Used when you have a document element
and need to know its citable address.

These two operations should be inverses: `resolve(generate(e)) is e` and
`generate(resolve(u)) == u`. The test suite verifies this.

**`@use` may be any XPath** (added 2026-09-29). A plain attribute (`@n`)
is read directly; anything else is evaluated with the candidate element as
context, bare element names prefixed as in `@match`, and a numeric result
written without a trailing `.0`. Every reader of `@use` goes through
`_use()`, so resolve, generate, citations, TOC and milestone chunks agree.
Before this, a non-attribute `@use` generated empty values and never
resolved. The case that forced it: ShakeDraCor editions carry the Folger
Through-Line-Number only in `@xml:id` (`ftln-0034`), and are cited by it
through `use="string(number(substring-after(@xml:id, 'ftln-')))"`.

**Axes in `@match` are not prefixed.** `_prefix_match_expr` skips a name
preceded by `:`, so in `ancestor::div` the `div` stays unprefixed and
matches nothing in a TEI document. Write paths without axes (`sp//milestone`
rather than `.//milestone[not(ancestor::div[...])]`) until this is fixed.

### `toc` — the navigational hierarchy

`toc()` returns the full citation tree as nested dicts — suitable for
rendering a table of contents or a navigation sidebar. The `Chunker` includes
this in `metadata.json` alongside each compiled document. It's the
structured analogue of `citation_records()`: same traversal, different
output shape.

---

## The Chunker and its two strategies

`Chunker` compiles a `LenientTEIDocument` into a directory of per-chunk XML
files plus `index.json` and `metadata.json`. Each chunk is a `CitationChunk`
— a named wrapper element containing the deep-copied TEI content for one
citable unit.

### Selecting the chunk level

The chunking level is selected by `_find_chunk_cs()`:

1. **Explicit opt-in**: if any `<citeStructure n="chunk">` exists, use it.
   This lets editors override the default for unusual documents.
2. **Default — penultimate level**: the second-to-last level in the
   citeStructure hierarchy. For `book > chapter > section`, this is
   `chapter`. For `book > line`, this is `book`.

The penultimate-level default reflects a judgment that the finest citation
grain (individual lines, sections) is usually too small for a useful reading
page, while the coarsest level (book) is usually too large. The penultimate
level — a chapter, a book-within-a-book — tends to be the right page unit
for the Perseus reading interface.

### Two chunking strategies

**`_div_chunks`**: for structural `<div type="textpart">` elements. Each
matched element IS a chunk. Its subtree is deep-copied directly into the
`CitationChunk.elements` list. Straightforward.

**`_milestone_chunks`**: for milestone-based structure (Homer's `card`
milestones; Stephanus page milestones in Plato; Bekker pages in Aristotle).
Here the citable units are not elements but *regions between milestones*,
so the content of each chunk is assembled by `elements_between()`.

`elements_between(root, start_ms, end_ms)` finds all top-level elements in
document order between two milestones. `copy_before(element, stop)` handles
the boundary case where an element straddles a milestone — it copies the
element's content only up to the stop point.

This is the subtlest code in the package. The key insight is that milestone
content doesn't fit into a tree model cleanly (milestones are empty elements
that appear inside a linear stream of siblings), so the chunker has to work
in document order rather than tree order. The `pos` dict in
`elements_between` is the position index that makes this efficient.

---

## The models hierarchy

**`TEIMetadata`**: a frozen dataclass of bibliographic facts extracted from
the TEI header. The extraction is pragmatic and fallback-heavy: it tries
`biblStruct/monogr` first (the structured form), then falls back to flat
`titleStmt` elements.

**`TEIDocument`**: a parsed TEI source document. The parser is configured
with `recover=True` (tolerates malformed XML), `load_dtd=False`, and
`no_network=True` — essential for a corpus scanner that encounters many
legacy files with DTD references to dead network locations.

**`LenientTEIDocument`**: currently just `LenientTEIDocument = TEIDocument`.
The alias was introduced to signal an architectural distinction: a
`LenientTEIDocument` is one that the resolver should not fail on if some
citation expressions match zero elements (non-fatal). This distinction was
not implemented as of June 2026 — `LenientTEIDocument` and `TEIDocument` are
identical. The alias preserves the call sites in `CTSResolver` and `Chunker`
for a future implementation.

**`Corpus`**: lazy document iterator over a root directory. Skips
`__cts__.xml` catalog files. Collects parse failures and reports them as
warnings rather than aborting — necessary for a real-world corpus with
encoding defects.

**`CitationChunk`**: the output unit of `Chunker.chunks()`. Contains the
CTS URN, the unit name, the deep-copied element list, and prev/next URNs for
navigation. `to_xml()` serializes it as a `<citationChunk>` wrapper element
with TEI content inside — the format MVP's Flask app reads.

---

## The scripts

These are in `scripts/` and are corpus-repair tools developed during the
normalization campaign. They belong here (not in `corpus-tools`) because they
depend on `CTSResolver` internals.

**`check_corpus.py`** — runs `CTSResolver` on every file in one or more
corpus roots and reports `citation_records()` counts at each depth. The key
diagnostic: `zero_all` means the citeStructure is there but the match
expressions find nothing — almost always a depth mismatch (the expression
targets `l` but the lines are nested inside a container the expression
doesn't know about). `config_error` means missing xml:base or refsDecl.

**`compile_corpus.py`** — batch-compiles a corpus to proto-page chunks via
`Chunker`. Used to generate the `proto-pages/` directory that MVP's Flask
app reads. Skips already-compiled documents unless `--force` is given.
Derives the output path from the CTS URN
(`greekLit/tlg0001/tlg001/perseus-grc2/`).

**`fix_citestructure_depth.py`** — repairs the most common post-normalization
failure mode. When `add-citeStructure.xsl` generates a single-level
citeStructure targeting `l[@n]` but the actual document nests lines inside
`div[@type='poem']`, the resolver finds no citations. This script detects
that pattern — citeStructure says `match="l"` but lines are always inside a
container — and inserts the missing intermediate level. Dry-run by default;
`--write` to modify files.

**`fix_first_level_delim.py`** — fixes a systematic error in generated
citeStructures where the first citation-hierarchy level was given
`delim="."` instead of `delim=":"`. CTS URN syntax requires `:` to separate
the work identifier from the passage component (`urn:...work:book.chapter`,
not `urn:...work.book.chapter`). This was a bulk fix after the normalization
pipeline was corrected; existing files needed one-time remediation.

**`set_refsDecl_xml_id.py`** — adds `xml:id="CTS"` to every
`refsDecl[citeStructure]` that lacks it. Idempotent. Used once after the
initial normalization campaign; should not be needed again on already-
normalized files.

---

## Known limitations and open questions

**`LenientTEIDocument`** is not yet meaningfully distinct from `TEIDocument`.
The intent was that a `LenientTEIDocument` would tolerate citeStructure
match failures at leaf level without raising. This matters for documents like
the Galen corpus (non-standard milestones) where the resolver currently
produces partial results. Implementing the distinction requires a way to
signal "warn but continue" at the `_walk_cs` level.

**Milestone-based chunking assumes flat milestone sequences.** `elements_between`
works on a flat list of all elements in the body. If milestones are nested
(unusual but possible), the document-order traversal may capture too many
elements. No corpus examples of this were found during development, but the
case is not explicitly guarded against.

**`_penultimate_cs` always takes the first child** at each level when
descending. For documents with multiple citeStructure branches (multiple
refsDecl patterns at the same level — Plato's overlapping Stephanus/chapter
schemes), this selects only the first. The multi-axis citation problem is
acknowledged as Open Question 6 in MVP's `Roadmap.org` and is explicitly
deferred.

**`generate()` is O(n) in the number of citable elements.** It walks the
entire citeStructure to find the path to a given element. For large corpora
called frequently, this could be a bottleneck. Not a problem for the current
batch-compilation use case but worth noting for any interactive
annotation-resolution scenario.

**The chunk format (`citationChunk` wrapper element) is an internal
convention**, not a published standard. Charles's Flask implementation reads
it; it's not guaranteed to be stable. If the proto-pages format ever needs
to be versioned, the `version="1"` field in `metadata.json` is the hook.
