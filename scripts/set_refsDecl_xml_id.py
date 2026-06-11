#!/usr/bin/env python3
"""Add xml:id="CTS" to the refsDecl that contains a citeStructure child.

Walks a file or directory recursively, finds every refsDecl[citeStructure],
and adds xml:id="CTS" if the attribute is absent.  Idempotent: files that
already carry xml:id="CTS" are reported but not rewritten.

Usage
-----
    # Dry run — show what would change without writing:
    python scripts/set_refsDecl_xml_id.py ../data-local

    # Write the changes:
    python scripts/set_refsDecl_xml_id.py ../data-local --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
NS     = {"tei": TEI_NS}
XML_ID = f"{{{XML_NS}}}id"

TARGET_ID = "CTS"

PARSER = etree.XMLParser(
    recover=True,
    load_dtd=False,
    resolve_entities=False,
    no_network=True,
    remove_comments=False,
)


def process_file(path: Path, write: bool) -> tuple[str, str]:
    """Return (status, detail) where status is one of:
    'updated', 'already_set', 'skipped', 'conflict', 'error'.
    """
    try:
        tree = etree.parse(str(path), PARSER)
    except Exception as exc:
        return "error", str(exc)

    root = tree.getroot()
    if root is None:
        return "error", "could not parse (empty or malformed)"

    # Only operate on TEI documents
    if etree.QName(root.tag).namespace != TEI_NS:
        return "skipped", "not a TEI document"

    hits = root.xpath("//tei:refsDecl[tei:citeStructure]", namespaces=NS)

    if not hits:
        return "skipped", "no refsDecl[citeStructure]"

    if len(hits) > 1:
        return "error", f"{len(hits)} refsDecl elements contain citeStructure — cannot disambiguate"

    refsDecl = hits[0]
    existing = refsDecl.get(XML_ID)

    if existing == TARGET_ID:
        return "already_set", ""

    if existing is not None:
        return "conflict", f"xml:id already set to '{existing}'"

    refsDecl.set(XML_ID, TARGET_ID)

    if write:
        encoding = tree.docinfo.encoding or "UTF-8"
        tree.write(
            str(path),
            xml_declaration=True,
            encoding=encoding,
            pretty_print=False,
        )

    return "updated", ""


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("path", type=Path, help="File or directory to process")
    ap.add_argument(
        "--write",
        action="store_true",
        help="Write changes to disk (default: dry run)",
    )
    args = ap.parse_args()

    if not args.path.exists():
        print(f"error: path does not exist: {args.path}", file=sys.stderr)
        sys.exit(1)

    files = [args.path] if args.path.is_file() else sorted(args.path.rglob("*.xml"))

    counts: dict[str, int] = {}
    conflicts: list[Path] = []

    for f in files:
        status, detail = process_file(f, args.write)
        counts[status] = counts.get(status, 0) + 1

        if status == "updated":
            verb = "updated" if args.write else "would update"
            print(f"  {verb}: {f}")
        elif status == "conflict":
            conflicts.append(f)
            print(f"  conflict: {f}: {detail}", file=sys.stderr)
        elif status == "error":
            print(f"  error: {f}: {detail}", file=sys.stderr)

    mode = "write" if args.write else "dry run"
    print(
        f"\n[{mode}]  "
        f"updated={counts.get('updated', 0)}  "
        f"already_set={counts.get('already_set', 0)}  "
        f"skipped={counts.get('skipped', 0)}  "
        f"conflicts={counts.get('conflict', 0)}  "
        f"errors={counts.get('error', 0)}"
    )

    if conflicts or counts.get("error", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
