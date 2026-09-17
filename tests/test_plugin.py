from __future__ import annotations

from copy import deepcopy
from configparser import ConfigParser
from pathlib import Path

import pandas as pd
import pytest

from fair_eva.plugin.fidelis.plugin import (
    ADULT_COLUMN_MAPPING,
    ADULT_QUASI_IDENTIFIERS,
    ADULT_SENSITIVE_ATTRIBUTES,
    Plugin,
)


RECORD = {
    "id": 10897,
    "conceptrecid": "605507",
    "doi": "10.5281/zenodo.10897",
    "doi_url": "https://doi.org/10.5281/zenodo.10897",
    "created": "2014-08-08T22:38:59+00:00",
    "modified": "2024-08-06T14:13:35+00:00",
    "metadata": {
        "title": "Computing and Using Metrics in ADS",
        "publication_date": "2014-07-16",
        "description": "Research impact metrics data.",
        "access_right": "open",
        "creators": [
            {
                "name": "Henneken, Edwin",
                "affiliation": "Smithsonian Astrophysical Observatory",
                "orcid": "0000-0002-1825-0097",
            }
        ],
        "keywords": ["bibliometrics", "impact measures"],
        "resource_type": {"title": "Dataset", "type": "dataset"},
        "license": {"id": "cc-by-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
        "version": "1.0",
        "communities": [{"id": "fidelis"}],
        "related_identifiers": [
            {
                "identifier": "10.5281/zenodo.99999",
                "relation": "isDerivedFrom",
                "resource_type": "dataset",
            },
            {
                "identifier": "10.5281/zenodo.88888",
                "relation": "isDescribedBy",
                "resource_type": "publication",
            },
        ],
        "relations": {"version": [{"index": 0, "is_last": True}]},
    },
    "links": {
        "self": "https://zenodo.org/api/records/10897",
        "self_html": "https://zenodo.org/records/10897",
    },
    "files": [
        {
            "key": "metrics.csv",
            "size": 1234,
            "checksum": "md5:abc",
            "links": {"self": "https://zenodo.org/api/records/10897/files/metrics.csv/content"},
        }
    ],
}

DEMO_CSV = b"""39, State-gov, 77516, Bachelors, 13, Never-married, Adm-clerical, Not-in-family, White, Male, 2174, 0, 40, United-States, <=50K
39, Private, 77517, Bachelors, 13, Never-married, Adm-clerical, Not-in-family, Black, Male, 0, 0, 40, United-States, >50K
50, Private, 83311, HS-grad, 9, Married-civ-spouse, Exec-managerial, Husband, White, Male, 0, 0, 13, United-States, <=50K
50, Private, 83312, HS-grad, 9, Married-civ-spouse, Exec-managerial, Husband, Black, Male, 0, 0, 13, United-States, >50K
"""

DEMO_RECORD = deepcopy(RECORD)
DEMO_RECORD.update(
    {
        "id": 7214275,
        "doi": "10.5281/zenodo.7214275",
        "doi_url": "https://doi.org/10.5281/zenodo.7214275",
        "files": [
            {
                "key": "adult.csv",
                "size": len(DEMO_CSV),
                "checksum": "md5:demo",
                "links": {
                    "self": "https://zenodo.org/api/records/7214275/files/adult.csv/content"
                },
            }
        ],
    }
)
DEMO_RECORD["metadata"] = {
    **DEMO_RECORD["metadata"],
    "title": "UCI Machine Learning- Adult Dataset",
    "doi": "10.5281/zenodo.7214275",
}


class Response:
    def __init__(self, payload=None, status_code=200, content=b""):
        self.payload = payload
        self.status_code = status_code
        self.content = content

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, record=RECORD, download_content=DEMO_CSV, download_status=200):
        self.record = record
        self.download_content = download_content
        self.download_status = download_status
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/adult.csv/content"):
            return Response(status_code=self.download_status, content=self.download_content)
        if url.endswith("/records"):
            return Response({"hits": {"hits": [{"id": self.record["id"]}]}})
        return Response(self.record)


@pytest.fixture
def config():
    parser = ConfigParser()
    parser.read(Path(__file__).parents[1] / "fair_eva/plugin/fidelis/config.ini")
    return parser


@pytest.mark.parametrize(
    "identifier",
    [
        "10897",
        "10.5281/zenodo.10897",
        "https://doi.org/10.5281/zenodo.10897",
        "https://zenodo.org/records/10897",
    ],
)
def test_supported_identifiers_resolve_to_record(identifier, config):
    plugin = Plugin(identifier, config=config, session=Session())
    assert plugin.record_id == "10897"
    assert plugin.item_id == "10.5281/zenodo.10897"


def test_non_zenodo_doi_is_searched(config):
    session = Session()
    plugin = Plugin("10.1234/example.dataset", config=config, session=session)
    assert session.calls[0][0] == "https://zenodo.org/api/records"
    assert session.calls[0][1]["params"]["q"] == 'doi:"10.1234/example.dataset"'
    assert plugin.record_id == "10897"


def test_metadata_and_files_are_mapped(config):
    plugin = Plugin("10897", config=config, session=Session())
    assert list(plugin.metadata.columns) == ["metadata_schema", "element", "qualifier", "text_value"]
    assert "10.5281/zenodo.10897" in plugin._metadata_values("identifier", "doi")
    assert "0000-0002-1825-0097" in plugin._metadata_values("creator", "orcid")
    assert "cc-by-4.0" in plugin._metadata_values("rights", "license")
    assert plugin.file_list.iloc[0]["extension"] == ".csv"
    assert plugin.file_list.iloc[0]["format"] == "text/csv"


def test_all_fair_eva_400_indicators_return_valid_scores(config):
    plugin = Plugin("10897", config=config, session=Session())
    indicators = [
        "rda_f1_01m", "rda_f1_01d", "rda_f1_02m", "rda_f1_02d", "rda_f2_01m", "rda_f3_01m", "rda_f4_01m",
        "rda_a1_01m", "rda_a1_02m", "rda_a1_02d", "rda_a1_03m", "rda_a1_03d", "rda_a1_04m", "rda_a1_04d", "rda_a1_05d", "rda_a1_1_01m", "rda_a1_1_01d", "rda_a1_2_01d", "rda_a2_01m",
        "rda_i1_01m", "rda_i1_01d", "rda_i1_02m", "rda_i1_02d", "rda_i2_01m", "rda_i2_01d", "rda_i3_01m", "rda_i3_01d", "rda_i3_02m", "rda_i3_02d", "rda_i3_03m", "rda_i3_04m",
        "rda_r1_01m", "rda_r1_1_01m", "rda_r1_1_02m", "rda_r1_1_03m", "rda_r1_2_01m", "rda_r1_2_02m", "rda_r1_3_01m", "rda_r1_3_01d", "rda_r1_3_02m", "rda_r1_3_02d",
        "data_01", "data_02", "data_privacy_01",
    ]
    for indicator in indicators:
        points, messages = getattr(plugin, indicator)()
        assert 0 <= points <= 100, indicator
        assert isinstance(messages, list) and messages, indicator


def test_restricted_record_is_not_reported_as_automatically_downloadable(config):
    record = {**RECORD, "metadata": {**RECORD["metadata"], "access_right": "restricted", "access_conditions": "Apply to the owner."}, "files": []}
    plugin = Plugin("10897", config=config, session=Session(record))
    assert plugin.rda_a1_03d()[0] == 100
    assert plugin.rda_a1_05d()[0] == 0


def test_invalid_identifier_has_actionable_error(config):
    with pytest.raises(ValueError, match="Zenodo record ID"):
        Plugin("not-an-identifier", config=config, session=Session())


def test_non_zenodo_endpoint_is_rejected(config):
    with pytest.raises(ValueError, match="only accepts HTTPS endpoints"):
        Plugin("10897", api_endpoint="http://example.org/api", config=config, session=Session())


def test_pycanon_demo_record_is_identified(config):
    plugin = Plugin("7214275", config=config, session=Session(DEMO_RECORD))

    assert plugin._is_pycanon_demo_dataset()


def test_fidelis_api_extension_is_opt_in(config, monkeypatch):
    assert config.get("Generic", "api_config") == "fair-api.yaml"
    monkeypatch.setenv("FIDELIS_API_CONFIG", "fair-api-fidelis.yaml")

    plugin = Plugin("10897", config=config, session=Session())

    assert plugin.config.get("Generic", "api_config") == "fair-api-fidelis.yaml"


def test_pycanon_demo_is_not_applicable_to_another_record(config):
    plugin = Plugin("10897", config=config, session=Session())

    points, messages = plugin.data_privacy_01()

    assert points == 0
    assert "Not applicable" in messages[0]["message"]


def test_get_file_entry_selects_adult_csv(config):
    plugin = Plugin("7214275", config=config, session=Session(DEMO_RECORD))

    entry = plugin._get_file_entry("adult.csv")

    assert entry is not None
    assert entry["key"] == "adult.csv"


def test_download_csv_uses_session_and_assigns_headerless_columns(config):
    session = Session(DEMO_RECORD)
    plugin = Plugin("7214275", config=config, session=session)

    data = plugin._download_csv(plugin._get_file_entry("adult.csv"))

    assert list(data.columns) == list(ADULT_COLUMN_MAPPING.values())
    assert len(data) == 4
    assert data.iloc[0]["salary-class"] == "<=50K"
    assert session.calls[-1][1]["timeout"] == (10, 60)


def test_pycanon_executes_on_small_synthetic_dataframe():
    data = pd.DataFrame(
        [
            [39, "Bachelors", "Clerical", "Not-in-family", "Male", "US", "<=50K"],
            [39, "Bachelors", "Clerical", "Not-in-family", "Male", "US", ">50K"],
            [50, "HS-grad", "Manager", "Husband", "Male", "US", "<=50K"],
            [50, "HS-grad", "Manager", "Husband", "Male", "US", ">50K"],
        ],
        columns=ADULT_QUASI_IDENTIFIERS + ADULT_SENSITIVE_ATTRIBUTES,
    )

    result = Plugin._run_pycanon_assessment(data)

    assert result["k_anonymity"] == 2
    assert result["l_diversity"] == 2
    # pyCANON 1.3.6 truncates exp(entropy) to int, so this balanced two-value
    # synthetic case currently reports 1 due to floating-point precision.
    assert result["entropy_l_diversity"] == 1
    assert result["t_closeness"] == pytest.approx(0)
    assert result["delta_disclosure"] == pytest.approx(0)


def test_pycanon_demo_handles_missing_file(config):
    record = deepcopy(DEMO_RECORD)
    record["files"] = []
    plugin = Plugin("7214275", config=config, session=Session(record))

    points, messages = plugin.data_privacy_01()

    assert points == 0
    assert "missing" in messages[0]["message"]


def test_pycanon_demo_handles_download_error(config):
    plugin = Plugin(
        "7214275",
        config=config,
        session=Session(DEMO_RECORD, download_status=503),
    )

    points, messages = plugin.data_privacy_01()

    assert points == 0
    assert "could not be completed" in messages[0]["message"]


def test_pycanon_demo_handles_unexpected_columns(config):
    plugin = Plugin(
        "7214275",
        config=config,
        session=Session(DEMO_RECORD, download_content=b"age,salary\n39,<=50K\n"),
    )

    points, messages = plugin.data_privacy_01()

    assert points == 0
    assert "2 columns; expected 15" in messages[0]["message"]


def test_pycanon_demo_handles_pycanon_exception(config, monkeypatch):
    plugin = Plugin("7214275", config=config, session=Session(DEMO_RECORD))

    def fail(_data):
        raise RuntimeError("synthetic pyCANON failure")

    monkeypatch.setattr(plugin, "_run_pycanon_assessment", fail)

    points, messages = plugin.data_privacy_01()

    assert points == 0
    assert "synthetic pyCANON failure" in messages[0]["message"]


def test_pycanon_success_score_means_execution_not_anonymity(config, monkeypatch):
    plugin = Plugin("7214275", config=config, session=Session(DEMO_RECORD))
    monkeypatch.setattr(
        plugin,
        "_run_pycanon_assessment",
        lambda _data: {
            "k_anonymity": 1,
            "l_diversity": 1,
            "entropy_l_diversity": 1,
            "t_closeness": 0.5,
            "delta_disclosure": 2.5,
        },
    )

    points, messages = plugin.data_privacy_01()
    message = " ".join(entry["message"] for entry in messages)

    assert points == 100
    assert "successfully performed" in message
    assert "does not mean that the dataset is 100% anonymous" in message
    assert "do not certify legal anonymisation or GDPR compliance" in message
