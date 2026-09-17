# Customer-Base Audit Engine

**A methodology gate for customer analytics: it checks whether a CLV model is valid for your data before it lets anyone compute one.**

Independent project, built from customer-analytics coursework and AI-engineering practice. Not affiliated with any employer or vendor.

---

## The problem

Ask any AI analytics assistant "what are our customers worth?" and hand it a transaction export. You'll get a confident number. What you won't get is a check on whether the model it ran was legitimate for that data.

A language model doesn't *forget* to validate — it has no mechanism that makes validation happen. It pattern-matches "CLV question + transaction data" to the most common pipeline in its training distribution (BG/NBD + Gamma-Gamma) and executes it fluently. Its confidence reflects how typical the answer sounds, not whether the statistics hold. So it will:

- fit a non-contractual model (churn *unobserved*) to subscription billing data (churn *observed*), and report wrong lifetime values;
- score a customer base where one person appears under three email spellings, guest checkouts hide a share of orders, and refunds inflate purchase frequency.

Prompting an assistant to "always check assumptions" gets you validation *language* some of the time. It doesn't get you validation *behaviour* every time. The only way to make a check happen deterministically is to put it in code, on the path the agent must take.

**That's what this repo is: an output guardrail and router for customer analytics, expressed as code an agent has to pass through.**

## What it does

Raw transaction CSV in → verdict and audit report out.

| Verdict | Policy |
|---|---|
| `PASS` | Data supports the detected model family. Proceed. |
| `FLAG` | Modelable, but each named bias — and its direction — must be carried into whatever the agent tells the user. |
| `REFUSE` | The analysis would be statistically illegitimate. The engine explains why and what to fix. No numbers are produced. |

Every failure mode has a defined policy, not just a detection. That distinction is the difference between a guardrail and a log line.

### Pipeline

1. **Schema inference** — fuzzy-maps arbitrary headers (`Customer Email`, `Total (DKK)`, `invoice_date`) to canonical roles; sniffs delimiter and encoding.
2. **Data-quality diagnostics** — each defect is reported with the *direction* it biases the result, because a caveat without a direction isn't actionable:

   | Defect | Effect on CLV |
   |---|---|
   | Case-split identities | one customer becomes several → value per customer understated |
   | Guest checkout (missing IDs) | base undercounted → value per customer inflated |
   | Refunds counted as purchases | frequency inflated |
   | Duplicate rows | frequency inflated → P(alive) biased upward |
   | Observation window < ~9 months | dead vs. dormant customers indistinguishable → `REFUSE` |

3. **Business-structure router** — classifies the log as **contractual / non-contractual / hybrid** from inter-purchase-time regularity, calendar periodicity, and amount stickiness. This one classification selects the entire valid model family (survival / sBG vs. BG/NBD + Gamma-Gamma). It runs before any model is fit, so the expensive and wrong step never happens. Contractual → `REFUSE` for BG/NBD, with routing advice.
4. **Modeling with assumption checks** (`customer_base_audit.py`) — BG/NBD + Gamma-Gamma with explicit tests of the assumptions practitioners routinely skip, bias direction stated when they fail.
5. **Executive brief** — CLV distribution, revenue concentration, P(alive) segment matrix, and every caveat the gate raised, in a format a decision-maker acts on rather than a notebook.
6. **Agent tool server** (`tool_server.py`) — the gate as an HTTP tool. The response carries an `agent_instruction` field: an explicit behavioural contract per verdict (on `REFUSE`: *do not produce churn or CLV figures; producing numbers anyway would be fabrication*). The agent gets the conversational layer; the tool supplies the guarantee.

## Worked example: the benchmark everyone learns on

CDNOW is the standard public dataset in nearly every CLV curriculum. The Gamma-Gamma spend model assumes purchase frequency and spend-per-order are independent — an assumption its authors documented and most deployment pipelines never test. This engine tests it:

- **Finding:** frequency and spend-per-order are positively dependent (Spearman ρ ≈ +0.21). Modest, but real.
- **Direction:** frequent buyers spend somewhat more per order than the model assumes, so it pulls their expected spend toward the population mean and **undervalues the heaviest buyers**.
- **Consequence:** when the engine reports ~71% of future value in the top 20% of customers, it also reports that this is a **floor** — true concentration is likely higher.

Nothing here is a new discovery about Gamma-Gamma. The point is that the check ran automatically, on data where a standard pipeline would have said nothing.

## Where it sits in an agent architecture

```
User: "Which high-value customers are we about to lose?"
        │
        ▼
  AI agent (any tool-calling framework / MCP client)
        │  calls read-only tool: audit(transactions)
        ▼
  ┌─ Methodology gate ─────────────────────────────────┐
  │ schema → diagnostics → structure router             │
  │   REFUSE → agent relays reason + remediation        │
  │   FLAG   → agent must surface each bias + direction │
  │   PASS   → valid model family selected              │
  └─────────────────────┬──────────────────────────────┘
                        ▼
          scored customers + caveats → decision brief
```

Design choices, and why:

- **Guardrail before the model, not after.** Agent error compounds multiplicatively across steps; a feasibility check at step one is worth more than a quality check at step ten.
- **Policy per failure mode.** `REFUSE`, `FLAG`, and `PASS` each dictate what the agent does next. "The analysis failed" is not an instruction.
- **Router as a small deterministic classifier**, not a model call. Cheap, inspectable, and it rejects out-of-scope data before anything expensive runs.
- **Read-only tool.** The audit never writes to a system of record, so it can be wired into an agent at the lowest trust tier.
- **The agent cannot route around the gate.** There is no endpoint that returns CLV without a verdict attached.

## Evaluation

What a guardrail is worth depends on two numbers this repo does not yet have, stated here so nobody has to guess:

1. **Router accuracy** — precision and recall of contractual/non-contractual classification. Target: no contractual dataset passes as non-contractual (that misclassification is the expensive one; the detector is tuned for recall on it at the cost of some false `REFUSE`s).
2. **Decision impact** — on real commercial data, how often does a `FLAG` or `REFUSE` change the conclusion a naive pipeline would have reached? If the answer is "rarely," this is hygiene, not judgment. That test is the next milestone.

Current evidence is a smoke test, not an evaluation: two adversarial synthetic logs in `examples/` — a messy DTC export (guest checkouts, mixed-case emails, refunds, injected duplicates → `FLAG`, all four defects caught) and a SaaS billing log (→ `contractual`, `REFUSE`). Correct on both; two data points.

## How this differs from what exists

| | AI copilots / text-to-SQL | CLV libraries (`lifetimes`, `pymc-marketing`) | This engine |
|---|---|---|---|
| Answers ad-hoc questions | ✅ | ❌ | via the agent it serves |
| Fits CLV models | ❌ | ✅ | ✅ |
| Checks model validity *for this data* | ❌ | ❌ (assumes you know) | ✅ core |
| Refuses illegitimate analysis | ❌ | ❌ | ✅ |
| States bias direction on violation | ❌ | ❌ | ✅ |

The libraries assume a statistician is driving. The copilots assume none is needed. This is for the space between.

## Who this is for

- **Mid-market e-commerce, DTC, and subscription businesses** with real transaction history and no in-house statistician.
- **Analytics and AI consultancies** shipping agentic analytics who need a validation layer their competitors' text-to-SQL demos lack.
- **Diligence teams** assessing an SMB's customer base from a raw export, who need explicit statements of what the data can and cannot support.
- **Membership organisations** — structurally contractual; the survival/sBG route targets them.

## Roadmap

- **v0.1** ✅ BG/NBD + Gamma-Gamma with assumption checks; executive brief (CDNOW)
- **v0.2** ✅ raw-CSV ingestion, data-quality diagnostics, structure router, `REFUSE` path
- **v0.3** ✅ HTTP tool server with per-verdict agent contract
- **v0.4** ⬜ contractual module (sBG / survival); calibration–holdout validation; router evaluation set
- **v0.5** ⬜ identity resolution beyond casefolding; hybrid-base splitting; first live-data decision-impact test

## Limitations

- Validated on benchmark and synthetic data only. No live commercial dataset yet.
- Structure detection is a three-signal heuristic with majority vote, not a learned classifier.
- The Gamma-Gamma dependence on CDNOW is modest; it is a demonstration of the check, not a claim that the textbook pipeline is unusable.
- The modeling core uses `lifetimes`, which is no longer actively maintained; migration to `pymc-marketing` is planned.
- This is a working demonstration of a failure mode in AI analytics, with receipts. It is not a product.

## Quick start

```bash
pip install -r requirements.txt
python ingest.py examples/saas_billing.csv        # → JSON audit report, verdict REFUSE
python customer_base_audit.py                     # → CDNOW run with assumption checks + brief
uvicorn tool_server:app --port 8000               # → agent tool; POST a CSV to /audit
```

MIT License.
