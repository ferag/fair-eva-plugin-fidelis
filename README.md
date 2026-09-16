# FIDELIS FAIR Evaluator

FIDELIS is a Zenodo-specific distribution of [FAIR EVA 4.0.0](https://github.com/IFCA-Advanced-Computing/FAIR_eva/releases/tag/4.0.0). It combines:

- the FAIR EVA evaluation engine, pinned to release `4.0.0`;
- the `fidelis` plugin, which reads structured metadata and files from the Zenodo REST API;
- the FAIR EVA web client, preconfigured and branded as **FIDELIS FAIR Evaluator**.

## Prerequisites

For the recommended route, the only host dependency is **Docker with Compose v2**. Application dependencies are installed inside the images during the first build; running `pip install` on the host is not required.

- Windows/macOS: install and start [Docker Desktop](https://docs.docker.com/desktop/).
- Linux: install [Docker Engine](https://docs.docker.com/engine/install/) and the [Compose plugin](https://docs.docker.com/compose/install/linux/).

Check the installation without starting any container:

```bash
python fidelis.py check
```

If Docker is missing, the command reports what must be installed. Docker is a system application and therefore cannot be installed through a Python `requirements.txt` file.

## Run it

The cross-platform launcher checks Docker and Compose before building and starting both services:

```bash
python fidelis.py
```

Then open <http://localhost:8000>. To run in the background or stop the stack:

```bash
python fidelis.py --detach
python fidelis.py down
```

The equivalent direct Compose command is:

```bash
docker compose up --build
```

Paste a Zenodo DOI, record URL, or numeric record ID, and run the evaluation. Examples:

- `10.5281/zenodo.10897`
- `https://zenodo.org/records/10897`
- `10897`

The FAIR EVA API and its OpenAPI UI are also exposed at <http://localhost:9090/v1.0/ui/>. Stop the stack with `docker compose down`.

To change ports, copy `.env.example` to `.env` and edit the values. Public Zenodo records need no credential. `ZENODO_ACCESS_TOKEN` is optional and is sent as an `Authorization: Bearer` header when present; it is never placed in a URL.

## What the plugin maps

Zenodo's JSON is converted to the four-column dataframe required by FAIR EVA 4.0.0: `metadata_schema`, `element`, `qualifier`, and `text_value`.

| FAIR assessment need | Zenodo source |
|---|---|
| Persistent identification | record DOI, concept DOI, DOI URL |
| Discovery richness | title, description, creators, dates, resource type, keywords, version |
| Accessibility | `access_right`, access conditions, landing page and file URLs |
| Interoperability | DataCite/Zenodo schema, ORCID, relation types, MIME types and extensions |
| Reusability | licence, funding, related identifiers, provenance/versioning and file manifest |

The plugin overrides repository-sensitive indicators instead of relying on OAI-PMH-oriented assumptions in the generic evaluator. In particular, it distinguishes metadata accessibility from file accessibility and does not treat restricted data as automatically open.

### pyCANON privacy demonstrator

FAIR EVA normally evaluates FAIRness from metadata and repository behaviour. FIDELIS additionally includes a deliberately narrow demonstrator showing that a plugin can inspect dataset content and run a domain-specific assessment.

The `data_privacy_01` test applies only to the [UCI Adult dataset on Zenodo](https://doi.org/10.5281/zenodo.7214275). It downloads `adult.csv` from the machine-actionable URL in the Zenodo API response and uses [pyCANON](https://github.com/IFCA-Advanced-Computing/pycanon) with:

- quasi-identifiers: `age`, `education`, `occupation`, `relationship`, `sex`, `native-country`;
- sensitive attribute: `salary-class`;
- metrics: k-anonymity, l-diversity, entropy l-diversity, t-closeness and delta-disclosure privacy.

The deposited CSV has no header row. FIDELIS therefore applies the documented 15-column UCI Adult schema by position: `age`, `workclass`, `fnlwgt`, `education`, `education-num`, `marital-status`, `occupation`, `relationship`, `race`, `sex`, `capital-gain`, `capital-loss`, `hours-per-week`, `native-country`, `salary-class`. It does not infer or guess alternative columns.

This is a plugin-specific data test, not an RDA FAIR Data Maturity Model indicator, and it does not contribute to the four FAIR principle scores. A score of 100 means only that the configured privacy assessment was successfully performed. The reported values describe privacy/risk-related characteristics for the predefined attributes; they are not proof or legal certification of anonymisation or GDPR compliance. Other Zenodo records are reported as not applicable.

## Configuration

The default endpoint and mappings live in `fair_eva/plugin/fidelis/config.ini`. The interface is intentionally restricted to `FIDELIS (Zenodo)` through `config/plugins.json`.

Supported environment variables:

| Variable | Default | Purpose |
|---|---:|---|
| `FIDELIS_WEB_PORT` | `8000` | Host port for the interface |
| `FIDELIS_API_PORT` | `9090` | Host port for the FAIR EVA API |
| `ZENODO_ACCESS_TOKEN` | empty | Optional token for authorised Zenodo access |

## Development

Docker is not needed to develop or test the Python plugin itself. Install it in an isolated environment; `requirements-dev.txt` delegates to `pyproject.toml`, which remains the single source of dependency versions:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest
```

Re-run the installation command after changing plugin source code. FAIR EVA 4.0.0 is a regular Python package, so an editable install cannot safely merge the external `fair_eva.plugin.fidelis` namespace into it.

The package uses the `fair_eva.plugin.fidelis` namespace expected by FAIR EVA 4.0.0. A complete API smoke test can be run after starting Compose:

```bash
curl -fsS http://localhost:9090/v1.0/endpoints
curl -fsS -X POST http://localhost:9090/v1.0/rda/rda_all \
  -H 'Content-Type: application/json' \
  -d '{"id":"10.5281/zenodo.10897","repo":"fidelis","lang":"en"}'
```

## Version policy

The engine is pinned to the Git tag `4.0.0`. The web client is pinned to commit `0ec6808f92f6a1ad31dba819ace523a693d7c88d` so builds remain reproducible. Both references should be updated deliberately and tested together.

## Licence

Apache-2.0.
