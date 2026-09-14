from __future__ import annotations

from configparser import ConfigParser
from pathlib import Path

import pytest

from fair_eva.plugin.fidelis.plugin import Plugin


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


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, record=RECORD):
        self.record = record
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
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
        "data_01", "data_02",
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
