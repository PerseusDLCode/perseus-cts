#!/usr/bin/env python3
"""Fix citeStructure depth: insert missing intermediate container level.

For documents where a single-level citeStructure targets elements that are
actually nested one level deeper than <body> (e.g. match="l" but lines are
inside div[@type='poem']), this script:

  1. Finds all occurrences of the target element anywhere in <body>
  2. Traces each back to its direct-body-child ancestor (the outer container)
  3. If a single outer container type is found, inserts it as a new intermediate
     citeStructure level wrapping the existing inner one
  4. Writes the corrected file (--write) or reports changes (dry run)

New outer citeStructure always receives delim=':' (first citation level).
If the wrapped inner previously had delim=':' it is corrected to delim='.'.

Skips files where:
  - CTSResolver already yields citations
  - No refsDecl[citeStructure] / config error
  - Target element not found anywhere in the body
  - Multiple distinct outer container types (flags for manual review)
  - Root citeStructure has more than one child (not the target pattern)

Usage
-----
    # Dry run:
    python scripts/fix_citestructure_depth.py ../data-local/canonical-greekLit

    # Write changes:
    python scripts/fix_citestructure_depth.py ../data-local --write
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree
from lxml.etree import QName

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perseus_cts.cts_resolver import _prefix_match_expr, CTSResolver, ConfigurationError  # noqa: E402
from perseus_cts.constants import NS, TEI_NS  # noqa: E402

_PARSER = etree.XMLParser(
    recover=True,
    load_dtd=False,
    resolve_entities=False,
    no_network=True,
    remove_comments=False,
)


def _find_outer_containers(
    inner_match: str,
    body: etree._Element,
    doc_prefix: str,
    ns_map: dict,
) -> Counter | None:
    """Search for inner_match elements anywhere in body; return Counter of
    (localname, type) tuples for the direct-body-child ancestor of each hit.

    Returns None if no hits anywhere (different problem).
    Returns an empty Counter if all hits are already direct body children.
    """
    prefixed = _prefix_match_expr(inner_match, doc_prefix)
    hits = body.xpath(".//" + prefixed, namespaces=ns_map)
    if not hits:
        return None

    containers: Counter = Counter()
    for elem in hits:
        # Walk up to find the direct child of body
        current = elem
        while current.getparent() is not body and current.getparent() is not None:
            current = current.getparent()

        if current is elem:
            # Already a direct body child — no outer container needed
            continue
        if current.getparent() is not body:
            continue  # shouldn't happen

        tag = QName(current.tag).localname
        typ = (current.get("type") or "").strip()  # normalize whitespace typos
        containers[(tag, typ)] += 1

    return containers


def _outer_match_expr(tag: str, typ: str) -> str:
    return f"{tag}[@type='{typ}']" if typ else tag


def process_file(path: Path, write: bool) -> tuple[str, str]:
    """Return (status, detail).

    Statuses: fixed, would_fix, ok, skipped, multi_type, not_found, error
    """
    try:
        tree = etree.parse(str(path), _PARSER)
    except Exception as exc:
        return "error", str(exc)

    root = tree.getroot()
    if root is None or QName(root.tag).namespace != TEI_NS:
        return "skipped", "not TEI"

    if not root.xpath("//tei:refsDecl[tei:citeStructure]", namespaces=NS):
        return "skipped", "no refsDecl[citeStructure]"

    # Use the already-parsed tree so modifications and tree.write() stay in sync.
    class _Doc:
        root = tree.getroot()

    try:
        resolver = CTSResolver(_Doc())  # type: ignore[arg-type]
    except ConfigurationError as exc:
        return "skipped", f"config: {exc}"
    except Exception as exc:
        return "error", str(exc)

    if sum(1 for _ in resolver.citation_records(depth=-1)) > 0:
        return "ok", ""

    root_cs = resolver._root_cs
    body = resolver._body
    doc_prefix = resolver._doc_prefix
    ns_map = resolver._ns_map

    child_cs_list = root_cs.xpath("tei:citeStructure", namespaces=NS)
    if len(child_cs_list) != 1:
        return "skipped", f"root citeStructure has {len(child_cs_list)} children (expected 1)"

    inner_cs = child_cs_list[0]
    inner_match = inner_cs.get("match", "")

    containers = _find_outer_containers(inner_match, body, doc_prefix, ns_map)

    if containers is None:
        return "not_found", f"{inner_match!r} not found anywhere in body"

    if not containers:
        return "skipped", f"{inner_match!r} is already a direct body child (unexpected)"

    if len(containers) > 1:
        types = ", ".join(
            f"{_outer_match_expr(tag, typ)}×{n}"
            for (tag, typ), n in containers.most_common()
        )
        return "multi_type", f"multiple outer types: {types}"

    (outer_tag, outer_type), _ = containers.most_common(1)[0]
    outer_match = _outer_match_expr(outer_tag, outer_type)
    outer_unit = outer_type or outer_tag

    # Build new intermediate citeStructure
    new_outer_cs = etree.Element(f"{{{TEI_NS}}}citeStructure")
    new_outer_cs.set("match", outer_match)
    new_outer_cs.set("use", "@n")
    new_outer_cs.set("unit", outer_unit)
    new_outer_cs.set("delim", ":")

    # If inner was acting as first level (delim=':'), correct it to '.'
    if inner_cs.get("delim") == ":":
        inner_cs.set("delim", ".")

    # Move inner_cs into new_outer_cs, then attach to root_cs
    # (lxml automatically removes inner_cs from root_cs on append)
    new_outer_cs.append(inner_cs)
    root_cs.append(new_outer_cs)

    if write:
        encoding = tree.docinfo.encoding or "UTF-8"
        tree.write(str(path), xml_declaration=True, encoding=encoding, pretty_print=False)
        return "fixed", f"inserted {outer_match!r} around {inner_match!r}"

    return "would_fix", f"would insert {outer_match!r} around {inner_match!r}"


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("paths", nargs="+", type=Path, help="Corpus directory or XML file")
    ap.add_argument("--write", action="store_true", help="Write changes (default: dry run)")
    args = ap.parse_args()

    files: list[Path] = []
    for p in args.paths:
        if not p.exists():
            print(f"error: path does not exist: {p}", file=sys.stderr)
            sys.exit(1)
        files.extend([p] if p.is_file() else sorted(p.rglob("*.xml")))

    if not files:
        print("No XML files found.", file=sys.stderr)
        sys.exit(1)

    total = len(files)
    print(f"Scanning {total} files...", flush=True)

    counts: dict[str, int] = defaultdict(int)
    details: list[tuple[str, Path, str]] = []

    for i, f in enumerate(files, 1):
        if i % 250 == 0 or i == total:
            print(f"  {i}/{total}", flush=True)
        status, detail = process_file(f, args.write)
        counts[status] += 1
        if status not in ("ok", "skipped"):
            details.append((status, f, detail))

    mode = "write" if args.write else "dry run"
    print(f"\n[{mode}]")
    for label in ("fixed", "would_fix", "ok", "skipped", "multi_type", "not_found", "error"):
        n = counts.get(label, 0)
        if n:
            print(f"  {label:<14} {n}")

    if details:
        print(f"\nDetails:")
        for status, path, detail in sorted(details, key=lambda x: x[0]):
            print(f"  [{status}] {path.name}")
            print(f"           {detail}")

    if counts.get("multi_type", 0) or counts.get("error", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
