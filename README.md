# Customer-Base Audit Engine

**CLV analytics with a statistical conscience: a pipeline that knows when its own models are lying.**

---

## The problem (why you should pay attention)

Every AI analytics tool on the market today — text-to-SQL copilots, "ask your data" chatbots, auto-dashboard generators — will happily answer *"What's our churn? What are our customers worth?"* with a confident number.

None of them check whether the number is statistically legitimate.

An LLM will fit BG/NBD (a model for businesses where churn is *unobserved*) to subscription billing data where churn is *directly observed* — and report plausible-looking, wrong customer lifetime values. It will compute CLV on a transaction log where the same customer appears under three email spellings, where guest checkouts hide 15% of orders, where refunds inflate frequency. The output looks like analysis. It's noise with a confidence interval.

This is not a hypothetical. Running this engine on **CDNOW** — the canonical academic benchmark dataset used in every CLV course — it flagged a violation of the Gamma-Gamma independence assumption (frequency–spend correlation, Spearman +0.21) that biases the standard textbook pipeline. The dataset everyone learns on fails the assumptions everyone skips.

**The thesis: as analysis gets automated, the scarce layer is not running models — it's validating them. This repo encodes that validation as code.**

## What it does

Raw transaction CSV in → audited, decision-ready output out, through a **methodology gate** with three verdicts:

| Verdict | Meaning |
|---|---|
| `PASS` | Data supports the model family. Proceed. |
| `FLAG` | Modelable, but with named biases carried into the final brief (e.g. "guest checkouts → per-customer value inflated") |
| `REFUSE` | The analysis would be statistically illegitimate. The engine explains why and what to fix — instead of producing a wrong number |

### Pipeline stages

1. **Schema inference** — fuzzy-maps arbitrary column headers (`Customer Email`, `Total (DKK)`, `invoice_date`...) to canonical roles; sniffs delimiters and encodings.
2. **Data-quality diagnostics** — the failure modes that silently corrupt CLV in practice:
   - identity fragmentation (case-split emails, guest checkout share)
   - refunds and zero-value rows
   - duplicate transactions (→ inflated frequency, biased P(alive))
   - observation window too short to separate dead customers from dormant ones
3. **Business-structure auto-detection** — classifies the log as **contractual / non-contractual / hybrid** using inter-purchase-time regularity, calendar periodicity, and amount stickiness. This single classification decides the entire valid model family (sBG/survival vs. BG/NBD + Gamma-Gamma). Getting it wrong is the most expensive silent error in CLV work.
4. **Modeling with assumption checks** *(v0.1)* — BG/NBD + Gamma-Gamma with explicit tests of the assumptions practitioners routinely skip (frequency–spend independence), bias direction stated when violated.
5. **Executive brief** *(v0.1)* — CLV distribution, revenue concentration (Stobachoff), P(alive) segment matrix, and every caveat the gate raised — in the 3-page format a CFO acts on, not a notebook.

### Demonstrated on adversarial synthetic data

A deliberately messy DTC log (guest checkouts, mixed-case emails, refunds, injected duplicates) → `FLAG` with all four issues caught and corrected. A synthetic SaaS billing log → correctly classified `contractual`, **hard-refused** for BG/NBD with routing advice. The gate works.

## How this differs from existing solutions

| | Text-to-SQL / AI copilots | CLV libraries (`lifetimes`, `pymc-marketing`) | CDP / analytics suites | **This engine** |
|---|---|---|---|---|
| Answers ad-hoc questions | ✅ | ❌ | partial | via agent layer (v0.3) |
| Fits CLV models | ❌ | ✅ | black-box | ✅ |
| Checks if the model is *valid for this data* | ❌ | ❌ (assumes you know) | ❌ | ✅ **core feature** |
| Refuses illegitimate analysis | ❌ | ❌ | ❌ | ✅ |
| Explains bias direction when assumptions break | ❌ | ❌ | ❌ | ✅ |

The libraries assume a trained statistician is driving. The copilots assume no statistician is needed. Both assumptions fail in the mid-market. This sits in the gap: **judgment-as-code.**

## Where AI agents fit (v0.3 architecture)

The engine is built to be the *validation layer underneath* agentic analytics, not another chatbot on top:

```
User: "Which high-value customers are we about to lose?"
        │
        ▼
  AI agent (Copilot Studio / Claude / MCP client)
        │  calls tool: customer_base_audit(source)
        ▼
  ┌─ Methodology gate ──────────────────────────┐
  │ ingest → diagnose → detect structure        │
  │   REFUSE → agent must tell the user why,    │
  │            cannot fabricate an answer       │
  │   PASS/FLAG → valid model family selected   │
  └─────────────────┬───────────────────────────┘
                    ▼
        scored customers + caveats → agent → decision brief
```

Implementation path: wrap `ingest.py` + the modeling core as an **MCP server** (or Copilot Studio custom action against Dynamics 365 / Business Central data). The agent gets the conversational plumbing; this repo supplies the statistical conscience it structurally lacks. The key design rule: **the agent cannot route around the gate.** A `REFUSE` propagates to the user as "here's why this can't be answered from this data, and what to fix" — which is more valuable than a wrong number.

## Who benefits

- **Mid-market DTC / e-commerce / subscription businesses** (the segment with real transaction data but no in-house statistician): defensible CLV, churn risk, and revenue-concentration answers from the data they already have.
- **BI & analytics consultancies / Microsoft partner ecosystem**: a differentiated layer to ship inside Copilot Studio engagements — every competitor demos text-to-SQL; almost no one demos analysis that validates itself.
- **M&A / diligence teams evaluating SMB acquisitions**: customer-base quality (concentration, retention economics, P(alive)-weighted revenue durability) from a raw transaction export, with explicit statements of what the data can and cannot support — exactly the epistemic honesty diligence requires.
- **Membership organizations & associations**: structurally subscription businesses; the contractual routing (survival/sBG module, v0.3 roadmap) targets them directly.

## Roadmap

- **v0.1** ✅ BG/NBD + Gamma-Gamma engine with assumption checks, executive brief (CDNOW)
- **v0.2** ✅ raw-CSV ingestion, data-quality diagnostics, contractual auto-detection, REFUSE path
- **v0.3** ⬜ contractual module (sBG / survival), calibration–holdout validation, MCP server wrapper
- **v0.4** ⬜ identity resolution beyond casefolding; hybrid-base splitting

## Honest limitations

Synthetic and benchmark validation only so far — the gate has not yet changed a decision on a live commercial dataset; that is the next milestone. Structure detection is heuristic (three signals, majority vote), tuned for recall on contractual misclassification because that error is the expensive one. This is a working demonstration of a failure mode in AI analytics, with receipts — not a product.

## Quick start

```bash
python ingest.py your_transactions.csv   # → JSON audit report with verdict
```

License: MIT.
