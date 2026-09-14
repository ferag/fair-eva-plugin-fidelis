FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/fidelis
COPY . /opt/fidelis

# Installing this package also installs the FAIR EVA engine pinned by
# pyproject.toml to the requested 4.0.0 release.
RUN python -m pip install --no-cache-dir .

EXPOSE 9090
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://localhost:9090/v1.0/endpoints || exit 1

CMD ["python", "/opt/fidelis/docker/run_api.py"]
