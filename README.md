# perseus-cts

CTS resolver, chunker, and TEI document models for the Perseus Digital Library.

## Overview

`perseus-cts` provides:

- **`CTSResolver`** — resolves and generates CTS URNs from TEI documents using `<citeStructure>` declarations
- **`Chunker`** — compiles a TEI document into `CitationChunk` XML files with navigation indexes
- **`TEIDocument` / `Corpus`** — lightweight TEI document model and corpus discovery
- **Data models** — `CitationChunk`, `CitationRecord`, `TEIMetadata`, word/chunk index types

## Installation

```bash
pip install perseus-cts
# or with PDM:
pdm add perseus-cts
```

## Usage

```python
from perseus_cts import TEIDocument, CTSResolver, Chunker

doc = TEIDocument("path/to/tei.xml")
resolver = CTSResolver(doc)

# Resolve a CTS URN to an XML element
elem = resolver.resolve("urn:cts:greekLit:tlg0003.tlg001.perseus-grc2:1.1.1")

# Iterate all chunks
for chunk in resolver.chunks():
    print(chunk.cts_urn, chunk.unit)

# Compile to static XML files
chunker = Chunker(doc)
chunker.compile(output_path)
```

## License

MIT
