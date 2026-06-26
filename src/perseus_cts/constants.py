"""Shared TEI, CTS, and XML namespace constants."""

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
CTS_NS = "http://chs.harvard.edu/xmlns/cts"
XML_NS = "http://www.w3.org/XML/1998/namespace"

NS = {"tei": TEI_NS, "xml": XML_NS}

XML_BASE = f"{{{XML_NS}}}base"
XML_ID   = f"{{{XML_NS}}}id"
XML_LANG = f"{{{XML_NS}}}lang"

XML_PARSER = etree.XMLParser(
    recover=True,
    load_dtd=False,
    resolve_entities=False,
    no_network=True,
    remove_comments=False,
)
