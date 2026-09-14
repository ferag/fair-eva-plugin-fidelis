FROM python:3.11-slim

ARG WEB_CLIENT_REF=0ec6808f92f6a1ad31dba819ace523a693d7c88d

RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir \
       "git+https://github.com/IFCA-Advanced-Computing/fair_eva_web_client.git@${WEB_CLIENT_REF}"

WORKDIR /app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
  CMD curl -fsS http://localhost:8000/ || exit 1

CMD ["fair-eva-web-client", "--host", "0.0.0.0", "--port", "8000"]
