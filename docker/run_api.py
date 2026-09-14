"""Launch FAIR EVA on all container interfaces.

FAIR EVA 4.0.0's console entry point binds to loopback by default.  This small
launcher preserves the upstream API definition while making it reachable by
the separately containerised FIDELIS web client.
"""

from importlib import resources

import connexion
from connexion.resolver import RestyResolver


def main() -> None:
    specification_dir = str(resources.files("fair_eva"))
    app = connexion.FlaskApp(__name__, specification_dir=specification_dir)
    app.add_api(
        "fair-api.yaml",
        arguments={"title": "FIDELIS FAIR evaluator"},
        resolver=RestyResolver("fair_eva.api"),
    )
    app.run(host="0.0.0.0", port=9090)


if __name__ == "__main__":
    main()
