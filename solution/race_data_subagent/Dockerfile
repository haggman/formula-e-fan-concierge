# Race-data subagent → Cloud Run (the agent IS the service).
# BUILD CONTEXT = repo root (needs shared/ alongside the package). Build via
# deploy/deploy_race_data_subagent.sh (Cloud Build + the cloudbuild.yaml next to
# this file), or locally:
#   docker build -f solution/race_data_subagent/Dockerfile -t race-data-subagent .
#
# PKG_DIR selects which package gets deployed (the starter/solution seam). It
# defaults to the reference; deploy the student build with:
#   --build-arg PKG_DIR=starter/race_data_subagent
#
# Layout produced (matches app.py's get_fast_api_app agents_dir expectation):
#   /app/app.py                       <- uvicorn app:app  (the service)
#   /app/agents/race_data_subagent/   <- the agent package (top-level name for ADK)
#   /app/shared/                      <- shared Firestore reader (now_tools imports it)
FROM python:3.12-slim

ARG PKG_DIR=solution/race_data_subagent

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY ${PKG_DIR}/requirements.txt ./
RUN pip install -r requirements.txt

# shared/ as a top-level package (now_tools does `from shared.state_client ...`)
COPY shared/ ./shared/
# the agent package under an ADK agents_dir, importable as `race_data_subagent`
COPY ${PKG_DIR}/ ./agents/race_data_subagent/
# the service entrypoint at the WORKDIR root
COPY ${PKG_DIR}/app.py ./app.py

# Cloud Run sets $PORT (default 8080). Do NOT hardcode it.
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
