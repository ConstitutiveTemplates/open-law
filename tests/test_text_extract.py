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


def test_html_to_text_preserve_structure_blocks_and_headings() -> None:
    html = "<h1>Title</h1><p>Para 1</p><p>Para 2</p><ul><li>a</li><li>b</li></ul>"
    out = html_to_text(html, preserve_structure=True)
    assert "# Title" in out
    assert "\n\n" in out
    assert "Para 1" in out and "Para 2" in out
    assert "- a" in out and "- b" in out
    # Default stays lossy
    assert html_to_text(html) == "Title Para 1 Para 2 a b"


def test_xml_to_text_preserve_structure_newlines_per_element() -> None:
    xml = "<root><section>Part 1</section><section>Part 2</section></root>"
    assert xml_to_text(xml) == "Part 1 Part 2"
    assert xml_to_text(xml, preserve_structure=True) == "Part 1\nPart 2"


def test_xml_to_text_preserve_structure_empty_on_malformed() -> None:
    assert xml_to_text("<not-xml", preserve_structure=True) == ""


def test_full_text_pdf_requires_pypdf_hint(tmp_path, monkeypatch) -> None:
    """PDF text_format without pypdf raises with pip install hint."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "pypdf":
            msg = "No module named 'pypdf'"
            raise ImportError(msg)
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    import httpx
    from open_law.fetcher import FetchConfig, PoliteFetcher
    from open_law.sources.base import NotAvailableBySourceError
    from open_law.sources.la import LaoGazetteAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if "/index.php" in request.url.path:
            # minimal gazette row so fetch returns a Law with a pdf text_url
            body = '<div class="row"><strong>ຫົວຂໍ້:</strong> Test Act</div><a href="/kcfinder/upload/files/a.pdf">pdf</a>'
            return httpx.Response(200, text=body)
        return httpx.Response(404, text="miss")

    fetcher = PoliteFetcher(
        FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter = LaoGazetteAdapter(fetcher)
    import pytest as _pytest

    with _pytest.raises(NotAvailableBySourceError, match=r"pip install open-law\[pdf\]"):
        adapter.full_text("2143")


def test_full_text_pdf_extracts_with_pypdf(tmp_path, monkeypatch) -> None:
    import sys
    import types
    import httpx
    from open_law.fetcher import FetchConfig, PoliteFetcher
    from open_law.sources.la import LaoGazetteAdapter

    # Stub pypdf with a fake PdfReader that returns known text
    mod = types.ModuleType("pypdf")

    class _FakePage:
        def extract_text(self):
            return "hello pdf"

    class _FakeReader:
        def __init__(self, _bio):
            self.pages = [_FakePage(), _FakePage()]

    mod.PdfReader = _FakeReader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", mod)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if "/index.php" in request.url.path:
            body = '<div class="row"><strong>ຫົວຂໍ້:</strong> Test Act</div><a href="/kcfinder/upload/files/a.pdf">pdf</a>'
            return httpx.Response(200, text=body)
        if request.url.path.endswith(".pdf"):
            # content is bytes; httpx handles str as text, bytes as content
            return httpx.Response(200, content=b"%PDF-1.4 fake")
        return httpx.Response(404, text="miss")

    fetcher = PoliteFetcher(
        FetchConfig(cache_dir=tmp_path / "cache", delay_seconds=0),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter = LaoGazetteAdapter(fetcher)
    text = adapter.full_text("2143")
    assert "hello pdf" in text
