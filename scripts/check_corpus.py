#!/usr/bin/env python3
"""Corpus sanity checker for CTSResolver.

Walks normalized corpus directories, attempts to initialize CTSResolver on each
TEI document, calls citation_records(depth=-1), and flags documents where
citeStructure @match expressions fail to match any elements.

Status codes
------------
ok           - CTSResolver initialised; citations found at every depth
zero_all     - CTSResolver initialised; zero citations at every depth (broken match)
zero_at_leaf - CTSResolver initialised; leaf depth returned zero (partial match failure)
config_error - CTSResolver raised ConfigurationError (missing xml:base or refsDecl id)
parse_error  - lxml could not parse the file
skipped      - not a TEI document, or no refsDecl[citeStructure] present

Usage
-----
    python scripts/check_corpus.py ../data-local/canonical-greekLit ../data-local/First1KGreek
    python scripts/check_corpus.py ../data-local --csv report.csv
    python scripts/check_corpus.py ../data-local --show-ok
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from perseus_cts.cts_resolver import CTSResolver, ConfigurationError  # noqa: E402
from perseus_cts.models.document import TEIDocument  # noqa: E402

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}

_PARSER = etree.XMLParser(
    recover=True,
    load_dtd=False,
    resolve_entities=False,
    no_network=True,
    remove_comments=False,
)


def check_file(path: Path) -> dict:
    try:
        tree = etree.parse(str(path), _PARSER)
    except Exception as exc:
        return {"path": path, "status": "parse_error", "detail": str(exc), "counts": {}, "urn": ""}

    root = tree.getroot()
    if root is None or etree.QName(root.tag).namespace != TEI_NS:
        return {"path": path, "status": "skipped", "detail": "not a TEI document", "counts": {}, "urn": ""}

    if not root.xpath("//tei:refsDecl[tei:citeStructure]", namespaces=NS):
        return {"path": path, "status": "skipped", "detail": "no refsDecl[citeStructure]", "counts": {}, "urn": ""}

    try:
        resolver = CTSResolver(TEIDocument(path))
    except ConfigurationError as exc:
        return {"path": path, "status": "config_error", "detail": str(exc), "counts": {}, "urn": ""}
    except Exception as exc:
        return {"path": path, "status": "error", "detail": str(exc), "counts": {}, "urn": ""}

    counts: dict[int, int] = defaultdict(int)
    try:
        for record in resolver.citation_records(depth=-1):
            counts[record.depth] += 1
    except Exception as exc:
        return {"path": path, "status": "error", "detail": f"citation_records: {exc}", "counts": {}, "urn": resolver.base_urn}

    counts = dict(counts)
    if not counts:
        status = "zero_all"
        detail = "no citations at any depth"
    elif counts.get(max(counts), 0) == 0:
        status = "zero_at_leaf"
        detail = f"zero at leaf depth {max(counts)}"
    else:
        status = "ok"
        detail = ""

    return {"path": path, "status": status, "detail": detail, "counts": counts, "urn": resolver.base_urn}


def counts_str(counts: dict) -> str:
    return "  ".join(f"d{d}={n}" for d, n in sorted(counts.items()))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("paths", nargs="+", type=Path, help="Corpus directory or XML file")
    ap.add_argument("--csv", type=Path, metavar="FILE", help="Write full results to CSV")
    ap.add_argument("--show-ok", action="store_true", help="Also list OK files in detail")
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
    print(f"Checking {total} files...", flush=True)

    results = []
    status_counts: dict[str, int] = defaultdict(int)

    for i, f in enumerate(files, 1):
        if i % 250 == 0 or i == total:
            print(f"  {i}/{total}", flush=True)
        r = check_file(f)
        results.append(r)
        status_counts[r["status"]] += 1

    flagged = [r for r in results if r["status"] not in ("ok", "skipped")]

    print(f"\nSummary ({total} files):")
    for label in ("ok", "skipped", "zero_all", "zero_at_leaf", "config_error", "parse_error", "error"):
        n = status_counts.get(label, 0)
        if n:
            print(f"  {label:<16} {n}")

    if flagged:
        print(f"\nFlagged ({len(flagged)}):")
        for r in sorted(flagged, key=lambda x: x["status"]):
            c = f"  [{counts_str(r['counts'])}]" if r["counts"] else ""
            print(f"  [{r['status']}] {r['path'].name}{c}")
            if r["detail"]:
                print(f"           {r['detail']}")

    if args.show_ok:
        ok = [r for r in results if r["status"] == "ok"]
        print(f"\nOK ({len(ok)}):")
        for r in ok:
            print(f"  {r['path'].name}  {counts_str(r['counts'])}")

    if args.csv:
        max_depth = max(
            (max(r["counts"].keys()) for r in results if r["counts"]),
            default=3,
        )
        depth_cols = [f"d{d}" for d in range(max_depth + 1)]
        fieldnames = ["path", "status", "detail", "urn"] + depth_cols
        with open(args.csv, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                row: dict = {
                    "path": r["path"],
                    "status": r["status"],
                    "detail": r["detail"],
                    "urn": r["urn"],
                }
                for col in depth_cols:
                    d = int(col[1:])
                    row[col] = r["counts"].get(d, "")
                writer.writerow(row)
        print(f"\nCSV written to {args.csv}")

    if status_counts.get("zero_all", 0) or status_counts.get("error", 0):
        sys.exit(1)


if __name__ == "__main__":
    main()
