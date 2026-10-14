"""OL-1 contract tests: what ``last_amended`` and ``consolidated_as_of`` mean, per adapter.

The unified model splits versioning into two fields:

- ``last_amended``: the ISO-8601 date of the most recent amendment the
  *source* reports — or ``None`` when the source does not say. It is
  NEVER a fetch/run date and NEVER a metadata-record timestamp. Two
  fetches compare ``last_amended`` to detect amendments.
- ``consolidated_as_of``: the ISO-8601 point-in-time the served text
  reflects — or ``None`` for as-published texts and sources that do
  not state one.

Each test below pins one adapter's semantics against a captured
fixture, so a future change to any adapter's date handling trips
exactly the test naming that adapter. No test touches the network.
"""

from __future__ import annotations

from tests.helpers import FixtureLoader, Offline, RecordingSite

from open_law.sources.bd import BangladeshLawsAdapter
from open_law.sources.ca import JusticeLawsAdapter
from open_law.sources.de import GesetzeImInternetAdapter
from open_law.sources.eu import EurlexAdapter
from open_law.sources.jlt import JltAdapter
from open_law.sources.jp import EgovAdapter
from open_law.sources.la import LaoGazetteAdapter
from open_law.sources.mv import MvLawAdapter
from open_law.sources.np import NepalLawCommissionAdapter
from open_law.sources.uk import LegislationGovUkAdapter
from open_law.sources.us_ecfr import EcfrAdapter
from open_law.sources.us_tx import TexasStatutesAdapter

_MENDED_V2 = (
    '{"laws": [{"law_info": {"law_id": "327AC0000000187", "law_num": "昭和二十七年法律第百八十七号"}, '
    '"revision_info": {"law_title": "長期信用銀行法", "amendment_promulgate_date": "2026-07-23", '
    '"amendment_enforcement_date": "2026-08-12"}}]}'
)


def test_jp_amended_law_reports_v2_amendment_date(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """Amendment-awareness for jp: a later v2 amendment date becomes ``last_amended``.

    The v1 body is served from the captured fixture (promulgation
    1950-03-31); the v2 lookup reports an amendment promulgated
    2026-07-23, enforced 2026-08-12. ``last_amended`` is the former,
    ``consolidated_as_of`` the latter.
    """
    adapter = offline(
        EgovAdapter,
        recording_site(
            {
                "/api/1/lawdata/327AC0000000187": fixture_text("egov_lawdata_325AC0000000041.xml"),
                "/api/2/laws": _MENDED_V2,
            },
            [],
        ),
    )
    law = adapter.fetch("327AC0000000187")
    assert law.last_amended == "2026-07-23"
    assert law.consolidated_as_of == "2026-08-12"


def test_jp_never_amended_law_has_no_last_amended(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """A never-amended Japanese law: v2 stamping the enactment date is not an amendment."""
    adapter = offline(
        EgovAdapter,
        recording_site(
            {
                "/api/1/lawdata/325AC0000000041": fixture_text("egov_lawdata_325AC0000000041.xml"),
                "/api/2/laws": fixture_text("egov_search_bankin.json"),
            },
            [],
        ),
    )
    law = adapter.fetch("325AC0000000041")
    assert law.promulgation_date == "1950-03-31"
    assert law.last_amended is None
    assert law.consolidated_as_of == "1950-03-31"


def test_us_ecfr_reports_point_in_time_not_amendment(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """us-ecfr: the API states no per-node amendment date — ``last_amended`` is ``None``.

    ``consolidated_as_of`` is the dated ``full/`` endpoint's day (the
    corpus point-in-time), which the adapter pins to the fetch day by
    construction — never presented as an amendment.
    """
    from open_law.sources.us_ecfr import _today

    adapter = offline(
        EcfrAdapter,
        recording_site({f"/api/versioner/v1/full/{_today()}/title-16.xml": fixture_text("ecfr_t16_s312_5.xml")}, []),
    )
    law = adapter.fetch("title-16/part-312/section-312.5")
    assert law.last_amended is None
    assert law.consolidated_as_of == _today()


def test_ca_reports_pit_and_amendment_dates(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """ca: ``last_amended`` is ``lastAmendedDate``; ``consolidated_as_of`` is ``pit-date``."""
    adapter = offline(
        JusticeLawsAdapter,
        recording_site({"/eng/XML/P-8.6.xml": fixture_text("ca_P-8.6.xml")}, []),
    )
    law = adapter.fetch("P-8.6")
    assert law.last_amended == "2025-03-04"
    assert law.consolidated_as_of == "2026-03-26"


def test_ca_without_stamps_reports_unknown_not_today(offline: Offline, recording_site: RecordingSite) -> None:
    """ca: XML without date stamps yields ``None`` — never the fetch date."""
    bare = '<?xml version="1.0"?><Statute><Identification/></Statute>'
    adapter = offline(JusticeLawsAdapter, recording_site({"/eng/XML/C-46.xml": bare}, []))
    law = adapter.fetch("C-46")
    assert law.last_amended is None
    assert law.consolidated_as_of is None


def test_eu_reports_record_date_not_amendment(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """eu: CELLAR's ``lastModificationDate`` is the metadata record's own stamp.

    A re-ingest moves it without any amendment, so ``last_amended``
    stays ``None``; ``consolidated_as_of`` is the record's day.
    """
    adapter = offline(
        EurlexAdapter,
        recording_site({"/resource/celex/32022R2065": fixture_text("eu_celex_32022R2065.rdf")}, []),
    )
    law = adapter.fetch("32022R2065")
    assert law.last_amended is None
    assert law.consolidated_as_of == "2023-12-13"


def test_uk_reports_validity_not_amendment(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """uk: ``dc:modified`` is the metadata record's own stamp (``None``); ``dct:valid`` is as-of."""
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({"/ukcm/2023/1/data.xml": fixture_text("uk_ukcm_2023_1_data.xml")}, []),
    )
    law = adapter.fetch("ukcm/2023/1")
    assert law.last_amended is None
    assert law.consolidated_as_of == "2023-06-29"


def test_as_published_sources_report_unknown_dates(
    offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    """bd/de/jlt/la/mv/np/us-tx: as-published channels state no version dates — both ``None``."""
    cases = [
        (BangladeshLawsAdapter, {"/act-details-43.html": fixture_text("bd_act_43.html")}, "43"),
        (GesetzeImInternetAdapter, {"/bgb/index.html": fixture_text("de_teilb_excerpt.html")}, "bgb"),
        (JltAdapter, {"/en/laws/view/4913": fixture_text("jlt_view_4913.html")}, "4913"),
        (LaoGazetteAdapter, {"/index.php": fixture_text("la_display_2143.html")}, "2143"),
        (
            MvLawAdapter,
            {"/dv/legislations/291": fixture_text("mv_consolidation_291_1302.html")},
            "291",
        ),
        (NepalLawCommissionAdapter, {"/content/13535/": fixture_text("np_act_page.html")}, "13535"),
        (TexasStatutesAdapter, {"/resources/BC/htm/BC.503.htm": fixture_text("ustx_BC.503.htm")}, "BC.503"),
    ]
    for adapter_cls, mapping, law_id in cases:
        adapter = offline(adapter_cls, recording_site(mapping, []))
        law = adapter.fetch(law_id)
        assert law.last_amended is None, adapter_cls.source_id
        assert law.consolidated_as_of is None, adapter_cls.source_id
