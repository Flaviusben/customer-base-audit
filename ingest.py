"""
Customer-Base Audit — v0.2 Ingestion Layer
==========================================
Raw CSV -> validated transaction log + data-quality report + business-structure
auto-detection (contractual vs non-contractual), with HARD-REFUSE gates.

Design: every downstream model (BG/NBD, Gamma-Gamma, sBG, ...) is only valid
for certain data structures. This layer decides what the data CAN support
before any model is fit. Output verdicts:
  PASS  -> safe to model
  FLAG  -> model, but carry caveat into the brief
  REFUSE-> do not model; explain why
"""
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
import re, sys, json

# ---------------------------------------------------------------- schema map
CANDIDATES = {
    "customer_id": ["customer_id","cust_id","customerid","customer","user_id","userid","id","cust","client_id","account_id","email"],
    "date":        ["date","order_date","transaction_date","invoice_date","datetime","timestamp","purchase_date","created_at"],
    "amount":      ["amount","revenue","sales","total","value","price","spend","order_value","gross","net_amount"],
    "quantity":    ["quantity","qty","units","items"],
    "order_id":    ["order_id","invoice","invoice_no","transaction_id","orderid","receipt"],
}

def map_columns(df: pd.DataFrame) -> dict:
    """Fuzzy-map raw headers to canonical roles. Returns {role: column}."""
    norm = {re.sub(r"[^a-z0-9]","",c.lower()): c for c in df.columns}
    out = {}
    for role, names in CANDIDATES.items():
        for n in names:
            key = re.sub(r"[^a-z0-9]","",n)
            if key in norm:
                out[role] = norm[key]; break
        if role not in out:  # substring fallback: 'customeremail' ~ 'email'
            for n in names:
                key = re.sub(r"[^a-z0-9]","",n)
                hit = [orig for k,orig in norm.items() if key in k and orig not in out.values()]
                if hit: out[role] = hit[0]; break
    # fallback: infer date column by dtype/parseability
    if "date" not in out:
        for c in df.columns:
            try:
                parsed = pd.to_datetime(df[c].dropna().head(50), errors="coerce", format="mixed")
                if parsed.notna().mean() > 0.9: out["date"] = c; break
            except Exception: pass
    # fallback: amount = most plausible numeric column (positive, continuous)
    if "amount" not in out:
        best, score = None, 0
        for c in df.select_dtypes("number").columns:
            s = df[c].dropna()
            if len(s) == 0 or c == out.get("customer_id"): continue
            sc = (s > 0).mean() * min(s.nunique()/len(s), 1.0)
            if sc > score: best, score = c, sc
        if best: out["amount"] = best
    return out

# ---------------------------------------------------------------- diagnostics
@dataclass
class Issue:
    severity: str   # INFO | FLAG | REFUSE
    code: str
    detail: str

@dataclass
class AuditReport:
    issues: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    structure: dict = field(default_factory=dict)
    def add(self, sev, code, detail): self.issues.append(Issue(sev, code, detail))
    @property
    def verdict(self):
        sevs = [i.severity for i in self.issues]
        return "REFUSE" if "REFUSE" in sevs else ("FLAG" if "FLAG" in sevs else "PASS")
    def to_json(self):
        return json.dumps({"verdict": self.verdict,
                           "structure": self.structure, "stats": self.stats,
                           "issues": [i.__dict__ for i in self.issues]}, indent=2, default=str)

def diagnose(df: pd.DataFrame, cols: dict, rep: AuditReport) -> pd.DataFrame:
    n0 = len(df)
    rep.stats["rows_raw"] = n0

    # --- required fields
    if "customer_id" not in cols:
        rep.add("REFUSE","NO_CUSTOMER_ID","No customer identifier found. CLV models require longitudinal identity. Possible fixes: join order header, hash email.")
        return df
    if "date" not in cols:
        rep.add("REFUSE","NO_DATE","No parseable date column. Timing models (BG/NBD) impossible.")
        return df

    df = df.rename(columns={v:k for k,v in cols.items()})
    df["date"] = pd.to_datetime(df["date"], errors="coerce", format="mixed")

    # --- nulls / parse failures
    bad_date = df["date"].isna().mean()
    if bad_date > 0.05: rep.add("FLAG","DATE_PARSE", f"{bad_date:.1%} of dates unparseable; rows dropped.")
    bad_id = df["customer_id"].isna().mean()
    if bad_id > 0:
        rep.add("FLAG" if bad_id < 0.10 else "REFUSE","GUEST_CHECKOUT",
                f"{bad_id:.1%} rows lack customer_id (guest checkout?). CLV on remaining rows only -> base undercounted, per-customer value inflated.")
    df = df.dropna(subset=["customer_id","date"])

    # --- identity-quality heuristics (the trap from message one)
    ids = df["customer_id"].astype(str)
    if ids.str.contains("@").mean() > 0.5:
        casefold_dupes = ids.str.lower().nunique() < ids.nunique()
        if casefold_dupes:
            rep.add("FLAG","IDENTITY_CASE","Email IDs differ only by case -> same customer split into multiple IDs. Normalizing to lowercase.")
            df["customer_id"] = ids.str.lower()

    # --- amounts: refunds, zeros, duplicates
    if "amount" in df.columns:
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
        neg = (df["amount"] < 0).mean()
        if neg > 0:
            rep.add("FLAG","REFUNDS", f"{neg:.1%} negative-amount rows (refunds/credits). Netting refunds into same-day orders; unmatched refunds excluded from spend model but kept for revenue truth.")
        zero = (df["amount"] == 0).mean()
        if zero > 0.02: rep.add("FLAG","ZERO_VALUE", f"{zero:.1%} zero-value rows (samples/replacements?). Excluded from Gamma-Gamma.")
    dupe_key = [c for c in ["customer_id","date","amount","order_id"] if c in df.columns]
    dup = df.duplicated(dupe_key).mean()
    if dup > 0.005:
        rep.add("FLAG","DUPLICATES", f"{dup:.1%} exact duplicate rows -> frequency inflated, P(alive) biased up. Deduplicating.")
        df = df.drop_duplicates(dupe_key)

    # --- observation window
    span_days = (df["date"].max() - df["date"].min()).days
    rep.stats.update(rows_clean=len(df), customers=df["customer_id"].nunique(),
                     start=str(df["date"].min().date()), end=str(df["date"].max().date()),
                     span_days=span_days)
    if span_days < 270:
        rep.add("REFUSE","SHORT_WINDOW", f"Only {span_days} days observed. BTYD needs ~9-12+ months to separate dead from dormant; holdout split impossible.")
    elif span_days < 540:
        rep.add("FLAG","SHORT_WINDOW", f"{span_days} days: modelable but no seasonal cycle for validation.")
    return df

# -------------------------------------------- contractual auto-detection
def detect_structure(df: pd.DataFrame, rep: AuditReport):
    """Contractual (subscription) vs non-contractual decides the ENTIRE model
    family: sBG/survival vs BG/NBD. Wrong choice = confidently wrong CLV.
    Signals: inter-purchase-time regularity, amount stickiness, calendar alignment."""
    g = df.sort_values("date").groupby("customer_id")["date"]
    ipt = g.diff().dt.days.dropna()
    ipt = ipt[ipt > 0]
    repeaters = (df.groupby("customer_id").size() >= 3).mean()
    s = {}
    if len(ipt) < 50:
        rep.add("FLAG","STRUCTURE_UNKNOWN","Too few repeat transactions to classify business structure. Defaulting to non-contractual; verify manually.")
        rep.structure.update(classification="unknown", repeat_buyer_share=round(repeaters,3))
        return

    # 1) IPT regularity: per-customer CV of inter-purchase times (subs ~ 0)
    cv = (df.sort_values("date").groupby("customer_id")["date"]
            .agg(lambda x: x.diff().dt.days.std()/x.diff().dt.days.mean()
                 if len(x) >= 4 and x.diff().dt.days.mean() else np.nan).dropna())
    s["median_ipt_cv"] = round(float(cv.median()), 3) if len(cv) else None

    # 2) Periodicity: share of IPTs within ±3 days of 7/14/30/365
    anchors = np.array([7,14,30,31,365])
    near = np.abs(ipt.values[:,None] - anchors[None,:]).min(axis=1) <= 3
    s["periodic_ipt_share"] = round(float(near.mean()), 3)

    # 3) Amount stickiness: same customer pays same amount repeatedly
    if "amount" in df.columns:
        sticky = (df.groupby("customer_id")["amount"]
                    .agg(lambda x: x.value_counts(normalize=True).iloc[0] if len(x)>=3 else np.nan).dropna())
        s["median_amount_stickiness"] = round(float(sticky.median()),3) if len(sticky) else None

    score = sum([
        (s.get("median_ipt_cv") is not None and s["median_ipt_cv"] < 0.25),
        s["periodic_ipt_share"] > 0.5,
        (s.get("median_amount_stickiness") or 0) > 0.8,
    ])
    cls = "contractual" if score >= 2 else ("hybrid" if score == 1 else "non_contractual")
    s.update(classification=cls, repeat_buyer_share=round(float(repeaters),3), signals_fired=score)
    rep.structure.update(s)

    if cls == "contractual":
        rep.add("REFUSE","WRONG_MODEL_FAMILY",
                "Data looks CONTRACTUAL (regular billing cadence, sticky amounts). BG/NBD assumes unobserved churn -> would misestimate P(alive). Route to sBG/survival module instead (v0.3).")
    elif cls == "hybrid":
        rep.add("FLAG","HYBRID_STRUCTURE","Mixed signals (e.g. subscriptions + one-off sales). Consider splitting the base before modeling.")

# ---------------------------------------------------------------- entrypoint
def ingest(path: str) -> tuple[pd.DataFrame, AuditReport]:
    rep = AuditReport()
    # delimiter sniffing + encoding fallback
    for enc in ("utf-8","latin-1"):
        try:
            df = pd.read_csv(path, sep=None, engine="python", encoding=enc); break
        except UnicodeDecodeError: continue
    cols = map_columns(df)
    rep.stats["column_mapping"] = cols
    if not cols: rep.add("REFUSE","UNMAPPABLE","Could not identify any required columns.")
    df = diagnose(df, cols, rep)
    if rep.verdict != "REFUSE":
        detect_structure(df, rep)
    return df, rep

if __name__ == "__main__":
    df, rep = ingest(sys.argv[1])
    print(rep.to_json())
