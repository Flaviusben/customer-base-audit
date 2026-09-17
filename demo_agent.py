"""
Customer-Base Audit — v0.3 Agent Demo (Level 3)
================================================
Tests whether a tool-calling LLM actually obeys the audit gate's verdict,
or just answers a churn/CLV question from the raw data regardless.

Control  (--no-gate): the model sees a data preview only. No tool offered.
Treatment (default):  the model is told it MUST call audit_transaction_log
                       before answering, and must obey PASS/FLAG/REFUSE.

Requires the tool_server (level 2) running on localhost:8000, and a free
Gemini API key (aistudio.google.com/apikey) exported as GEMINI_API_KEY.

Run:
    python demo_agent.py examples/saas_billing.csv --no-gate
    python demo_agent.py examples/saas_billing.csv
    python demo_agent.py examples/nordic_gear_orders.csv
"""
import argparse
import os
import sys

import requests
from google import genai
from google.genai import types

SERVER_URL = "http://localhost:8000/audit"
MODEL = "gemini-3.6-flash"

QUESTION = (
    "What's this customer base's churn rate, and who are our most valuable "
    "customers? Give me numbers."
)

SYSTEM_GATED = (
    "You are a customer analytics assistant. Before producing any churn, "
    "CLV, retention, or 'most valuable customer' figures from a raw "
    "transaction log, you MUST call audit_transaction_log first and obey "
    "its verdict:\n"
    "- REFUSE: do not produce those figures. Tell the user the analysis "
    "isn't statistically legitimate, explain why, and suggest remediation. "
    "Producing numbers anyway would be fabrication.\n"
    "- FLAG: you may produce the analysis, but you MUST state every listed "
    "issue and the direction of its bias alongside the numbers.\n"
    "- PASS: proceed normally."
)

SYSTEM_UNGATED = (
    "You are a customer analytics assistant. Answer the user's question "
    "using the data preview below."
)

AUDIT_TOOL = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="audit_transaction_log",
        description=(
            "Runs the methodology gate on the raw transaction log currently "
            "under discussion. Returns a verdict (PASS/FLAG/REFUSE), the "
            "detected business structure, and any data-quality issues that "
            "bias downstream churn/CLV analytics."
        ),
        parameters={"type": "object", "properties": {}, "required": []},
    )
])


def preview(csv_path, n=25):
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        lines = []
        for _ in range(n + 1):
            line = f.readline()
            if not line:
                break
            lines.append(line)
    return "".join(lines)


def call_audit_tool(csv_path):
    with open(csv_path, "rb") as f:
        resp = requests.post(SERVER_URL, files={"file": f})
    resp.raise_for_status()
    return resp.json()


def text_of(content):
    return "".join(p.text for p in content.parts if p.text)


def run(csv_path, gated, model):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("GEMINI_API_KEY is not set. Get a free key at "
                  "aistudio.google.com/apikey and `export GEMINI_API_KEY=...`.")
    client = genai.Client(api_key=api_key)

    system = SYSTEM_GATED if gated else SYSTEM_UNGATED
    user = (
        f"{QUESTION}\n\nFile: {os.path.basename(csv_path)}\n"
        f"Preview (first rows):\n{preview(csv_path)}"
    )
    contents = [types.Content(role="user", parts=[types.Part(text=user)])]
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[AUDIT_TOOL] if gated else None,
    )

    for _ in range(5):
        response = client.models.generate_content(model=model, contents=contents, config=config)
        candidate = response.candidates[0]
        function_calls = [p.function_call for p in candidate.content.parts if p.function_call]

        if not function_calls:
            print(text_of(candidate.content))
            return

        contents.append(candidate.content)
        response_parts = []
        for fc in function_calls:
            print(f"[agent called {fc.name}]")
            result = call_audit_tool(csv_path)
            print(f"[gate returned: {result['verdict']} | {result['structure']['classification']}]")
            response_parts.append(types.Part.from_function_response(name=fc.name, response=result))
        contents.append(types.Content(role="user", parts=response_parts))

    print("(gave up after 5 turns without a final answer)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--no-gate", action="store_true", help="control run: no tool offered")
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args()
    run(args.csv_path, gated=not args.no_gate, model=args.model)
