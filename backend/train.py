"""
SupplierShield AI -- Reproducible Training Pipeline
=====================================================
Methodology: latent-variable synthetic data generation.
Labels are derived from a hidden true_risk_level, NOT from the observable
features directly. This prevents XGBoost from simply copying the rule engine.

All hyperparameter / policy decisions use training + validation data only.
The held-out test set is evaluated EXACTLY ONCE after all decisions are frozen.

SYNTHETIC COST MODEL DISCLAIMER
All cost figures are illustrative benchmark assumptions created solely for
this benchmark. They are not Indian SME industry data, not Razorpay data,
and not empirical fraud-loss estimates.

Run:
  cd backend
  python train.py
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
import xgboost as xgb

warnings.filterwarnings("ignore")

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

SEED = 42
N_RECORDS = 30_000
rng = np.random.default_rng(SEED)

# ---------------------------------------------------------------------------
# SYNTHETIC BENCHMARK COST MODEL ASSUMPTIONS
# IMPORTANT: illustrative only - NOT industry data.
# ---------------------------------------------------------------------------
FP_REVIEW_COST_INR = 300.0
FP_DELAY_RATE = 0.0008
FN_LOSS_RATE = 0.35
COST_MODEL_DISCLAIMER = (
    "Synthetic benchmark cost-model assumptions. "
    "These numerical values are illustrative estimates created solely for this benchmark. "
    "They are not observed Indian SME industry statistics, not Razorpay data, "
    "and not empirical measures of actual fraud losses."
)

# ---------------------------------------------------------------------------
# LATENT-VARIABLE FEATURE DISTRIBUTION PARAMETERS (frozen methodology)
# ---------------------------------------------------------------------------
PRIORS = [0.52, 0.23, 0.17, 0.08]   # safe, elevated, high, critical
LABEL_NOISE = 0.04

ADVANCE_PARAMS  = {0:(18.,20.), 1:(35.,25.), 2:(58.,22.), 3:(78.,18.)}
DEST_PROBS      = {0:0.04, 1:0.12, 2:0.32, 3:0.58}
QUOTE_PARAMS    = {0:(0.,8.),  1:(5.,14.), 2:(18.,20.),3:(32.,22.)}
MISMATCH_PROBS  = {0:0.05, 1:0.14, 2:0.35, 3:0.62}
MISSING_LAMBDAS = {0:0.3,  1:0.9,  2:2.1,  3:3.4}
AMOUNT_PARAMS   = {0:(10.5,1.2),1:(11.0,1.3),2:(11.4,1.2),3:(11.8,1.1)}
DAYS_RATES      = {0:0.05, 1:0.09, 2:0.18, 3:0.30}

CONFOUNDER_SAFE_HIGH_ADV  = 0.12
CONFOUNDER_RISKY_LOW_ADV  = 0.08
CONFOUNDER_RISKY_SUBTLE   = 0.06

FEATURE_NAMES = [
    "amount_log","advance_pct","quote_dev","dest_changed",
    "doc_mismatch","missing_count","delivery_days",
]

WEIGHT_CANDIDATES = [
    {"W_rule":0.50,"W_ml":0.40,"W_anomaly":0.10},
    {"W_rule":0.55,"W_ml":0.35,"W_anomaly":0.10},
    {"W_rule":0.45,"W_ml":0.45,"W_anomaly":0.10},
    {"W_rule":0.60,"W_ml":0.30,"W_anomaly":0.10},
]
CONTAMINATION_CANDIDATES = [0.05, 0.10, 0.15, 0.20]


# ---------------------------------------------------------------------------
# DATA GENERATION
# ---------------------------------------------------------------------------
def _gen(level: int, n: int) -> dict:
    mu,sig = ADVANCE_PARAMS[level];  adv = np.clip(rng.normal(mu,sig,n),0,100)
    dest    = rng.binomial(1,DEST_PROBS[level],n).astype(float)
    mu,sig  = QUOTE_PARAMS[level];   quote = np.clip(rng.normal(mu,sig,n),-100,1000)
    doc     = rng.binomial(1,MISMATCH_PROBS[level],n).astype(float)
    missing = np.clip(rng.poisson(MISSING_LAMBDAS[level],n),0,20).astype(float)
    mu,sig  = AMOUNT_PARAMS[level];  amount = rng.lognormal(mu,sig,n)
    days    = np.clip(rng.exponential(1./DAYS_RATES[level],n)+1.,1,3650)
    return dict(adv=adv,dest=dest,quote=quote,doc=doc,missing=missing,amount=amount,days=days)


def _apply_confounders(d: dict, level: int) -> None:
    n = len(d["adv"])
    if level == 0:
        m = rng.random(n) < CONFOUNDER_SAFE_HIGH_ADV
        d["adv"][m] = np.clip(rng.normal(72.,15.,m.sum()),60.,100.)
    elif level in (2,3):
        n_low = max(1,int(n*CONFOUNDER_RISKY_LOW_ADV))
        ix = rng.choice(n,n_low,replace=False)
        d["adv"][ix] = np.clip(rng.normal(15.,10.,n_low),0.,29.9)
        n_sub = max(1,int(n*CONFOUNDER_RISKY_SUBTLE))
        ix2 = rng.choice(n,n_sub,replace=False)
        d["adv"][ix2]     = np.clip(rng.normal(22.,12.,n_sub),0.,40.)
        d["dest"][ix2]    = 0.; d["doc"][ix2] = 0.
        d["missing"][ix2] = np.clip(rng.poisson(.3,n_sub),0,2).astype(float)
        d["quote"][ix2]   = np.clip(rng.normal(22.,8.,n_sub),10.,50.)


def generate_dataset(n: int = N_RECORDS):
    latent = rng.choice(4, size=n, p=PRIORS)
    buf = {k: np.empty(n) for k in ["adv","dest","quote","doc","missing","amount","days","level"]}
    for lv in range(4):
        mask = latent == lv; cnt = int(mask.sum())
        if cnt == 0: continue
        d = _gen(lv, cnt); _apply_confounders(d, lv)
        for k in ["adv","dest","quote","doc","missing","amount","days"]:
            buf[k][mask] = d[k]
        buf["level"][mask] = lv
    raw_y = (buf["level"] >= 2).astype(int)
    noise  = rng.random(n) < LABEL_NOISE
    y = np.where(noise, 1-raw_y, raw_y)
    X = np.column_stack([
        np.log1p(buf["amount"]), buf["adv"], buf["quote"],
        buf["dest"], buf["doc"], buf["missing"], buf["days"]
    ])
    return X, y, buf["amount"]


def generate_leakage_dataset(n: int = N_RECORDS):
    """Old rule-derived label dataset. Leakage-prone. Kept as baseline only."""
    r = np.random.default_rng(SEED)
    adv = np.clip(r.normal(30,30,n),0,100)
    dest= r.binomial(1,.15,n).astype(float)
    q   = r.normal(0,25,n)
    doc = r.binomial(1,.18,n).astype(float)
    mis = np.clip(r.poisson(1.2,n),0,20).astype(float)
    alog= r.normal(11.,1.2,n)  # fixed below
    days= np.clip(r.exponential(20,n)+1,1,3650)
    def lbl(a,d,qv,m,mi):
        s=0
        if a>=100: s+=28
        elif a>=60: s+=16
        if d: s+=22
        if abs(qv)>=30: s+=15
        if m: s+=20
        if mi>=2: s+=min(18,int(mi)*5)
        return int(s>=35)
    y = np.array([lbl(adv[i],dest[i],q[i],doc[i],mis[i]) for i in range(n)])
    alog = r.normal(11.,1.2,n)
    X = np.column_stack([alog,adv,q,dest,doc,mis,days])
    return X,y


# ---------------------------------------------------------------------------
# RULE SCORE (mirrors risk_engine.py)
# ---------------------------------------------------------------------------
def rule_score_from_row(row: np.ndarray) -> int:
    al,adv,q,dest,doc,mis,days = row
    amount = np.expm1(al)
    s=0
    if adv>=100: s+=28
    elif adv>=60: s+=16
    if dest>=.5: s+=22
    if abs(q)>=30: s+=15
    if doc>=.5: s+=20
    if mis>=2: s+=min(18,int(mis)*5)
    if amount>=500_000: s+=12
    if days<=3 and amount>=100_000: s+=8
    return min(88,s)

def batch_rule_scores(X): return np.array([rule_score_from_row(r) for r in X])


# ---------------------------------------------------------------------------
# ANOMALY SCORE TRANSFORMATION
# Normalization derived from training data percentiles only.
# t = 80th pct of raw scores; s = (95th pct - 80th pct), floor 0.01
# ---------------------------------------------------------------------------
def compute_anomaly_params(model, X_tr):
    raw = -model.score_samples(X_tr)
    t   = float(np.percentile(raw,80))
    s   = max(0.01, float(np.percentile(raw,95)) - t)
    return t, s

def anomaly_score(raw, t, s): return int(np.clip((raw-t)/s*100,0,100))


# ---------------------------------------------------------------------------
# COST HELPERS
# ---------------------------------------------------------------------------
def fp_cost(a): return FP_REVIEW_COST_INR + FP_DELAY_RATE*a
def fn_cost(a): return FN_LOSS_RATE*a

def composite(rule_s, ml_p, anom_s, w):
    return max(8, min(100, int(round(rule_s*w["W_rule"] + ml_p*100*w["W_ml"] + anom_s*w["W_anomaly"]))))

def val_cost(rule_s, ml_p, anom_s, y, amounts, thr, w):
    total = 0.
    for i in range(len(y)):
        pred = int(composite(rule_s[i],ml_p[i],anom_s[i],w) >= thr)
        if pred==1 and y[i]==0: total += fp_cost(amounts[i])
        elif pred==0 and y[i]==1: total += fn_cost(amounts[i])
    return total


# ---------------------------------------------------------------------------
# METRICS
# ---------------------------------------------------------------------------
def compute_metrics(yt, yp, yprob):
    cm = confusion_matrix(yt,yp); tn,fp,fn,tp = cm.ravel()
    return dict(
        precision=float(precision_score(yt,yp,zero_division=0)),
        recall=float(recall_score(yt,yp,zero_division=0)),
        f1=float(f1_score(yt,yp,zero_division=0)),
        roc_auc=float(roc_auc_score(yt,yprob)),
        pr_auc=float(average_precision_score(yt,yprob)),
        false_positive_rate=float(fp/(fp+tn)) if (fp+tn)>0 else 0.,
        false_negative_rate=float(fn/(fn+tp)) if (fn+tp)>0 else 0.,
        confusion_matrix=[[int(tn),int(fp)],[int(fn),int(tp)]],
    )

def biz_metrics(yt, yp, amounts, label):
    n = len(yt); cm = confusion_matrix(yt,yp); tn,fp,fn,tp = cm.ravel()
    fp_idx=np.where((yt==0)&(yp==1))[0]; fn_idx=np.where((yt==1)&(yp==0))[0]
    tp_idx=np.where((yt==1)&(yp==1))[0]; flag_idx=np.where(yp==1)[0]
    tfc=sum(fp_cost(amounts[i]) for i in fp_idx)
    tnc=sum(fn_cost(amounts[i]) for i in fn_idx)
    return dict(
        policy=label,
        fp_count=int(fp), fn_count=int(fn),
        fp_cost_inr=round(tfc,2), fn_cost_inr=round(tnc,2),
        total_expected_decision_cost_inr=round(tfc+tnc,2),
        review_rate_pct=round(len(flag_idx)/n*100,2),
        risky_exposure_correctly_flagged_inr=round(float(amounts[tp_idx].sum()),2),
        risky_exposure_missed_inr=round(float(amounts[fn_idx].sum()),2),
        legitimate_exposure_escalated_inr=round(float(amounts[fp_idx].sum()),2),
        cost_model_disclaimer=COST_MODEL_DISCLAIMER,
    )

def ece(yt, yp, n_bins=10):
    frac,mean = calibration_curve(yt,yp,n_bins=n_bins,strategy="uniform")
    step=1./n_bins; sizes=[]
    for b in range(n_bins):
        sizes.append(int(((yp>=b*step)&(yp<(b+1)*step)).sum()))
    sa=np.array(sizes[:len(frac)]); tot=sa.sum()
    return 0. if tot==0 else float(np.sum(sa/tot*np.abs(frac-mean)))


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    ts = datetime.now(timezone.utc).isoformat()
    print("="*70); print(f"SupplierShield Training Pipeline  {ts}"); print("="*70)

    # 1. Generate datasets
    print("\n[1] Generating latent-variable dataset...")
    X,y,amounts = generate_dataset(N_RECORDS)
    print(f"    pos={y.mean():.1%}  neg={(1-y).mean():.1%}")

    print("[2] Generating leakage-prone baseline dataset...")
    try:
        Xl,yl = generate_leakage_dataset(N_RECORDS)
    except Exception as e:
        print(f"    Warning: leakage dataset generation had error: {e}")
        Xl,yl = X.copy(), y.copy()  # fallback

    # 3. Splits
    print("[3] Splitting 70/15/15 stratified...")
    X_tr,X_tmp,y_tr,y_tmp,a_tr,a_tmp = train_test_split(X,y,amounts,test_size=.30,random_state=SEED,stratify=y)
    X_val,X_te,y_val,y_te,a_val,a_te = train_test_split(X_tmp,y_tmp,a_tmp,test_size=.50,random_state=SEED,stratify=y_tmp)
    print(f"    train={len(X_tr)} val={len(X_val)} test={len(X_te)}")

    # 4. Leakage baseline (val split for comparison)
    print("[4] Evaluating leakage baseline...")
    try:
        Xl_tr,Xl_te,yl_tr,yl_te = train_test_split(Xl,yl,test_size=.30,random_state=SEED,stratify=yl)
        sc_l = StandardScaler().fit(Xl_tr)
        lr_l = LogisticRegression(C=1.,max_iter=1000,random_state=SEED).fit(sc_l.transform(Xl_tr),yl_tr)
        lk_prob = lr_l.predict_proba(sc_l.transform(Xl_te))[:,1]
        lk_pred = (lk_prob>=.5).astype(int)
        lk_met  = compute_metrics(yl_te,lk_pred,lk_prob)
        leak_auc = lk_met["roc_auc"]
    except Exception as e:
        print(f"    Warning: leakage baseline error: {e}"); leak_auc=0.0; lk_met={}
    print(f"    Leakage baseline ROC-AUC: {leak_auc:.4f} (expected: inflated by leakage)")

    # 5. LogReg baseline
    print("[5] Training Logistic Regression baseline...")
    scaler = StandardScaler().fit(X_tr)
    best_lr_auc=-1.; best_lr_c=1.; best_lr=None
    for C in [.01,.1,1.,10.]:
        lr=LogisticRegression(C=C,max_iter=1000,random_state=SEED)
        lr.fit(scaler.transform(X_tr),y_tr)
        a=roc_auc_score(y_val,lr.predict_proba(scaler.transform(X_val))[:,1])
        if a>best_lr_auc: best_lr_auc=a; best_lr_c=C; best_lr=lr
    lr_vp = best_lr.predict_proba(scaler.transform(X_val))[:,1]
    lr_vm = compute_metrics(y_val,(lr_vp>=.5).astype(int),lr_vp)
    print(f"    C={best_lr_c}  Val ROC-AUC={lr_vm['roc_auc']:.4f}")
    joblib.dump(scaler, ARTIFACTS/"scaler.joblib")

    # 6. XGBoost tuning
    print("[6] Tuning XGBoost on validation...")
    spw = float((y_tr==0).sum())/float((y_tr==1).sum())
    best_xgb_auc=-1.; best_xgb_p={}; best_xgb=None
    for ne in [100,200,300]:
        for d in [3,4,5]:
            for lr_r in [.05,.1,.2]:
                m=xgb.XGBClassifier(n_estimators=ne,max_depth=d,learning_rate=lr_r,
                    scale_pos_weight=spw,eval_metric="logloss",early_stopping_rounds=20,
                    random_state=SEED,verbosity=0)
                m.fit(X_tr,y_tr,eval_set=[(X_val,y_val)],verbose=False)
                a=roc_auc_score(y_val,m.predict_proba(X_val)[:,1])
                if a>best_xgb_auc: best_xgb_auc=a; best_xgb_p=dict(n_estimators=ne,max_depth=d,learning_rate=lr_r,scale_pos_weight=spw); best_xgb=m
    xgb_vp = best_xgb.predict_proba(X_val)[:,1]
    xgb_vm = compute_metrics(y_val,(xgb_vp>=.5).astype(int),xgb_vp)
    sel_model = "XGBoost" if xgb_vm["roc_auc"]>=lr_vm["roc_auc"] else "LogisticRegression"
    print(f"    Best {best_xgb_p}  Val ROC-AUC={xgb_vm['roc_auc']:.4f}  Selected={sel_model}")
    joblib.dump(best_xgb, ARTIFACTS/"risk_model.joblib")

    # 7. IsolationForest contamination selection (validation cost, not from supervised prevalence)
    print("[7] Selecting IsolationForest contamination (independent of supervised prevalence)...")
    val_rs = batch_rule_scores(X_val)
    best_cc=float("inf"); best_c=.10; best_if=None; best_t=0.; best_s=1.
    for c in CONTAMINATION_CANDIDATES:
        ifm=IsolationForest(contamination=c,random_state=SEED,n_jobs=-1).fit(X_tr)
        t,s=compute_anomaly_params(ifm,X_tr)
        anom_v=np.array([anomaly_score(-ifm.score_samples(X_val[[i]])[0],t,s) for i in range(len(X_val))])
        cost=val_cost(val_rs,xgb_vp,anom_v,y_val,a_val,50,WEIGHT_CANDIDATES[0])
        print(f"    c={c:.2f} -> val cost INR {cost:,.0f}")
        if cost<best_cc: best_cc=cost; best_c=c; best_if=ifm; best_t=t; best_s=s
    print(f"    Selected contamination: {best_c}")
    joblib.dump(best_if, ARTIFACTS/"anomaly_model.joblib")
    anom_val=np.array([anomaly_score(-best_if.score_samples(X_val[[i]])[0],best_t,best_s) for i in range(len(X_val))])

    # 8. Weight configuration selection
    print("[8] Selecting composite score weight configuration...")
    best_w=WEIGHT_CANDIDATES[0]; best_wc=float("inf")
    for w in WEIGHT_CANDIDATES:
        cost=val_cost(val_rs,xgb_vp,anom_val,y_val,a_val,50,w)
        print(f"    W_rule={w['W_rule']} W_ml={w['W_ml']} W_anom={w['W_anomaly']} -> val cost INR {cost:,.0f}")
        if cost<best_wc: best_wc=cost; best_w=w
    print(f"    Selected: {best_w}")

    # 9. Threshold selection
    print("[9] Selecting classification threshold...")
    val_comp=np.array([composite(val_rs[i],xgb_vp[i],anom_val[i],best_w) for i in range(len(y_val))])
    best_thr=50; best_tc=float("inf")
    for thr in range(25,75,5):
        yp=(val_comp>=thr).astype(int)
        c=sum(fp_cost(a_val[i]) if yp[i]==1 and y_val[i]==0 else fn_cost(a_val[i]) if yp[i]==0 and y_val[i]==1 else 0. for i in range(len(y_val)))
        print(f"    thr={thr} -> val cost INR {c:,.0f}")
        if c<best_tc: best_tc=c; best_thr=thr
    print(f"    Selected threshold: {best_thr}")

    # 10. Optional calibration (properly separated: 60% cal, 40% cal-eval - no held-out data)
    print("[10] Optional calibration check (validation subsets only)...")
    sp=int(len(X_val)*.60)
    y_cal,y_ce = y_val[:sp],y_val[sp:]
    p_cal,p_ce = xgb_vp[:sp],xgb_vp[sp:]
    ece_bef = ece(y_ce,p_ce)
    iso=IsotonicRegression(out_of_bounds="clip").fit(p_cal,y_cal)
    p_ce_cal=iso.predict(p_ce)
    ece_aft=ece(y_ce,p_ce_cal)
    cal_imp=ece_bef-ece_aft; use_cal=(cal_imp>.02)
    print(f"    ECE before: {ece_bef:.4f}  after: {ece_aft:.4f}  improvement: {cal_imp:.4f}")
    print(f"    Calibration applied: {'Yes' if use_cal else 'No'}")
    if use_cal: joblib.dump(iso, ARTIFACTS/"calibrator.joblib")
    elif (ARTIFACTS/"calibrator.joblib").exists(): (ARTIFACTS/"calibrator.joblib").unlink()

    # 11. Save train_config.json (freeze all decisions)
    cfg = dict(
        dataset=dict(version="supplier-risk-dataset-v2-latent-variable",n_records=N_RECORDS,seed=SEED,
            methodology="latent-variable",class_priors=dict(safe=.52,elevated=.23,high=.17,critical=.08),
            label_noise_rate=LABEL_NOISE,
            confounder_rates=dict(safe_high_advance=CONFOUNDER_SAFE_HIGH_ADV,risky_low_advance=CONFOUNDER_RISKY_LOW_ADV,risky_subtle=CONFOUNDER_RISKY_SUBTLE)),
        split=dict(method="stratified 70/15/15",seed=SEED,train=len(X_tr),validation=len(X_val),test=len(X_te),
            train_pos_rate=float(y_tr.mean()),val_pos_rate=float(y_val.mean()),test_pos_rate=float(y_te.mean())),
        logistic_regression_baseline=dict(best_C=best_lr_c,val_roc_auc=lr_vm["roc_auc"]),
        xgboost=dict(selected_params=best_xgb_p,val_roc_auc=xgb_vm["roc_auc"]),
        model_selection=dict(selected=sel_model,objective="validation ROC-AUC"),
        isolation_forest=dict(contamination=best_c,candidates=CONTAMINATION_CANDIDATES,
            selection_objective="validation expected decision cost",
            normalization_method="percentile-based from training data (80th and 95th pct of raw scores)",
            t_param=best_t,s_param=best_s,
            note="contamination is an independent unsupervised hyperparameter, NOT derived from supervised positive-class prevalence"),
        composite_score=dict(
            formula=f"max(8,min(100,round(rule*{best_w['W_rule']}+ml_prob*100*{best_w['W_ml']}+anomaly*{best_w['W_anomaly']})))",
            W_rule=best_w["W_rule"],W_ml=best_w["W_ml"],W_anomaly=best_w["W_anomaly"],
            weight_candidates=WEIGHT_CANDIDATES,selection_objective="minimum validation expected decision cost",
            shap_score_bonus="REMOVED - SHAP is explanation-only, not used in scoring"),
        threshold=dict(composite_score_threshold=best_thr,selection_objective="minimum validation expected decision cost",candidates=list(range(25,75,5))),
        calibration=dict(status="applied" if use_cal else "not_applied",
            method="isotonic regression on 60% of validation; evaluated on remaining 40%",
            ece_before=ece_bef,ece_after=float(ece_aft) if use_cal else None,
            improvement=float(cal_imp),threshold=0.02,
            note="held-out test set NOT used for calibration selection"),
        cost_model=dict(disclaimer=COST_MODEL_DISCLAIMER,fp_review_cost_inr=FP_REVIEW_COST_INR,
            fp_delay_rate=FP_DELAY_RATE,fn_loss_rate=FN_LOSS_RATE,
            fp_formula="300+0.0008*amount",fn_formula="0.35*amount"),
        feature_names=FEATURE_NAMES,
        trained_at=datetime.now(timezone.utc).isoformat(),
    )
    with open(ARTIFACTS/"train_config.json","w") as f: json.dump(cfg,f,indent=2)
    print("    train_config.json saved.")

    # -----------------------------------------------------------------------
    # HELD-OUT EVALUATION -- runs ONCE, all decisions frozen above
    # -----------------------------------------------------------------------
    print("\n"+"="*70)
    print("FINAL HELD-OUT EVALUATION (single run, all decisions frozen)")
    print("="*70)
    te_xgb_p = best_xgb.predict_proba(X_te)[:,1]
    te_xgb_cost = iso.predict(te_xgb_p) if use_cal else te_xgb_p
    te_rs = batch_rule_scores(X_te)
    te_anom = np.array([anomaly_score(-best_if.score_samples(X_te[[i]])[0],best_t,best_s) for i in range(len(X_te))])
    te_comp = np.array([composite(te_rs[i],te_xgb_cost[i],te_anom[i],best_w) for i in range(len(y_te))])
    te_pred = (te_comp>=best_thr).astype(int)

    fin = compute_metrics(y_te,te_pred,te_xgb_p)
    ss_biz = biz_metrics(y_te,te_pred,a_te,"SupplierShield")
    pa_biz = biz_metrics(y_te,np.zeros_like(y_te),a_te,"Pass All (Baseline A)")
    fa_biz = biz_metrics(y_te,np.ones_like(y_te),a_te,"Flag All (Baseline B)")
    ss_biz["net_cost_vs_pass_all_inr"]=round(pa_biz["total_expected_decision_cost_inr"]-ss_biz["total_expected_decision_cost_inr"],2)
    ss_biz["net_cost_vs_flag_all_inr"]=round(fa_biz["total_expected_decision_cost_inr"]-ss_biz["total_expected_decision_cost_inr"],2)

    for k,v in fin.items():
        if k!="confusion_matrix": print(f"  {k}: {v:.4f}")
    print(f"  confusion_matrix: {fin['confusion_matrix']}")
    print(f"\n  SupplierShield cost:  INR {ss_biz['total_expected_decision_cost_inr']:,.0f}")
    print(f"  Pass All cost:        INR {pa_biz['total_expected_decision_cost_inr']:,.0f}")
    print(f"  Flag All cost:        INR {fa_biz['total_expected_decision_cost_inr']:,.0f}")
    print(f"  Net saved vs Pass All: INR {ss_biz['net_cost_vs_pass_all_inr']:,.0f}")

    mm = dict(
        dataset_version="supplier-risk-dataset-v2-latent-variable",
        model_version="supplier-risk-v2",
        methodology="Latent-variable synthetic benchmark. Labels from hidden risk states, not directly from observable features. NOT real-world fraud performance.",
        features=FEATURE_NAMES,
        split=dict(total=N_RECORDS,train=len(X_tr),validation=len(X_val),test=len(X_te),method="stratified 70/15/15",seed=SEED),
        model_selection=dict(logistic_regression_val_roc_auc=lr_vm["roc_auc"],xgboost_val_roc_auc=xgb_vm["roc_auc"],selected=sel_model),
        composite_score_formula=dict(W_rule=best_w["W_rule"],W_ml=best_w["W_ml"],W_anomaly=best_w["W_anomaly"],threshold=best_thr,shap_score_bonus="removed"),
        isolation_forest=dict(contamination=best_c,t_param=best_t,s_param=best_s),
        calibration=dict(status="applied" if use_cal else "not_applied",ece_before=ece_bef,ece_after=float(ece_aft) if use_cal else None),
        metrics=fin,
        business_metrics=dict(
            cost_model_disclaimer=COST_MODEL_DISCLAIMER,
            suppliershield=ss_biz,
            baseline_pass_all=pa_biz,
            baseline_flag_all=fa_biz,
        ),
        leakage_baseline_reference=dict(description="Old rule-derived label methodology (v1)",roc_auc=leak_auc,note="Metrics inflated by label leakage"),
        limitation="Synthetic benchmark. Costs are synthetic assumptions, not industry data. Real-world performance unknown.",
        evaluated_at=datetime.now(timezone.utc).isoformat(),
    )
    with open(ARTIFACTS/"model_metrics.json","w") as f: json.dump(mm,f,indent=2)
    print("\nArtifacts saved. Training complete.")


if __name__=="__main__":
    main()
