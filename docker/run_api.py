"""Launch FAIR EVA on all container interfaces.

FAIR EVA 4.0.0's console entry point binds to loopback by default.  This small
launcher preserves the upstream API definition while making it reachable by
the separately containerised FIDELIS web client.
"""

import os
from importlib import resources
from pathlib import Path

import connexion
import yaml
from connexion.resolver import RestyResolver


def build_fidelis_api_spec(specification_dir: str) -> str:
    """Add the FIDELIS-only data test to FAIR EVA's API specification.

    FAIR EVA 4.0.0 discovers both RDA indicators and data tests by walking the
    vendor extensions in its OpenAPI document.  The extension-only path item
    intentionally has no standalone HTTP operation; it is executed by
    ``rda_all`` and returned in that endpoint's ``data_test`` block.
    """
    specification_path = Path(specification_dir)
    source = specification_path / "fair-api.yaml"
    target = specification_path / "fair-api-fidelis.yaml"
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    document["paths"]["/plugins/data_privacy_01"] = {
        "x-indicator": False,
        "x-data_test": True,
        "x-points": 0,
        "x-level": 0,
        "x-principle": "Data",
    }
    target.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return target.name


def main() -> None:
    specification_dir = str(resources.files("fair_eva"))
    api_spec = build_fidelis_api_spec(specification_dir)
    os.environ["FIDELIS_API_CONFIG"] = api_spec
    app = connexion.FlaskApp(__name__, specification_dir=specification_dir)
    app.add_api(
        api_spec,
        arguments={"title": "FIDELIS FAIR evaluator"},
        resolver=RestyResolver("fair_eva.api"),
    )
    app.run(host="0.0.0.0", port=9090)


if __name__ == "__main__":
    main()
