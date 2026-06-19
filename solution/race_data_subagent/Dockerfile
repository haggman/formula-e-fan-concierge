# Race-data subagent MCP server → Cloud Run. [SKELETON]
# Serves StreamableHttp at /mcp on $PORT. Build from repo root:
#   docker build -f solution/race_data_subagent/Dockerfile -t race-data .
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# add: fastmcp, google-adk, google-cloud-firestore, toolbox-core
COPY shared/ ./shared/
COPY solution/race_data_subagent/ ./solution/race_data_subagent/
ENV PORT=8080
CMD ["python", "-m", "solution.race_data_subagent.mcp_server"]
