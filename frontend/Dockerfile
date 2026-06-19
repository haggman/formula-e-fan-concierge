FROM python:3.12-slim

WORKDIR /app

# Install Python deps first (better layer caching)
COPY frontend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Shared models + the agent package (prompts/config/snapshot/state_client —
# the agent RUNTIME lives on Agent Engine; see frontend/requirements.txt)
COPY shared/ ./shared/
COPY solution/ ./solution/
# Bonus deploy path: either agent package must resolve in-container
# (AGENT_PACKAGE=starter.race_engineer ships your own agent).
COPY starter/ ./starter/

# The service itself (main.py, engineer_loop.py, agent_client.py, tts/stt, static UI)
COPY frontend/ ./frontend/

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

# Cloud Run sets PORT; uvicorn binds to it
CMD exec uvicorn frontend.main:app --host 0.0.0.0 --port ${PORT}
