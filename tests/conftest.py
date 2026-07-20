from __future__ import annotations

import textwrap
from pathlib import Path


def write_cts(directory: Path, *parts: str, content: str) -> Path:
    p = directory.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content), encoding="utf-8")
    return p
