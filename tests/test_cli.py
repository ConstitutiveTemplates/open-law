"""CLI tests: every subcommand, offline via injected factories."""

from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import cast

import pytest

from tests.helpers import FixtureLoader, Offline, RecordingSite
from open_law import __version__
from open_law import __main__ as cli
from open_law.fetcher import Preflight
from open_law.sources.bd import BangladeshLawsAdapter
from open_law.sources.jp import EgovAdapter
from open_law.sources.la import LaoGazetteAdapter
from open_law.sources.uk import LegislationGovUkAdapter


def test_cli_version() -> None:
    cmd = [sys.executable, "-m", "open_law", "--version"]
    assert subprocess.check_output(cmd).decode().strip() == __version__


def test_sources_lists_registered_adapters(capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["sources"])
    out = capsys.readouterr().out
    assert "uk\tGB\tlegislation.gov.uk (The National Archives)" in out
    assert "jp\tJP\te-Gov 法令検索 (Digital Agency)" in out
    assert "eu\tEU\t" in out
    assert "Open Government Licence v3.0" in out


def test_search_prints_summaries_as_json(
    capsys: pytest.CaptureFixture[str], offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        EgovAdapter,
        recording_site({"/api/2/laws": fixture_text("egov_search_bankin.json")}, []),
    )
    cli.main(["search", "jp", "銀行法", "--limit", "3"], adapter_factory=lambda _source: adapter)
    payload = cast("list[dict[str, object]]", json.loads(capsys.readouterr().out))
    assert payload[0]["law_id"] == "325AC0000000041"
    assert payload[0]["title"] == "日本勧業銀行法等を廃止する法律"


def test_fetch_prints_law_as_json(
    capsys: pytest.CaptureFixture[str], offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({"/ukcm/2023/1/data.xml": fixture_text("uk_ukcm_2023_1_data.xml")}, []),
    )
    cli.main(["fetch", "uk", "ukcm/2023/1"], adapter_factory=lambda _source: adapter)
    payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
    assert payload["title"] == "Diocesan Stipends Funds (Amendment) Measure 2023"
    assert cast("str", payload["akn_url"]).endswith("/data.akn")


def test_unknown_source_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["fetch", "mars", "x"])
    assert excinfo.value.code == 2
    assert "known sources: bd, ca, eu, jp, kr, la, np, uk, us" in capsys.readouterr().err


def test_text_command_prints_plain_text(
    capsys: pytest.CaptureFixture[str],
    offline: Offline,
    recording_site: RecordingSite,
    fixture_text: FixtureLoader,
) -> None:
    adapter = offline(
        BangladeshLawsAdapter,
        recording_site({"/act-details-43.html": fixture_text("bd_act_43.html")}, []),
    )
    cli.main(["text", "bd", "43"], adapter_factory=lambda _source: adapter)
    out = capsys.readouterr().out
    assert "Kazi" in out
    assert "<" not in out


def test_text_command_reports_pdf_sources(
    capsys: pytest.CaptureFixture[str], offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LaoGazetteAdapter,
        recording_site({"/index.php": fixture_text("la_display_2143.html")}, []),
    )
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["text", "la", "2143"], adapter_factory=lambda _source: adapter)
    assert excinfo.value.code == 2
    assert "is a PDF" in capsys.readouterr().err


def test_dump_writes_jsonl_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    offline: Offline,
    recording_site: RecordingSite,
    fixture_text: FixtureLoader,
) -> None:
    uk_adapter = offline(
        LegislationGovUkAdapter,
        recording_site({"/ukcm/2023/1/data.xml": fixture_text("uk_ukcm_2023_1_data.xml")}, []),
    )
    bd_adapter = offline(
        BangladeshLawsAdapter,
        recording_site({"/act-details-43.html": fixture_text("bd_act_43.html")}, []),
    )
    factory = {"uk": uk_adapter, "bd": bd_adapter}
    out = tmp_path / "laws.jsonl"
    cli.main(
        ["dump", "uk", "ukcm/2023/1", "ukcm/2023/1", "--out", str(out)],
        adapter_factory=lambda source: factory[source],
    )
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["title"] == "Diocesan Stipends Funds (Amendment) Measure 2023"
    assert capsys.readouterr().out == ""

    # without --out, JSONL goes to stdout (mixing sources via the factory)
    cli.main(["dump", "bd", "act-details-43.html"], adapter_factory=lambda source: factory[source])
    line = capsys.readouterr().out.splitlines()[0]
    assert json.loads(line)["title"] == "The Kazis Act, 1880"


def test_dump_missing_act_exits_with_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    offline: Offline,
    recording_site: RecordingSite,
) -> None:
    adapter = offline(
        BangladeshLawsAdapter,
        recording_site({"/act-details-999999.html": "<title>404</title>"}, []),
    )
    out = tmp_path / "laws.jsonl"
    with pytest.raises(SystemExit) as excinfo:
        cli.main(
            ["dump", "bd", "999999", "--out", str(out)],
            adapter_factory=lambda _source: adapter,
        )
    assert excinfo.value.code == 2
    assert "no act with id" in capsys.readouterr().err
    assert not out.exists()  # no partial file on failure


def test_dump_ids_from_file_skips_blank_lines(
    tmp_path: Path, offline: Offline, recording_site: RecordingSite, fixture_text: FixtureLoader
) -> None:
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({"/ukcm/2023/1/data.xml": fixture_text("uk_ukcm_2023_1_data.xml")}, []),
    )
    ids_file = tmp_path / "ids.txt"
    ids_file.write_text("ukcm/2023/1\n\n  \nukcm/2023/1\n", encoding="utf-8")
    out = tmp_path / "laws.jsonl"
    cli.main(
        ["dump", "uk", "--ids-from", str(ids_file), "--out", str(out)],
        adapter_factory=lambda _source: adapter,
    )
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2


def test_dump_ids_from_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    offline: Offline,
    recording_site: RecordingSite,
    fixture_text: FixtureLoader,
) -> None:
    adapter = offline(
        LegislationGovUkAdapter,
        recording_site({"/ukcm/2023/1/data.xml": fixture_text("uk_ukcm_2023_1_data.xml")}, []),
    )
    monkeypatch.setattr(sys, "stdin", StringIO("ukcm/2023/1\n"))
    cli.main(["dump", "uk", "--ids-from", "-"], adapter_factory=lambda _source: adapter)
    line = capsys.readouterr().out.splitlines()[0]
    assert json.loads(line)["title"] == "Diocesan Stipends Funds (Amendment) Measure 2023"


def test_dump_without_any_ids_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["dump", "uk"])
    assert excinfo.value.code == 2
    assert "no law ids given" in capsys.readouterr().err


def test_coverage_command_reads_dumped_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps({"jurisdiction": "JP", "title": "銀行法"}, ensure_ascii=False)
        + "\n"
        + json.dumps({"jurisdiction": "GB", "title": "Data Protection Act 2018"})
        + "\n",
        encoding="utf-8",
    )
    cli.main(["coverage", str(corpus)])
    out = capsys.readouterr().out
    assert "JP" in out and "GB" in out
    assert "missing" in out

    cli.main(["coverage", str(corpus), "--json"])
    payload = cast("dict[str, dict[str, object]]", json.loads(capsys.readouterr().out))
    jp = payload["JP"]
    counts = cast("dict[str, object]", jp["counts"])

    assert counts["banking"] == 1
    jp_missing = cast("list[object]", jp["missing"])
    assert "banking" not in jp_missing
    assert "data-protection" in jp_missing


def test_coverage_command_reads_stdin(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO('{"jurisdiction": "NP", "title": "Debt Recovery Act"}\n'))
    cli.main(["coverage", "-"])
    assert "NP" in capsys.readouterr().out


def test_taxonomy_export_writes_expert_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "taxonomy.json"
    cli.main(["taxonomy", "--export", str(out)])
    body = out.read_text(encoding="utf-8")
    taxonomy = cast("dict[str, list[str]]", json.loads(body))
    assert "banking" in taxonomy and "銀行" in taxonomy["banking"]
    assert capsys.readouterr().out == ""

    cli.main(["taxonomy", "--export", "-"])
    assert json.loads(capsys.readouterr().out)["banking"] == taxonomy["banking"]


def test_correspond_command_reports_candidates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps(
            {
                "source": "uk",
                "law_id": "2018/12",
                "jurisdiction": "GB",
                "title": "Data Protection Act 2018",
                "promulgation_date": "2018-05-25",
            }
        )
        + "\n"
        + json.dumps(
            {
                "source": "xx",
                "law_id": "2",
                "jurisdiction": "XX",
                "title": "Data Protection Act 2018",
                "promulgation_date": "2018-12-04",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cli.main(["correspond", str(corpus)])
    out = capsys.readouterr().out
    assert "candidates for human review" in out
    assert "[data-protection]" in out
    assert "1.000" in out


def test_correspond_command_silence_is_explicit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps({"jurisdiction": "JP", "title": "銀行法"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    cli.main(["correspond", str(corpus)])
    assert "no candidate correspondences found" in capsys.readouterr().out


def test_coverage_command_applies_expert_annotations(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    corpus = tmp_path / "corpus.jsonl"
    corpus.write_text(
        json.dumps(
            {
                "source": "uk",
                "law_id": "2020/1",
                "jurisdiction": "GB",
                "title": "Some Unnamed Act 2020",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    annotations = tmp_path / "annotations.json"
    annotations.write_text('{"uk:2020/1": ["data-protection"]}', encoding="utf-8")
    taxonomy = tmp_path / "taxonomy.json"
    taxonomy.write_text('{"data-protection": ["privacy"]}', encoding="utf-8")
    cli.main(
        [
            "coverage",
            str(corpus),
            "--taxonomy",
            str(taxonomy),
            "--annotations",
            str(annotations),
        ]
    )
    out = capsys.readouterr().out
    assert "data-protection" in out
    assert "missing 0 of 1" in out


def test_unavailable_full_text_exits_with_error(capsys: pytest.CaptureFixture[str]) -> None:
    """Jp full text needs registration: the CLI reports it as an error."""
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["fetch", "jp", "325AC0000000041"])
    assert excinfo.value.code == 2
    assert "elsur.e-gov.go.jp" in capsys.readouterr().err


def test_missing_subcommand_exits_with_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_preflight_prints_judgement(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    judgement = Preflight(
        url="https://example.com/x",
        feed_url=None,
        api_hint=None,
        allowed=True,
        request_count=0,
        request_budget=100,
    )

    def fake_preflight(_url: str) -> Preflight:
        return judgement

    monkeypatch.setattr(cli, "preflight", fake_preflight)
    cli.main(["preflight", "https://example.com/x"])
    payload = cast("dict[str, object]", json.loads(capsys.readouterr().out))
    assert payload["url"] == "https://example.com/x"
    assert payload["allowed"] is True
    assert payload["request_budget"] == 100
