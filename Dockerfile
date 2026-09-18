FROM python:3.12-slim AS runtime

COPY requirements.txt /tmp/requirements.txt
RUN apt-get update \
 && apt-get install -y --no-install-recommends chromium ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir -r /tmp/requirements.txt

RUN groupadd --gid 1000 app && useradd --uid 1000 --gid 1000 --create-home app
WORKDIR /app
COPY --chown=1000:1000 bin/ /app/bin/
COPY --chown=1000:1000 src/ /app/src/
COPY --chown=1000:1000 skills/ /app/skills/
COPY --chown=1000:1000 docs/ /app/docs/
COPY --chown=1000:1000 README.md SECURITY.md AGENTS.md THIRD_PARTY_NOTICES.md LICENSE requirements.txt /app/
RUN mkdir -p /state/receipts /ipc && chown -R app:app /state /ipc
USER 1000:1000
