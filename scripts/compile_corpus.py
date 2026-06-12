#!/usr/bin/env python3
"""Compile TEI corpus documents into proto-page chunk files.

For each document in one or more corpus roots, runs the Chunker to produce:
  - One XML file per citation chunk  (e.g. 1.xml, 1.2.xml)
  - index.json    — chunk listing with CTS URNs
  - metadata.json — bibliographic metadata and table of contents

Output files are written under OUTPUT_DIR/{cts_namespace}/{textgroup}/{work}/{version}/.

Documents whose index.json already exists are skipped unless --force is given.

Usage
-----
    # Dry run — show what would be compiled without writing:
    python scripts/compile_corpus.py --output ../proto-pages

    # Compile (skip already-compiled documents):
    python scripts/compile_corpus.py --output ../proto-pages --write

    # Force recompile everything:
    python scripts/compile_corpus.py --output ../proto-pages --write --force

    # Specific corpus roots:
    python scripts/compile_corpus.py ../data-local/canonical-greekLit --output ../proto-pages --write
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from perseus_cts.chunker import Chunker
from perseus_cts.cts_resolver import ConfigurationError
from perseus_cts.models.corpus import Corpus

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOTS = [
    SCRIPT_DIR.parent.parent / "data-local" / "canonical-greekLit",
    SCRIPT_DIR.parent.parent / "data-local" / "First1KGreek",
    SCRIPT_DIR.parent.parent / "data-local" / "csel-dev",
]


def urn_to_rel_path(urn: str) -> Path | None:
    """Return the relative output path for a CTS URN.

    urn:cts:greekLit:tlg0655.tlg001.perseus-grc2
      → greekLit/tlg0655/tlg001/perseus-grc2
    """
    parts = urn.split(":")
    if len(parts) < 4:
        return None
    namespace = parts[2]
    work_parts = parts[3].split(".")
    return Path(namespace, *work_parts)


def compile_document(doc, output_dir: Path, force: bool, write: bool) -> tuple[str, str]:
    """Return (status, detail).

    Status values:
      'compiled'      – successfully compiled (only when write=True)
      'would_compile' – would compile (dry run)
      'skipped'       – index.json already exists and --force not given
      'no_urn'        – document has no CTS URN
      'failed'        – Chunker raised an exception
    """
    urn = doc.metadata.urn if doc.metadata else None
    if not urn:
        return "no_urn", str(doc.path.name)

    rel = urn_to_rel_path(urn)
    if rel is None:
        return "failed", f"cannot derive path from URN: {urn!r}"

    chunk_dir = output_dir / rel

    if not force and (chunk_dir / "index.json").exists():
        return "skipped", ""

    if not write:
        return "would_compile", str(rel)

    try:
        Chunker(doc).compile(chunk_dir)
        return "compiled", str(rel)
    except ConfigurationError as exc:
        return "failed", str(exc)
    except Exception as exc:
        return "failed", str(exc)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "roots",
        nargs="*",
        type=Path,
        metavar="ROOT",
        help="Corpus root(s) to compile (default: canonical-greekLit, First1KGreek, csel-dev)",
    )
    ap.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        metavar="DIR",
        help="Directory to write proto-page output into",
    )
    ap.add_argument(
        "--write",
        action="store_true",
        help="Write chunk files to disk (default: dry run)",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Recompile documents even if index.json already exists",
    )
    args = ap.parse_args()

    roots = args.roots if args.roots else DEFAULT_ROOTS

    for root in roots:
        if not root.exists():
            print(f"error: corpus root not found: {root}", file=sys.stderr)
            sys.exit(1)

    counts: dict[str, int] = {}
    failures: list[tuple[Path, str]] = []

    for root in roots:
        corpus = Corpus(root)
        for doc in corpus.documents():
            status, detail = compile_document(doc, args.output, args.force, args.write)
            counts[status] = counts.get(status, 0) + 1

            if status == "compiled":
                print(f"  compiled: {detail}")
            elif status == "would_compile":
                print(f"  would compile: {detail}")
            elif status == "failed":
                failures.append((doc.path, detail))
                print(f"  failed: {doc.path.name}: {detail}", file=sys.stderr)

    mode = "write" if args.write else "dry run"
    compiled = counts.get("compiled", counts.get("would_compile", 0))
    print(
        f"\n[{mode}]  "
        f"compiled={compiled}  "
        f"skipped={counts.get('skipped', 0)}  "
        f"no_urn={counts.get('no_urn', 0)}  "
        f"failed={counts.get('failed', 0)}"
    )

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
