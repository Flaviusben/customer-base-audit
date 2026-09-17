# Testing the gate — three levels

Files to add to the repo from this batch: `ingest.py` (updated — adds `ORDER_LINES` detection), `examples/nordic_gear_orders.csv`, `demo_agent.py`, `requirements.txt` (adds `anthropic`, `requests`). Also `git rm` the two CSVs at repo root; they're duplicates of `examples/`.

---

## Level 1 — the gate alone (no server)

The new file `examples/nordic_gear_orders.csv` is what a Danish outdoor-gear webshop's order export actually looks like: 5,454 rows, one row per **product line**, semicolon-separated, latin-1 encoded, European dates (`dd-mm-yyyy`), columns for SKU, qty, discount, channel, country, status. Planted defects: 5% guest checkouts, 25% of emails title-cased by a second CRM, 3% refunds as negative return lines 1–3 weeks later, 2% duplicate lines from a botched re-export.

```bash
python ingest.py examples/nordic_gear_orders.csv
```

What you should see: `FLAG`, `non_contractual`, 834 customers, five issues: `GUEST_CHECKOUT`, `IDENTITY_CASE`, `REFUNDS`, `DUPLICATES`, `ORDER_LINES`.

**The lesson this file taught, and why it's in the repo:** the original v0.2 gate caught four of the five defects and *missed order-line granularity* — it counted 5,070 rows as purchases when there were only ~2,940 orders. Fed to BG/NBD, that inflates every customer's frequency ~1.7× and pushes P(alive) up, silently. The fix (`ORDER_LINES` check + aggregation to order level, running *after* dedupe so duplicated lines don't get summed into order totals) is a genuine improvement that only surfaced because the test data had the shape real data has. That's the argument for level 1: the gate is only as good as the ugliest file it's seen.

Try your own file next. Any purchase-like CSV you have. When the router's classification or a flag looks wrong to you, that's the next improvement.

---

## Level 2 — the gate as a tool (local server)

Terminal 1:
```bash
uvicorn tool_server:app --port 8000
```

Terminal 2:
```bash
curl -F "file=@examples/nordic_gear_orders.csv" localhost:8000/audit | python -m json.tool
```

Or skip curl: open **http://localhost:8000/docs** in a browser. FastAPI generates an interactive page — click `POST /audit` → *Try it out* → upload a file → *Execute*. You see the request, the response, and the `agent_instruction` field. This page is also what you show on screen; it makes "the tool returns a behavioural contract" visible without explaining JSON.

What level 2 proves: the gate is callable by anything that can make an HTTP request — Copilot Studio, an MCP bridge, a LangChain tool, a Power Automate flow. It does *not* yet prove an agent will obey it.

---

## Level 3 — an agent that has to go through the gate

This is the test of the thesis. Same model, same question, same file — with and without the tool.

Requires an Anthropic API key (or adapt the script to OpenAI function calling; the loop is the same shape).

Terminal 1: server running as in level 2.

Terminal 2:
```bash
export ANTHROPIC_API_KEY=sk-ant-...

# Control: no gate offered. Watch it answer.
python demo_agent.py examples/saas_billing.csv --no-gate

# Treatment: gate offered and required. Watch it refuse.
python demo_agent.py examples/saas_billing.csv

# The interesting middle case: modelable data with caveats.
python demo_agent.py examples/nordic_gear_orders.csv
```

What to expect, and what each outcome means:

| Run | Expected behaviour | If it does something else |
|---|---|---|
| SaaS, `--no-gate` | Produces a churn number and "most valuable customers" from the preview. Confident. Wrong model family, and it can't know. | If it *refuses* without the gate, note it — models sometimes volunteer caveats. Run it 3–5 times; the point is it's inconsistent. |
| SaaS, with gate | Calls the tool, gets `REFUSE` / `contractual`, tells the user the analysis isn't legitimate and why. No numbers. | If it produces numbers anyway despite `REFUSE`: **that's a real finding** — the tool boundary alone didn't hold and the system prompt needs hardening. Record it either way. |
| Nordic gear, with gate | Calls the tool, gets `FLAG`, answers *with* the five caveats and their bias directions surfaced. | If it drops the caveats: same finding — the contract in `agent_instruction` isn't strong enough. |

The `--no-gate` vs. gated comparison is the whole argument in one screen. Run it several times; consistency is the claim, and only repetition shows it.

---

## Recording it

Keep it under 90 seconds. One terminal split in two panes, or two windows side by side. No slides.

1. **(0–10s)** Title card, one line: *"Ask an AI for churn. Does it check whether the model is valid?"*
2. **(10–35s)** `--no-gate` run on the SaaS file. Let the confident answer scroll. Freeze on the number. Caption: *"Subscription data. Non-contractual model. Nobody checked."*
3. **(35–65s)** Same command, without `--no-gate`. Show `[agent called audit_transaction_log]` → `[gate returned: REFUSE | contractual]` → the agent explaining why it won't answer. Caption: *"Same model. Same question. Now it has to go through the gate."*
4. **(65–85s)** Nordic gear run, `FLAG`. Scroll to the caveats. Caption: *"Modelable — with five named biases the agent must state."*
5. **(85–90s)** Repo URL.

Record with OBS or the OS screen recorder; increase terminal font to 18pt+ before you start; clear the scrollback between runs. Post the clip with the "validation language vs. validation behaviour" framing, not "I discovered a flaw."

If any run in step 3 or 4 misbehaves, don't cut it. Show it and say what you changed. That's a better post than a clean demo.
