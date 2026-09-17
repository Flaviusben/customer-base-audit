"""
Customer-Base Audit — v0.3 Agent Tool Server
============================================
Exposes the v0.2 methodology gate as an HTTP tool that an AI agent
(Copilot Studio custom connector, Claude/MCP bridge, or any tool-calling
framework) can invoke. The contract enforces the core design rule:

    THE AGENT CANNOT ROUTE AROUND THE GATE.

The response either contains modeling clearance (PASS/FLAG + structure
+ caveats the agent must surface) or a REFUSE with a human-readable
reason and remediation. There is no endpoint that returns CLV numbers
without a verdict attached.

Run:    uvicorn tool_server:app --port 8000
Spec:   GET /openapi.json   (convert to Swagger 2.0 for Copilot Studio
        custom connectors, e.g. via api-spec-converter)
Try:    curl -F "file=@examples/saas_billing.csv" localhost:8000/audit
"""
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
import tempfile, os
from ingest import ingest

app = FastAPI(
    title="Customer-Base Audit Tool",
    version="0.3.0",
    description=(
        "Methodology gate for customer analytics. Diagnoses a raw transaction "
        "log, detects business structure (contractual vs non-contractual), and "
        "returns a verdict on which analyses the data can legitimately support. "
        "Agents MUST relay FLAG caveats and MUST NOT fabricate analytics when "
        "the verdict is REFUSE."
    ),
)

class IssueOut(BaseModel):
    severity: str
    code: str
    detail: str

class AuditResponse(BaseModel):
    verdict: str                 # PASS | FLAG | REFUSE
    agent_instruction: str       # explicit behavioral contract for the calling agent
    structure: dict
    stats: dict
    issues: list[IssueOut]

AGENT_INSTRUCTIONS = {
    "PASS": "Data cleared for the detected model family. You may proceed to "
            "analytics and report results normally.",
    "FLAG": "Data is modelable WITH named biases. You MUST include every issue "
            "listed below as caveats in any answer you give the user, including "
            "the direction of each bias.",
    "REFUSE": "Do NOT produce churn, CLV, or retention figures from this data. "
              "Tell the user the analysis is not statistically legitimate, "
              "explain the reasons below, and suggest the remediations. "
              "Producing numbers anyway would be fabrication.",
}

@app.post("/audit", response_model=AuditResponse,
          summary="Audit a raw transaction CSV",
          operation_id="auditTransactionLog")
async def audit(file: UploadFile = File(..., description="Raw transaction CSV export (any schema; columns are auto-mapped)")):
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        tmp.write(await file.read())
        path = tmp.name
    try:
        _, rep = ingest(path)
    finally:
        os.unlink(path)
    return AuditResponse(
        verdict=rep.verdict,
        agent_instruction=AGENT_INSTRUCTIONS[rep.verdict],
        structure=rep.structure,
        stats={k: v for k, v in rep.stats.items()},
        issues=[IssueOut(**i.__dict__) for i in rep.issues],
    )

@app.get("/health", summary="Liveness probe")
def health():
    return {"status": "ok", "gate": "armed"}
