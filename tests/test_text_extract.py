"""Plain-text extraction tests."""

from __future__ import annotations

from open_law.text_extract import html_to_text, xml_to_text


def test_html_to_text_strips_scripts_styles_and_tags() -> None:
    page = (
        "<html><head><style>body { color: red }</style>"
        "<script>evil()</script></head>"
        "<body><h1>कानूनी &amp; ऐन</h1><p>Section&nbsp;1</p><!-- note --></body></html>"
    )
    assert html_to_text(page) == "कानूनी & ऐन Section 1"


def test_html_to_text_collapses_whitespace() -> None:
    assert html_to_text("<p>a</p>\n  <p>b</p>") == "a b"


def test_xml_to_text_joins_character_data() -> None:
    xml = "<Legislation><Title>Diocesan Stipends</Title><Content>  Section 1 </Content></Legislation>"
    assert xml_to_text(xml) == "Diocesan Stipends Section 1"


def test_xml_to_text_empty_on_malformed() -> None:
    assert xml_to_text("<not-xml") == ""
