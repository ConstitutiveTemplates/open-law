"""OL-2 provisions tests: the article tree for the uk, jp and eu adapters.

``Provision`` is one node of a law's structure — ``id`` follows the
Akoma Ntoso eId convention (element abbreviation plus number,
ancestors joined with ``__``), ``num`` is the number as printed,
``heading`` the caption, ``text`` the node's own text excluding its
children, ``children`` the nested provisions in document order.

Only uk, jp and eu are in scope: the other adapters' channels serve
flat HTML/PDF/TMX with no article structure worth parsing. eu
parses the CELLAR XHTML rendition's ``div.eli-subdivision#art_N``
articles (a 404 rendition leaves provisions empty). No test touches
the network.
"""

from __future__ import annotations

from tests.helpers import FixtureLoader, Offline, RecordingSite

from open_law.models import Provision
from open_law.sources.eu import EurlexAdapter
from open_law.sources.jp import EgovAdapter
from open_law.sources.uk import LegislationGovUkAdapter

_JP_V1_WITH_ARTICLES = """<?xml version="1.0" encoding="UTF-8"?>
<Lawdata><Result><Code>0</Code></Result><ApplData><LawFullText>
<Law Era="Reiwa" Year="5" PromulgateMonth="06" PromulgateDay="14" LawType="Act">
<LawBody><LawTitle>人工知能関係試験法</LawTitle><LawNum>令和五年法律第五十号</LawNum>
<MainProvision>
<Article Num="1"><ArticleTitle>第一条</ArticleTitle><ArticleCaption>目的</ArticleCaption>
<Paragraph Num="1"><ParagraphNum>1</ParagraphNum>
<ParagraphSentence><Sentence>この法律は、試験のために制定する。</Sentence></ParagraphSentence>
</Paragraph>
<Paragraph Num="2"><ParagraphNum>2</ParagraphNum>
<ParagraphSentence><Sentence>前項の試験は、次に掲げる方法で行う。</Sentence></ParagraphSentence>
<Item Num="1"><ItemTitle>一</ItemTitle><ItemSentence><Sentence>目視による方法</Sentence></ItemSentence></Item>
<Item Num="2"><ItemTitle>二</ItemTitle><ItemSentence><Sentence>機械による方法</Sentence></ItemSentence></Item>
</Paragraph>
</Article>
<Article Num="2"><ArticleTitle>第二条</ArticleTitle>
<Paragraph Num="1"><ParagraphNum>1</ParagraphNum>
<ParagraphSentence><Sentence>この法律は、公布の日から施行する。</Sentence></ParagraphSentence>
</Paragraph>
</Article>
</MainProvision>
<SupplProvision>
<SupplProvisionLabel>附則</SupplProvisionLabel>
<Paragraph Num="1"><ParagraphNum>1</ParagraphNum>
<ParagraphSentence><Sentence>この附則は、試験である。</Sentence></ParagraphSentence>
</Paragraph>
</SupplProvision>
</LawBody></Law></LawFullText></ApplData></Lawdata>
"""


def _eids(provision: Provision) -> list[str]:
    """All ids in a provision subtree, depth-first (eId uniqueness check helper)."""
    ids = [provision.id]
    for child in provision.children:
        ids.extend(_eids(child))
    return ids


def test_uk_sections_parse_with_subsections(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({"/ukcm/2023/1/data.xml": fixture_text("uk_ukcm_2023_1_data.xml")}, []),
    )
    law = adapter.fetch("ukcm/2023/1")
    assert [p.id for p in law.provisions] == ["section_1", "section_2"]
    first, second = law.provisions
    # eId convention: underscores, never the source's dashes.
    assert all("-" not in eid for p in law.provisions for eid in _eids(p))
    assert first.num == "1"
    assert first.heading == "Distribution of income to other dioceses"
    assert "After section 5A" in first.text
    # Quoted insert text is not structure: section 1 has no children.
    assert first.children == ()
    assert second.num == "2"
    assert second.heading == "Short title, commencement and extent"
    assert [c.id for c in second.children] == ["section_2_1", "section_2_2", "section_2_3"]
    assert second.children[0].num == "1"
    assert "cited as the Diocesan Stipends Funds" in second.children[0].text
    # Own text excludes children's: section 2's own text is just its number.
    assert second.text == "2"


def test_jp_articles_parse_with_paragraphs_and_items(offline: Offline, recording_site: RecordingSite) -> None:
    adapter = offline(EgovAdapter, recording_site({"/api/1/lawdata/999AC0000000001": _JP_V1_WITH_ARTICLES}, []))
    law = adapter.fetch("999AC0000000001")
    assert [p.id for p in law.provisions] == ["art_1", "art_2"]
    first, second = law.provisions
    assert first.num == "第一条"
    assert first.heading == "目的"
    assert [c.id for c in first.children] == ["art_1__para_1", "art_1__para_2"]
    assert "試験のために制定する" in first.children[0].text
    items = first.children[1].children
    assert [i.num for i in items] == ["(1)", "(2)"]
    assert "目視による方法" in items[0].text
    assert second.children[0].id == "art_2__para_1"
    # The suppl-provision paragraph block is not an Article: no suppl ids leak in.
    assert all(not eid.startswith("suppl_") for p in law.provisions for eid in _eids(p))
    # Ids are unique across the whole tree.
    all_ids = [eid for p in law.provisions for eid in _eids(p)]
    assert len(set(all_ids)) == len(all_ids)


def test_jp_law_without_articles_has_no_provisions(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """The repeal-law fixture's MainProvision holds bare paragraphs — no articles, no provisions."""
    adapter = offline(
        EgovAdapter,
        recording_site({"/api/1/lawdata/325AC0000000041": fixture_text("egov_lawdata_325AC0000000041.xml")}, []),
    )
    law = adapter.fetch("325AC0000000041")
    assert law.provisions == ()


def test_eu_articles_parse_with_paragraphs(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """CELLAR's XHTML rendition parses into articles with paragraph children."""
    adapter = offline(
        EurlexAdapter,
        recording_site(
            {
                "/resource/celex/32022R2065": fixture_text("eu_celex_32022R2065.rdf"),
                "/resource/celex/32022R2065.ENG.xhtml": fixture_text("eu_celex_32022R2065_articles.xhtml"),
            },
            [],
        ),
    )
    law = adapter.fetch("32022R2065")
    assert [p.id for p in law.provisions] == ["art_1", "art_2", "art_8"]
    first, second, bare = law.provisions
    assert first.num == "Article 1"
    assert first.heading == "Subject matter"
    assert [c.id for c in first.children] == ["art_1__para_1", "art_1__para_2"]
    assert "proper functioning of the internal market" in first.children[0].text
    assert [i.id for i in first.children[1].children] == ["art_1__para_2__item_1", "art_1__para_2__item_2"]
    assert "conditional exemption from liability" in first.children[1].children[0].text
    # Own text excludes paragraph children: article 1's intro block has none of its own.
    assert first.text == ""
    # Bare paragraphs and item tables are article own text, not children:
    # children are the numbered paragraph blocks alone.
    assert second.num == "Article 2"
    assert "introductory note" in second.text
    assert "(a) an introductory definition;" in second.text
    assert [c.id for c in second.children] == ["art_2__para_1"]
    assert bare.heading == "No general monitoring obligations"
    assert bare.children == ()
    assert "No general obligation" in bare.text
    # eId convention: underscores, never the source's dots/dashes; unique across the tree.
    all_ids = [eid for p in law.provisions for eid in _eids(p)]
    assert len(set(all_ids)) == len(all_ids)
