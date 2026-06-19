"""MCP server wrapping the race-data subagent for CX. [SKELETON — see spec]

CX Agent Studio connects to an MCP tool over StreamableHttp only (no SSE), at a
URL ending /mcp, hosted on Cloud Run, authed with the CX Service Agent ID Token.
We expose ONE semantic tool so CX sees a clean orchestration surface:

    ask_race_data(question: str) -> str

Internally it runs the ADK root_agent (agent.py), which fuses Firestore "now" +
BigQuery "then" time-honestly and returns a natural-language answer.

Use the official MCP SDK or FastMCP. Mount StreamableHttp at /mcp. Deploy with
Dockerfile to Cloud Run (no-allow-unauthenticated); grant run.invoker to
service-{PROJECT_NUMBER}@gcp-sa-ces.iam.gserviceaccount.com.
"""
from __future__ import annotations

# from fastmcp import FastMCP
# from solution.race_data_subagent.agent import root_agent
#
# mcp = FastMCP("race-data")
#
# @mcp.tool()
# async def ask_race_data(question: str) -> str:
#     """Answer a Formula E race/stats question (R10 now + career then), time-honest."""
#     return await run_agent(root_agent, question)   # ADK runner glue, build conv.
#
# if __name__ == "__main__":
#     # StreamableHttp at /mcp on $PORT for Cloud Run
#     mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ["PORT"]),
#             path="/mcp")

raise NotImplementedError("MCP wrapper — implemented in the build conversation; see spec")
