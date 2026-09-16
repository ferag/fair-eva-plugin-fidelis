"""Zenodo-backed FIDELIS plugin for FAIR EVA 4.0.0.

The plugin deliberately consumes Zenodo's record API instead of flattening the
less expressive OAI-DC representation.  FAIR EVA still receives its historical
four-column metadata dataframe, while the repository-specific indicators use
the structured JSON response and the file manifest directly.
"""

from __future__ import annotations

from configparser import ConfigParser
from io import BytesIO
import logging
import math
import mimetypes
import os
import re
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import pandas as pd
import requests
from pycanon import anonymity
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fair_eva.api.evaluator import EvaluatorBase

logger = logging.getLogger("fair_eva.api.plugin.fidelis")

DATACITE_SCHEMA = "https://schema.datacite.org/meta/kernel-4.5/"
ZENODO_SCHEMA = "https://zenodo.org/schemas/records/record-v1.0.0.json"
DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
ZENODO_DOI_RE = re.compile(r"10\.5281/zenodo\.(\d+)", re.IGNORECASE)
ZENODO_URL_RE = re.compile(r"(?:records?|record|api/records)/(\d+)", re.IGNORECASE)

PYCANON_DEMO_RECORD_ID = "7214275"
PYCANON_DEMO_DOI = "10.5281/zenodo.7214275"
PYCANON_DEMO_FILENAME = "adult.csv"
PYCANON_DEMO_MAX_BYTES = 10 * 1024 * 1024

# Zenodo 7214275 contains the original headerless UCI Adult CSV.  These names
# are therefore an explicit ordinal mapping, not inferred from arbitrary data.
ADULT_COLUMN_MAPPING = {
    0: "age",
    1: "workclass",
    2: "fnlwgt",
    3: "education",
    4: "education-num",
    5: "marital-status",
    6: "occupation",
    7: "relationship",
    8: "race",
    9: "sex",
    10: "capital-gain",
    11: "capital-loss",
    12: "hours-per-week",
    13: "native-country",
    14: "salary-class",
}
ADULT_QUASI_IDENTIFIERS = [
    "age",
    "education",
    "occupation",
    "relationship",
    "sex",
    "native-country",
]
ADULT_SENSITIVE_ATTRIBUTES = ["salary-class"]


def _message(message: str, points: float) -> list[dict[str, Any]]:
    return [{"message": message, "points": points}]


def _values(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


class Plugin(EvaluatorBase):
    """Evaluate public or token-accessible Zenodo records for FIDELIS."""

    def __init__(
        self,
        item_id: str,
        api_endpoint: str | None = None,
        lang: str = "en",
        config: ConfigParser | None = None,
        name: str = "fidelis",
        session: requests.Session | None = None,
    ) -> None:
        if config is None:
            config = ConfigParser()
        fidelis_api_config = os.getenv("FIDELIS_API_CONFIG", "").strip()
        if fidelis_api_config:
            config.set("Generic", "api_config", fidelis_api_config)
        super().__init__(item_id, api_endpoint, lang, config, name)

        self.session = session or requests.Session()
        if session is None:
            retry = Retry(
                total=3,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=("GET",),
                respect_retry_after_header=True,
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "FIDELIS-FAIR-EVA/0.1 (+https://github.com/ferag/fair-eva-plugin-fidelis)",
            }
        )
        token = os.getenv("ZENODO_ACCESS_TOKEN", "").strip()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

        self.api_endpoint = self._normalise_endpoint(self.api_endpoint)
        self.original_item_id = item_id.strip()
        self.record_id = self._resolve_record_id(self.original_item_id)
        self.record = self._get_record(self.record_id)
        self.item_id = self.record.get("doi") or self.original_item_id
        self.files = list(self.record.get("files") or [])
        self.file_list = self._build_file_list()
        self.metadata = self.get_metadata()
        self.metadata_quality = 0
        self.cvs = []

        if self.metadata.empty:
            raise ValueError(f"Zenodo record {self.original_item_id!r} returned no metadata")

    @staticmethod
    def _normalise_endpoint(endpoint: str | None) -> str:
        endpoint = (endpoint or "https://zenodo.org/api").rstrip("/")
        if endpoint.endswith("/records"):
            endpoint = endpoint[: -len("/records")]
        if not endpoint.endswith("/api"):
            endpoint = f"{endpoint}/api"
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or parsed.hostname not in {"zenodo.org", "sandbox.zenodo.org"}:
            raise ValueError("FIDELIS only accepts HTTPS endpoints at zenodo.org or sandbox.zenodo.org")
        return endpoint

    def _resolve_record_id(self, identifier: str) -> str:
        if identifier.isdigit():
            return identifier

        match = ZENODO_DOI_RE.search(identifier) or ZENODO_URL_RE.search(identifier)
        if match:
            return match.group(1)

        doi_match = DOI_RE.search(identifier)
        if not doi_match:
            raise ValueError(
                "Use a Zenodo record ID, Zenodo record URL, or DOI (for example "
                "10.5281/zenodo.10897)."
            )

        doi = doi_match.group(0).rstrip(".,;)")
        response = self.session.get(
            f"{self.api_endpoint}/records",
            params={"q": f'doi:\"{doi}\"', "size": 1, "all_versions": "true"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        hits = payload.get("hits", {}).get("hits", []) if isinstance(payload, dict) else []
        if not hits:
            raise ValueError(f"No Zenodo record found for DOI {doi}")
        return str(hits[0]["id"])

    def _get_record(self, record_id: str) -> dict[str, Any]:
        response = self.session.get(f"{self.api_endpoint}/records/{quote(record_id)}", timeout=30)
        if response.status_code == 404:
            raise ValueError(f"Zenodo record {record_id} was not found")
        response.raise_for_status()
        record = response.json()
        if not isinstance(record, dict):
            raise ValueError("Zenodo returned an unexpected record representation")
        return record

    @classmethod
    def get_ids(cls, api_endpoint: str | None, pattern_to_query: str) -> list[str]:
        """Resolve a Zenodo search expression to at most 25 record identifiers."""
        endpoint = cls._normalise_endpoint(api_endpoint)
        response = requests.get(
            f"{endpoint}/records",
            params={"q": pattern_to_query, "size": 25},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        return [str(hit["id"]) for hit in payload.get("hits", {}).get("hits", [])]

    def _build_file_list(self) -> pd.DataFrame:
        rows = []
        for entry in self.files:
            filename = entry.get("key") or entry.get("filename") or ""
            extension = os.path.splitext(filename.lower())[1]
            media_type = entry.get("mimetype") or mimetypes.guess_type(filename)[0] or "application/octet-stream"
            link = (entry.get("links") or {}).get("self") or (entry.get("links") or {}).get("content")
            rows.append([filename, extension, media_type, link, entry.get("checksum"), entry.get("size")])
        return pd.DataFrame(
            rows, columns=["name", "extension", "format", "link", "checksum", "size"]
        )

    def get_metadata(self) -> pd.DataFrame:
        md = self.record.get("metadata") or {}
        rows: list[list[Any]] = []

        def add(element: str, value: Any, qualifier: str = "", schema: str = DATACITE_SCHEMA) -> None:
            for single in _values(value):
                if single not in (None, "", [], {}):
                    rows.append([schema, element, qualifier, str(single)])

        doi = self.record.get("doi") or md.get("doi")
        add("identifier", doi, "doi")
        add("identifier", self.record.get("doi_url") or (f"https://doi.org/{doi}" if doi else None), "uri")
        add("identifier", (self.record.get("links") or {}).get("self_html"), "landingPage")
        add("identifier", (self.record.get("links") or {}).get("self"), "metadata")
        add("identifier", self.record.get("conceptdoi"), "conceptDoi")
        add("title", md.get("title") or self.record.get("title"))
        add("description", md.get("description"), "abstract")
        add("publisher", "Zenodo")
        add("date", md.get("publication_date"), "issued")
        add("date", self.record.get("created"), "created")
        add("date", self.record.get("modified") or self.record.get("updated"), "modified")
        add("language", md.get("language"), "iso")
        add("version", md.get("version"))

        resource_type = md.get("resource_type") or {}
        if isinstance(resource_type, dict):
            add("type", resource_type.get("type"), "resourceTypeGeneral")
            add("type", resource_type.get("title"), "resourceType")
        else:
            add("type", resource_type)

        for creator in md.get("creators") or []:
            add("creator", creator.get("name"), "name")
            add("creator", creator.get("affiliation"), "affiliation")
            add("creator", creator.get("orcid"), "orcid")
            add("creator", creator.get("gnd"), "gnd")
        for contributor in md.get("contributors") or []:
            add("contributor", contributor.get("name"), contributor.get("type", "name"))
            add("contributor", contributor.get("orcid"), "orcid")
            add("contributor", contributor.get("affiliation"), "affiliation")

        for keyword in md.get("keywords") or []:
            add("subject", keyword, "keyword")
        for subject in md.get("subjects") or []:
            if isinstance(subject, dict):
                add("subject", subject.get("term") or subject.get("subject"), subject.get("scheme", "controlled"))
                add("subject", subject.get("identifier"), "uri")
            else:
                add("subject", subject)

        access_right = md.get("access_right")
        add("rights", access_right, "accessRights")
        add("rights", md.get("access_conditions"), "accessConditions")
        add("rights", md.get("embargo_date"), "embargoDate")
        license_data = md.get("license") or {}
        if isinstance(license_data, dict):
            license_id = license_data.get("id")
            add("rights", license_id, "license")
            add("license", license_id)
            add("license", license_data.get("url"), "uri")
            add("license", license_data.get("title"), "title")
        else:
            add("rights", license_data, "license")
            add("license", license_data)

        for relation in md.get("related_identifiers") or []:
            add("relation", relation.get("identifier"), relation.get("relation", "related"))
            add("relationType", relation.get("relation"), "controlled")
            add("relatedResourceType", relation.get("resource_type"), "controlled")

        for funding in md.get("grants") or md.get("funding") or []:
            if not isinstance(funding, dict):
                add("fundingReference", funding)
                continue
            funder = funding.get("funder") or {}
            award = funding.get("award") or {}
            add("fundingReference", funder.get("name") if isinstance(funder, dict) else funder, "funderName")
            if isinstance(funder, dict):
                add("fundingReference", funder.get("id"), "funderIdentifier")
            add("fundingReference", award.get("number") if isinstance(award, dict) else award, "awardNumber")
            if isinstance(award, dict):
                add("fundingReference", award.get("id"), "awardUri")

        for community in md.get("communities") or []:
            add("community", community.get("id") if isinstance(community, dict) else community, "identifier", ZENODO_SCHEMA)

        add("provenance", md.get("notes"), "notes", ZENODO_SCHEMA)
        relations = md.get("relations") or {}
        for relation_name, relation_values in relations.items():
            for relation in _values(relation_values):
                add("provenance", relation, relation_name, ZENODO_SCHEMA)

        for entry in self.files:
            filename = entry.get("key") or entry.get("filename") or ""
            links = entry.get("links") or {}
            add("file", filename, "name", ZENODO_SCHEMA)
            add("file", links.get("self") or links.get("content"), "downloadUrl", ZENODO_SCHEMA)
            add("file", entry.get("checksum"), "checksum", ZENODO_SCHEMA)
            add("file", entry.get("size"), "size", ZENODO_SCHEMA)
            add("format", entry.get("mimetype") or mimetypes.guess_type(filename)[0], "mediaType")
            add("format", os.path.splitext(filename.lower())[1], "extension")

        return pd.DataFrame(rows, columns=["metadata_schema", "element", "qualifier", "text_value"])

    def _score(self, condition: bool, success: str, failure: str) -> tuple[int, list[dict[str, Any]]]:
        points = 100 if condition else 0
        return points, _message(success if condition else failure, points)

    def _metadata_values(self, element: str, qualifier: str | None = None) -> list[str]:
        selected = self.metadata[self.metadata["element"] == element]
        if qualifier is not None:
            selected = selected[selected["qualifier"] == qualifier]
        return selected["text_value"].tolist()

    def _has_doi(self) -> bool:
        return bool(DOI_RE.search(str(self.record.get("doi") or "")))

    def _data_available(self) -> bool:
        md = self.record.get("metadata") or {}
        access = md.get("access_right", "open")
        return bool(self.files) or (access in {"restricted", "embargoed"} and bool(md.get("access_conditions")))

    def _related(self) -> list[dict[str, Any]]:
        return list((self.record.get("metadata") or {}).get("related_identifiers") or [])

    def _standard_files_score(self) -> float:
        if not self.files:
            return 0
        configured = {str(value).lower() for value in self.supported_data_formats}
        standard = sum(1 for ext in self.file_list["extension"] if ext.lower() in configured)
        return round(100 * standard / len(self.files), 2)

    def _is_pycanon_demo_dataset(self) -> bool:
        """Return whether this is the one record configured for the demo."""
        doi = str(self.record.get("doi") or (self.record.get("metadata") or {}).get("doi") or "")
        return self.record_id == PYCANON_DEMO_RECORD_ID and doi.lower() == PYCANON_DEMO_DOI

    def _get_file_entry(self, filename: str) -> dict[str, Any] | None:
        """Find an exact filename in the Zenodo manifest."""
        return next(
            (
                entry
                for entry in self.files
                if (entry.get("key") or entry.get("filename") or "") == filename
            ),
            None,
        )

    def _download_csv(self, file_entry: dict[str, Any]) -> pd.DataFrame:
        """Download and parse the fixed, headerless Adult demonstrator CSV."""
        filename = file_entry.get("key") or file_entry.get("filename") or ""
        if filename != PYCANON_DEMO_FILENAME:
            raise ValueError(f"Expected {PYCANON_DEMO_FILENAME!r}, received {filename!r}")

        declared_size = file_entry.get("size")
        if declared_size is not None and int(declared_size) > PYCANON_DEMO_MAX_BYTES:
            raise ValueError("The declared Adult CSV exceeds the 10 MiB demonstrator limit")

        links = file_entry.get("links") or {}
        download_url = links.get("content") or links.get("self")
        if not download_url:
            raise ValueError("adult.csv has no machine-actionable download URL")

        parsed_url = urlparse(download_url)
        endpoint_host = urlparse(self.api_endpoint).hostname
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname != endpoint_host
            or not parsed_url.path.endswith(f"/{PYCANON_DEMO_FILENAME}/content")
        ):
            raise ValueError("adult.csv download URL is not an expected Zenodo content URL")

        response = self.session.get(download_url, timeout=(10, 60))
        response.raise_for_status()
        content = response.content
        if len(content) > PYCANON_DEMO_MAX_BYTES:
            raise ValueError("The downloaded Adult CSV exceeds the 10 MiB demonstrator limit")

        data = pd.read_csv(
            BytesIO(content),
            header=None,
            skipinitialspace=True,
            keep_default_na=False,
        )
        expected_columns = list(ADULT_COLUMN_MAPPING.values())
        if data.empty:
            raise ValueError("adult.csv is empty")
        if data.shape[1] != len(expected_columns):
            raise ValueError(
                f"adult.csv has {data.shape[1]} columns; expected {len(expected_columns)}"
            )

        # The immutable Zenodo file is headerless.  Supporting a matching
        # header as well makes the parser explicit without guessing aliases.
        first_row = [str(value).strip() for value in data.iloc[0].tolist()]
        if first_row == expected_columns:
            data = data.iloc[1:].reset_index(drop=True)
        data.columns = expected_columns
        return data

    @staticmethod
    def _run_pycanon_assessment(data: pd.DataFrame) -> dict[str, int | float]:
        """Calculate pyCANON metrics for the fixed Adult configuration."""
        required = ADULT_QUASI_IDENTIFIERS + ADULT_SENSITIVE_ATTRIBUTES
        missing = [column for column in required if column not in data.columns]
        if missing:
            raise ValueError(f"adult.csv is missing expected columns: {', '.join(missing)}")

        return {
            "k_anonymity": int(anonymity.k_anonymity(data, ADULT_QUASI_IDENTIFIERS)),
            "l_diversity": int(
                anonymity.l_diversity(
                    data, ADULT_QUASI_IDENTIFIERS, ADULT_SENSITIVE_ATTRIBUTES
                )
            ),
            "entropy_l_diversity": float(
                anonymity.entropy_l_diversity(
                    data, ADULT_QUASI_IDENTIFIERS, ADULT_SENSITIVE_ATTRIBUTES
                )
            ),
            "t_closeness": float(
                anonymity.t_closeness(
                    data, ADULT_QUASI_IDENTIFIERS, ADULT_SENSITIVE_ATTRIBUTES
                )
            ),
            "delta_disclosure": float(
                anonymity.delta_disclosure(
                    data, ADULT_QUASI_IDENTIFIERS, ADULT_SENSITIVE_ATTRIBUTES
                )
            ),
        }

    @staticmethod
    def _format_privacy_metric(value: int | float) -> str:
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return f"{value:.6g}"

    # Findable
    def rda_f1_01m(self):
        return self._score(self._has_doi(), "Metadata is persistently identified by a DOI.", "No metadata DOI was found.")

    def rda_f1_01d(self):
        return self._score(self._has_doi(), "The digital object is persistently identified by a DOI.", "No data DOI was found.")

    def rda_f1_02m(self):
        return self.rda_f1_01m()

    def rda_f1_02d(self):
        return self.rda_f1_01d()

    def rda_f2_01m(self):
        required = {
            "title": self._metadata_values("title"),
            "creator": self._metadata_values("creator", "name"),
            "description": self._metadata_values("description"),
            "publication date": self._metadata_values("date", "issued"),
            "resource type": self._metadata_values("type"),
            "identifier": self._metadata_values("identifier", "doi"),
            "access rights": self._metadata_values("rights", "accessRights"),
            "license": self._metadata_values("license"),
            "subject": self._metadata_values("subject"),
            "version": self._metadata_values("version"),
        }
        present = [name for name, values in required.items() if values]
        missing = [name for name, values in required.items() if not values]
        points = round(100 * len(present) / len(required), 2)
        self.metadata_quality = points
        return points, _message(
            f"Richness fields present: {', '.join(present)}. Missing/recommended: {', '.join(missing) or 'none'}.",
            points,
        )

    def rda_f3_01m(self):
        return self._score(self._has_doi(), "Metadata explicitly includes the DOI of the object.", "Metadata does not include a data identifier.")

    def rda_f4_01m(self):
        return self._score(bool(self.record), "Metadata is indexed by Zenodo and exposed through REST API and OAI-PMH.", "Metadata could not be retrieved from Zenodo's index.")

    # Accessible
    def rda_a1_01m(self):
        return self._score(bool(self.record), "Metadata is retrievable from Zenodo over HTTPS.", "Metadata is not retrievable.")

    def rda_a1_02m(self):
        return self._score(bool((self.record.get("links") or {}).get("self_html")), "A human-readable Zenodo landing page is available.", "No human-readable metadata page was found.")

    def rda_a1_02d(self):
        access = (self.record.get("metadata") or {}).get("access_right", "open")
        return self._score(bool(access), f"Zenodo declares the data access mode: {access}.", "No data access information was found.")

    def rda_a1_03m(self):
        return self.rda_a1_01m()

    def rda_a1_03d(self):
        return self._score(self._data_available(), "Data files or access instructions resolve from the record.", "Neither files nor access instructions were found.")

    def rda_a1_04m(self, return_protocol: bool = False):
        result = (100, _message("Metadata is accessed through the standard HTTPS protocol.", 100))
        return (*result, "https") if return_protocol else result

    def rda_a1_04d(self):
        return self._score(self._data_available(), "Data or access instructions are available through HTTPS.", "No HTTPS data retrieval route was found.")

    def rda_a1_05d(self):
        open_files = bool(self.files) and (self.record.get("metadata") or {}).get("access_right", "open") == "open"
        return self._score(open_files, "File URLs are exposed by a machine-actionable JSON API.", "Automated file retrieval is not available without an access decision.")

    def rda_a1_1_01m(self):
        return 100, _message("HTTPS is open, free and universally implementable.", 100)

    def rda_a1_1_01d(self):
        return self._score(self._data_available(), "The data retrieval protocol is free to implement.", "No data retrieval route was found.")

    def rda_a1_2_01d(self):
        access = (self.record.get("metadata") or {}).get("access_right", "open")
        detail = "No authentication is needed for open files." if access == "open" else "Zenodo supports token/request-based authorisation for non-open files."
        return 100, _message(detail, 100)

    def rda_a2_01m(self):
        return self._score(self._has_doi(), "Zenodo keeps the DOI metadata record available independently of file access.", "No persistent metadata identifier was found.")

    # Interoperable
    def rda_i1_01m(self):
        return 100, _message("Zenodo exposes structured JSON and DataCite/Dublin Core serialisations.", 100)

    def rda_i1_01d(self):
        points = self._standard_files_score()
        return points, _message(f"{points}% of files use a configured standard format.", points)

    def rda_i1_02m(self):
        return 100, _message("Metadata is machine-actionable and available in JSON, DataCite XML and Dublin Core XML.", 100)

    def rda_i1_02d(self):
        return self.rda_i1_01d()

    def rda_i2_01m(self):
        controlled = bool(
            self._metadata_values("rights", "license")
            or self._metadata_values("creator", "orcid")
            or self._metadata_values("relationType")
            or self._metadata_values("type", "resourceTypeGeneral")
        )
        return self._score(controlled, "Metadata uses controlled values for licences, identifiers, relations or resource types.", "No controlled vocabulary values were detected.")

    def rda_i2_01d(self):
        return self.rda_i1_01d()

    def rda_i3_01m(self):
        references = self._metadata_values("creator", "orcid") + self._metadata_values("fundingReference", "funderIdentifier")
        return self._score(bool(references), "Qualified references to people or funders are present.", "No qualified reference to people, organisations or funders was found.")

    def rda_i3_01d(self):
        data_relations = [r for r in self._related() if r.get("resource_type") in {"dataset", "software", "other"}]
        return self._score(bool(data_relations), "Qualified references to related data are present.", "No qualified references to related data were found.")

    def rda_i3_02m(self):
        return self._score(bool(self._related()), "Metadata includes persistent references to related resources.", "No related persistent identifiers were found.")

    def rda_i3_02d(self):
        return self.rda_i3_01d()

    def rda_i3_03m(self):
        metadata_relations = {"hasMetadata", "isMetadataFor", "isDescribedBy", "describes"}
        found = any(r.get("relation") in metadata_relations for r in self._related())
        return self._score(found, "A qualified metadata-to-metadata reference is present.", "No qualified metadata-to-metadata reference was found.")

    def rda_i3_04m(self):
        qualified = any(r.get("identifier") and r.get("relation") for r in self._related())
        return self._score(qualified, "Related resources include explicit relation types.", "No qualified relation between resources was found.")

    # Reusable
    def rda_r1_01m(self):
        fields = ["description", "subject", "creator", "rights", "type", "date"]
        present = [field for field in fields if self._metadata_values(field)]
        points = round(100 * len(present) / len(fields), 2)
        return points, _message(f"Reuse-relevant metadata groups present: {', '.join(present) or 'none'}.", points)

    def rda_r1_1_01m(self, license_list=None, **kwargs):
        licenses = self._metadata_values("license")
        return self._score(bool(licenses), f"Reuse licence found: {', '.join(licenses)}.", "No reuse licence was found.")

    def rda_r1_1_02m(self, license_list=None, machine_readable: bool = False, **kwargs):
        licenses = list(license_list or self._metadata_values("license"))
        standard = any(re.match(r"^[a-z][a-z0-9.+-]*(?:-[a-z0-9.+]+)+$", value, re.I) for value in licenses)
        return self._score(standard, f"Zenodo licence identifier is controlled: {', '.join(licenses)}.", "No controlled licence identifier was found.")

    def rda_r1_1_03m(self, machine_readable: bool = True, **kwargs):
        return self.rda_r1_1_02m(machine_readable=machine_readable)

    def rda_r1_2_01m(self):
        md = self.record.get("metadata") or {}
        relations = md.get("relations") or {}
        detailed = bool(md.get("notes") or md.get("version") or md.get("related_identifiers"))
        basic = bool(relations.get("version") or self.record.get("conceptrecid"))
        points = 100 if detailed else (50 if basic else 0)
        return points, _message("Detailed provenance/version metadata is present." if detailed else "Only Zenodo's basic record-version provenance is present." if basic else "No provenance information was found.", points)

    def rda_r1_2_02m(self):
        points, _ = self.rda_r1_2_01m()
        return points, _message("Provenance is expressed as structured Zenodo/DataCite metadata." if points else "No structured provenance information was found.", points)

    def rda_r1_3_01m(self, **kwargs):
        return 100, _message("Zenodo exposes the record using the DataCite Metadata Schema.", 100)

    def rda_r1_3_01d(self, **kwargs):
        points = self._standard_files_score()
        return points, _message(f"{points}% of files match the configured community/general format list.", points)

    def rda_r1_3_02m(self, **kwargs):
        return 100, _message("DataCite metadata is available in a machine-understandable serialisation.", 100)

    def rda_r1_3_02d(self, **kwargs):
        return self.rda_r1_3_01d()

    # FAIR EVA 4.0.0 also exposes two optional repository data tests.  The
    # upstream schema does not assign formal RDA indicator identifiers to them.
    def data_01(self):
        checksums = [entry.get("checksum") for entry in self.files]
        complete = bool(checksums) and all(checksums)
        return self._score(complete, "Every exposed file has an integrity checksum.", "One or more files have no integrity checksum.")

    def data_02(self):
        complete = bool(self.files) and all(
            entry.get("size") is not None
            and bool((entry.get("links") or {}).get("self") or (entry.get("links") or {}).get("content"))
            for entry in self.files
        )
        return self._score(complete, "Every exposed file has a size and machine-actionable download URL.", "One or more files lack a size or download URL.")

    def data_privacy_01(self):
        """Run the dataset-specific pyCANON privacy demonstrator."""
        if not self._is_pycanon_demo_dataset():
            message = (
                "Not applicable: the pyCANON privacy demonstrator is currently configured "
                "only for the UCI Adult demonstrator dataset (Zenodo 7214275)."
            )
            return 0, _message(message, 0)

        file_entry = self._get_file_entry(PYCANON_DEMO_FILENAME)
        if file_entry is None:
            return 0, _message(
                "pyCANON privacy demonstrator could not run: adult.csv is missing from "
                "the Zenodo file manifest.",
                0,
            )

        try:
            data = self._download_csv(file_entry)
            metrics = self._run_pycanon_assessment(data)
        except Exception as error:
            logger.exception("pyCANON privacy demonstrator failed")
            return 0, _message(
                f"pyCANON privacy demonstrator could not be completed: {error}", 0
            )

        message_lines = (
            "Privacy/anonymisation demonstrator using pyCANON.",
            f"Dataset: UCI Adult (Zenodo 7214275); rows assessed: {len(data)}.",
            f"Quasi-identifiers: {', '.join(ADULT_QUASI_IDENTIFIERS)}.",
            f"Sensitive attribute: {', '.join(ADULT_SENSITIVE_ATTRIBUTES)}.",
            f"k-anonymity: k = {self._format_privacy_metric(metrics['k_anonymity'])}.",
            f"l-diversity: l = {self._format_privacy_metric(metrics['l_diversity'])}.",
            "Entropy l-diversity: l = "
            f"{self._format_privacy_metric(metrics['entropy_l_diversity'])}.",
            f"t-closeness: t = {self._format_privacy_metric(metrics['t_closeness'])}.",
            "Delta-disclosure privacy: delta = "
            f"{self._format_privacy_metric(metrics['delta_disclosure'])}.",
            "Score 100 means that the privacy assessment was successfully performed; "
            "it does not mean that the dataset is 100% anonymous. These risk-related "
            "anonymisation metrics apply only to the configured attributes and do not "
            "certify legal anonymisation or GDPR compliance.",
        )
        messages = []
        for line in message_lines:
            messages.extend(_message(line, 100))
        return 100, messages
