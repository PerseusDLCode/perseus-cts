#!/usr/bin/env python3
"""Fix first-level citeStructure delim: change '.' → ':' (CTS passage separator).

Walks one or more corpus roots, finds every refsDecl[@xml:id='CTS'], and
changes the direct children of the top-level citeStructure (use="@xml:base")
from delim="." to delim=":".  Deeper levels (book.chapter.section) are left
untouched.  Files are edited surgically: only the one attribute value changes;
all other bytes are preserved.

Usage
-----
    # Dry run — show what would change without writing:
    python scripts/fix_first_level_delim.py

    # Write the changes:
    python scripts/fix_first_level_delim.py --write

    # Operate on specific paths:
    python scripts/fix_first_level_delim.py ../data-local/canonical-greekLit --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOTS = [
    SCRIPT_DIR.parent.parent / "data-local" / "canonical-greekLit",
    SCRIPT_DIR.parent.parent / "data-local" / "First1KGreek",
    SCRIPT_DIR.parent.parent / "data-local" / "csel-dev",
]

PARSER = etree.XMLParser(
    recover=True,
    load_dtd=False,
    resolve_entities=False,
    no_network=True,
    remove_comments=False,
)


def process_file(path: Path, write: bool) -> tuple[str, str]:
    """Return (status, detail).

    Status values:
      'updated'         – delim changed (only when write=True)
      'would_update'    – delim would be changed (dry run)
      'already_correct' – first-level delim is already ':'
      'skipped'         – no CTS refsDecl or no first-level citeStructure
      'error'           – parse error or attribute not found on expected line
    """
    try:
        tree = etree.parse(str(path), PARSER)
    except Exception as exc:
        return "error", str(exc)

    root = tree.getroot()
    if root is None:
        return "error", "could not parse (empty or malformed)"

    if etree.QName(root.tag).namespace != TEI_NS:
        return "skipped", "not a TEI document"

    # Direct children of the top-level (use="@xml:base") citeStructure.
    first_level = root.xpath(
        "//tei:refsDecl[@xml:id='CTS']/tei:citeStructure/tei:citeStructure",
        namespaces=NS,
    )

    if not first_level:
        return "skipped", "no CTS refsDecl or no first-level citeStructure"

    # Collect elements that need fixing.
    to_fix = [cs for cs in first_level if cs.get("delim") == "."]
    already_correct = [cs for cs in first_level if cs.get("delim") == ":"]

    if not to_fix:
        if already_correct:
            return "already_correct", ""
        # Some other delim value or no delim at all — don't touch.
        return "skipped", "first-level delim is not '.' or ':'"

    # Surgical byte-level edit: locate each target element by source line
    # and replace the attribute on that exact line.
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)

    for cs in to_fix:
        lineno = cs.sourceline  # 1-indexed
        if lineno is None or lineno < 1 or lineno > len(lines):
            return "error", f"sourceline {lineno!r} out of range"

        # lxml sourceline points to the last line of the opening tag (where
        # '>' or '/>' appears).  Scan backward to find the delim attribute,
        # stopping when we hit the '<' that opens this element.
        found = False
        for i in range(lineno - 1, max(-1, lineno - 20), -1):
            if b'delim="."' in lines[i]:
                lines[i] = lines[i].replace(b'delim="."', b'delim=":"', 1)
                found = True
                break
            if b"<" in lines[i]:
                break

        if not found:
            return "error", f"delim=\".\" not found near line {lineno}"

    if write:
        path.write_bytes(b"".join(lines))
        return "updated", ""

    return "would_update", ""


def iter_xml_files(root: Path):
    for f in sorted(root.rglob("*.xml")):
        if f.name == "__cts__.xml":
            continue
        yield f


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "paths",
        nargs="*",
        type=Path,
        metavar="PATH",
        help="Corpus root(s) to process (default: three affected repos under data-local/)",
    )
    ap.add_argument(
        "--write",
        action="store_true",
        help="Write changes to disk (default: dry run)",
    )
    args = ap.parse_args()

    roots = args.paths if args.paths else DEFAULT_ROOTS

    for root in roots:
        if not root.exists():
            print(f"error: path does not exist: {root}", file=sys.stderr)
            sys.exit(1)

    counts: dict[str, int] = {}
    errors: list[tuple[Path, str]] = []

    for root in roots:
        files = [root] if root.is_file() else list(iter_xml_files(root))
        for f in files:
            status, detail = process_file(f, args.write)
            counts[status] = counts.get(status, 0) + 1

            if status in ("updated", "would_update"):
                verb = "updated" if args.write else "would update"
                print(f"  {verb}: {f}")
            elif status == "error":
                errors.append((f, detail))
                print(f"  error: {f}: {detail}", file=sys.stderr)

    mode = "write" if args.write else "dry run"
    print(
        f"\n[{mode}]  "
        f"updated={counts.get('updated', counts.get('would_update', 0))}  "
        f"already_correct={counts.get('already_correct', 0)}  "
        f"skipped={counts.get('skipped', 0)}  "
        f"errors={counts.get('error', 0)}"
    )

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
