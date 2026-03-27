#!/usr/bin/env python3
"""
YRFI/NRFI XGBoost Model Training Pipeline
==========================================
- Fetches data from Supabase mlb_model_features
- Temporal split: 2023-2024 train, 2025 test
- Optuna hyperparameter tuning with 5-fold CV
- Full evaluation suite with SHAP, calibration, confidence tiers
- Hybrid comparison with rule-based model
- Saves all artifacts to models/ directory

Usage:
    python3 train_model.py [--retrain]  # --retrain uses all data (no holdout)
"""

import os
import sys
import json
import argparse
import warnings
from datetime import datetime

import httpx
import numpy as np
import pandas as pd
import joblib
import xgboost as xgb
import optuna
import shap
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, log_loss, confusion_matrix, classification_report,
)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns

warnings.filterwarnings("ignore", category=FutureWarning)
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ── Config ────────────────────────────────────────────────────────────────────
SUPABASE_URL = "https://kakjbyoxqjvwnsdbqcnb.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imtha2pieW94cWp2d25zZGJxY25iIiwi"
    "cm9sZSI6ImFub24iLCJpYXQiOjE3Njk0NzQxMjgsImV4cCI6MjA4NTA1MDEyOH0."
    "6kkaabg_8D2qKcIsuEUVuZWja3LIdx8-a2wwoTmu30k"
)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(SCRIPT_DIR, "..", "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Feature column mapping: friendly_name -> actual column in mlb_model_features
FEATURE_MAP = {
    "combined_scoreless_pct": "combined_scoreless_pct",
    "combined_fi_era": "combined_fi_era",
    "home_p_era_delta": "home_p_fi_era_delta",
    "away_p_era_delta": "away_p_fi_era_delta",
    "home_p_scoreless_pct": "home_p_fi_scoreless_pct",
    "away_p_scoreless_pct": "away_p_fi_scoreless_pct",
    "home_p_k9": "home_p_k9",
    "away_p_k9": "away_p_k9",
    "home_p_bb9": "home_p_bb9",
    "away_p_bb9": "away_p_bb9",
    "home_p_fi_era": "home_p_fi_era",
    "away_p_fi_era": "away_p_fi_era",
    "home_team_yrfi_pct": "home_team_yrfi_pct_home",
    "away_team_yrfi_pct": "away_team_yrfi_pct_away",
    "park_yrfi_pct": "park_yrfi_pct",
    "is_dome": "is_dome",
    "vegas_over_under": "vegas_over_under",
    "era_delta_x_park": "pitcher_era_delta_x_park_factor",
    "pitcher_era_gap": "pitcher_era_gap",
}

FEATURE_NAMES = list(FEATURE_MAP.keys())
DB_COLUMNS = list(set(FEATURE_MAP.values())) + ["yrfi_label", "season", "game_id", "date"]

# Confidence tier thresholds
TIERS = {
    "Strong NRFI": (0.00, 0.35),
    "Lean NRFI":   (0.35, 0.42),
    "Skip":        (0.42, 0.58),
    "Lean YRFI":   (0.58, 0.65),
    "Strong YRFI": (0.65, 1.01),
}


# ── Data Loading ──────────────────────────────────────────────────────────────

def fetch_data() -> pd.DataFrame:
    """Fetch model features from Supabase REST API."""
    select_cols = ",".join(DB_COLUMNS)
    url = f"{SUPABASE_URL}/rest/v1/mlb_model_features"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
    }

    all_rows = []
    offset = 0
    while True:
        params = {
            "select": select_cols,
            "limit": 1000,
            "offset": offset,
            "order": "date.asc",
        }
        resp = httpx.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        rows = resp.json()
        if not rows:
            break
        all_rows.extend(rows)
        offset += 1000
        print(f"\r  Fetched {len(all_rows)} rows...", end="", flush=True)

    print(f"\r  Fetched {len(all_rows)} total rows")
    df = pd.DataFrame(all_rows)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Restore date as string
    df["date"] = pd.DataFrame(all_rows)["date"]
    return df


def prepare_features(df: pd.DataFrame) -> tuple:
    """Map column names and return (X, y, feature_names)."""
    X = pd.DataFrame()
    for friendly, actual in FEATURE_MAP.items():
        X[friendly] = df[actual].astype(float)
    y = df["yrfi_label"].astype(int)
    return X, y


# ── Optuna Tuning ─────────────────────────────────────────────────────────────

def objective(trial, X_train, y_train):
    """Optuna objective: minimize log_loss with 5-fold CV."""
    params = {
        "max_depth": trial.suggest_int("max_depth", 3, 8),
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        "n_estimators": trial.suggest_int("n_estimators", 100, 1000, step=50),
        "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
        "gamma": trial.suggest_float("gamma", 0, 5),
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "tree_method": "hist",
        "random_state": 42,
    }

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = []
    for train_idx, val_idx in cv.split(X_train, y_train):
        X_t, X_v = X_train.iloc[train_idx], X_train.iloc[val_idx]
        y_t, y_v = y_train.iloc[train_idx], y_train.iloc[val_idx]

        model = xgb.XGBClassifier(**params, verbosity=0)
        model.fit(
            X_t, y_t,
            eval_set=[(X_v, y_v)],
            verbose=False,
        )
        y_pred_proba = model.predict_proba(X_v)[:, 1]
        scores.append(log_loss(y_v, y_pred_proba))

    return np.mean(scores)


def tune_hyperparameters(X_train, y_train, n_trials=100):
    """Run Optuna hyperparameter search."""
    print(f"\n  Running Optuna ({n_trials} trials, 5-fold CV)...")
    study = optuna.create_study(direction="minimize", study_name="yrfi_xgboost")
    study.optimize(
        lambda trial: objective(trial, X_train, y_train),
        n_trials=n_trials,
        show_progress_bar=True,
    )
    print(f"  Best log_loss: {study.best_value:.4f}")
    print(f"  Best params: {json.dumps(study.best_params, indent=2)}")
    return study.best_params


# ── Training ──────────────────────────────────────────────────────────────────

def train_model(X_train, y_train, params: dict) -> xgb.XGBClassifier:
    """Train final model with best hyperparameters."""
    final_params = {
        **params,
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "tree_method": "hist",
        "random_state": 42,
    }
    model = xgb.XGBClassifier(**final_params, verbosity=0)
    model.fit(X_train, y_train)
    return model


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate_model(model, X_test, y_test):
    """Full evaluation on holdout set."""
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy": round(accuracy_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred), 4),
        "recall": round(recall_score(y_test, y_pred), 4),
        "f1": round(f1_score(y_test, y_pred), 4),
        "auc_roc": round(roc_auc_score(y_test, y_proba), 4),
        "log_loss": round(log_loss(y_test, y_proba), 4),
        "n_test": len(y_test),
        "yrfi_rate_actual": round(y_test.mean(), 4),
    }
    return metrics, y_pred, y_proba


def plot_confusion_matrix(y_test, y_pred, path):
    """Save confusion matrix plot."""
    cm = confusion_matrix(y_test, y_pred)
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.heatmap(
        cm, annot=True, fmt="d", cmap="Blues",
        xticklabels=["NRFI", "YRFI"],
        yticklabels=["NRFI", "YRFI"],
        ax=ax,
    )
    ax.set_xlabel("Predicted", fontsize=12)
    ax.set_ylabel("Actual", fontsize=12)
    ax.set_title("XGBoost YRFI Confusion Matrix (2025 Holdout)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()


def plot_calibration(y_test, y_proba, path):
    """Save calibration plot (predicted prob vs actual YRFI rate in decile buckets)."""
    df = pd.DataFrame({"proba": y_proba, "actual": y_test})
    df["bucket"] = pd.qcut(df["proba"], q=10, duplicates="drop")
    cal = df.groupby("bucket", observed=True).agg(
        mean_predicted=("proba", "mean"),
        mean_actual=("actual", "mean"),
        count=("actual", "count"),
    ).reset_index()

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.plot([0, 1], [0, 1], "k--", alpha=0.5, label="Perfect calibration")
    ax.scatter(cal["mean_predicted"], cal["mean_actual"], s=cal["count"], c="steelblue", alpha=0.8, edgecolors="navy", zorder=5)
    ax.plot(cal["mean_predicted"], cal["mean_actual"], "o-", color="steelblue", label="XGBoost")

    for _, row in cal.iterrows():
        ax.annotate(
            f"n={int(row['count'])}",
            (row["mean_predicted"], row["mean_actual"]),
            textcoords="offset points", xytext=(5, 10), fontsize=8, alpha=0.7,
        )

    ax.set_xlabel("Mean Predicted P(YRFI)", fontsize=12)
    ax.set_ylabel("Actual YRFI Rate", fontsize=12)
    ax.set_title("XGBoost Calibration Plot (2025 Holdout)\nPredicted Probability vs Actual YRFI Rate by Decile", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return cal


def threshold_analysis(y_test, y_proba):
    """Classification report at multiple thresholds."""
    thresholds = [0.40, 0.45, 0.50, 0.55, 0.60]
    results = []
    for t in thresholds:
        y_pred_t = (y_proba >= t).astype(int)
        yrfi_picks = (y_proba >= t).sum()
        nrfi_picks = (y_proba < t).sum()
        results.append({
            "threshold": t,
            "accuracy": round(accuracy_score(y_test, y_pred_t), 4),
            "precision_yrfi": round(precision_score(y_test, y_pred_t, zero_division=0), 4),
            "recall_yrfi": round(recall_score(y_test, y_pred_t, zero_division=0), 4),
            "f1": round(f1_score(y_test, y_pred_t, zero_division=0), 4),
            "yrfi_picks": int(yrfi_picks),
            "nrfi_picks": int(nrfi_picks),
        })
    return results


# ── SHAP Analysis ─────────────────────────────────────────────────────────────

def shap_analysis(model, X_test, path_summary, path_importance_csv):
    """SHAP values analysis and summary plot."""
    explainer = shap.TreeExplainer(model)
    shap_values = explainer(X_test)

    # Summary plot
    fig, ax = plt.subplots(figsize=(14, 10))
    shap.summary_plot(shap_values, X_test, show=False, max_display=19)
    plt.title("SHAP Feature Importance — XGBoost YRFI Model\nRed = pushes toward YRFI, Blue = pushes toward NRFI", fontsize=13, fontweight="bold")
    plt.tight_layout()
    plt.savefig(path_summary, dpi=150, bbox_inches="tight")
    plt.close("all")

    # Top 10 by mean |SHAP|
    mean_abs_shap = np.abs(shap_values.values).mean(axis=0)
    importance_df = pd.DataFrame({
        "feature": X_test.columns,
        "mean_abs_shap": mean_abs_shap,
    }).sort_values("mean_abs_shap", ascending=False)
    importance_df["rank"] = range(1, len(importance_df) + 1)
    importance_df.to_csv(path_importance_csv, index=False)

    return importance_df


# ── Confidence Tier Analysis ──────────────────────────────────────────────────

def confidence_tier_breakdown(y_test, y_proba):
    """Map predictions to confidence tiers and measure accuracy in each."""
    results = []
    for tier_name, (low, high) in TIERS.items():
        mask = (y_proba >= low) & (y_proba < high)
        n = mask.sum()
        if n == 0:
            continue

        actual_yrfi_rate = y_test[mask].mean()
        if "YRFI" in tier_name:
            correct = (y_test[mask] == 1).sum()
        elif "NRFI" in tier_name:
            correct = (y_test[mask] == 0).sum()
        else:
            correct = 0  # Skip has no "correct" direction

        accuracy = correct / n if n > 0 and "Skip" not in tier_name else None

        results.append({
            "tier": tier_name,
            "n_games": int(n),
            "actual_yrfi_rate": round(float(actual_yrfi_rate), 4),
            "accuracy": round(float(accuracy), 4) if accuracy is not None else None,
            "pct_of_total": round(n / len(y_test) * 100, 1),
        })
    return results


# ── Rule-Based Model Simulation ───────────────────────────────────────────────

def simulate_rule_based(X_test):
    """
    Simulate the rule-based weighted model on test features.
    Maps XGBoost features back to the rule-based 0-100 scoring system.
    """
    scores = np.full(len(X_test), 50.0)  # Start at neutral 50

    # Pitcher first-inning quality (weight 0.25 in rules)
    # ERA < 2 = strong NRFI, ERA > 5 = strong YRFI
    for col in ["home_p_fi_era", "away_p_fi_era"]:
        era = X_test[col].values
        adj = np.where(era < 2.0, -12, np.where(era < 3.0, -6, np.where(era > 5.0, 12, np.where(era > 4.0, 6, 0))))
        scores += adj * 0.25

    # Scoreless pct (within pitcher factor)
    for col in ["home_p_scoreless_pct", "away_p_scoreless_pct"]:
        sp = X_test[col].values
        adj = np.where(sp > 80, -5, np.where(sp < 55, 5, 0))
        scores += adj * 0.25

    # Slow starter delta (weight 0.10)
    for col in ["home_p_era_delta", "away_p_era_delta"]:
        delta = X_test[col].values
        adj = np.where(delta > 1.5, 15, np.where(delta > 1.0, 10, np.where(delta < -0.5, -5, 0)))
        scores += adj * 0.10

    # Park factor (weight 0.10)
    park = X_test["park_yrfi_pct"].values
    adj = np.where(park > 55, 8, np.where(park > 50, 3, np.where(park < 42, -8, np.where(park < 46, -3, 0))))
    scores += adj * 0.10

    # Team YRFI rates (recent form proxy, weight ~0.05 each)
    for col, w in [("home_team_yrfi_pct", 0.05), ("away_team_yrfi_pct", 0.05)]:
        rate = X_test[col].values
        adj = np.where(rate > 55, 5, np.where(rate < 40, -5, 0))
        scores += adj * w

    # Vegas O/U correlation check
    ou = X_test["vegas_over_under"].values
    adj = np.where(ou >= 10.0, 3, np.where(ou >= 9.5, 1, np.where(ou <= 7.5, -2, 0)))
    scores += adj * 0.05

    # Clamp to 0-100
    scores = np.clip(scores, 0, 100)

    # Convert to P(YRFI) on 0-1 scale
    return scores / 100.0


def rule_based_classify(proba):
    """Classify rule-based probability to YRFI/NRFI/SKIP."""
    if proba >= 0.58:
        return "YRFI"
    elif proba <= 0.42:
        return "NRFI"
    return "SKIP"


def xgb_classify(proba):
    """Classify XGBoost probability to tier."""
    if proba >= 0.65:
        return "YRFI"
    elif proba >= 0.58:
        return "YRFI"
    elif proba <= 0.35:
        return "NRFI"
    elif proba <= 0.42:
        return "NRFI"
    return "SKIP"


def hybrid_comparison(y_test, xgb_proba, rb_proba):
    """Compare rule-based vs XGBoost vs agreement picks."""
    xgb_picks = np.array([xgb_classify(p) for p in xgb_proba])
    rb_picks = np.array([rule_based_classify(p) for p in rb_proba])
    actual = np.array(["YRFI" if y == 1 else "NRFI" for y in y_test])

    # Agreement: both models pick the same non-SKIP direction
    agree_mask = (xgb_picks == rb_picks) & (xgb_picks != "SKIP")
    both_skip = (xgb_picks == "SKIP") & (rb_picks == "SKIP")

    results = {}

    # XGBoost accuracy (non-skip picks only)
    xgb_active = xgb_picks != "SKIP"
    if xgb_active.sum() > 0:
        results["xgboost"] = {
            "n_picks": int(xgb_active.sum()),
            "n_skip": int((xgb_picks == "SKIP").sum()),
            "accuracy": round(float((xgb_picks[xgb_active] == actual[xgb_active]).mean()), 4),
        }

    # Rule-based accuracy (non-skip picks only)
    rb_active = rb_picks != "SKIP"
    if rb_active.sum() > 0:
        results["rule_based"] = {
            "n_picks": int(rb_active.sum()),
            "n_skip": int((rb_picks == "SKIP").sum()),
            "accuracy": round(float((rb_picks[rb_active] == actual[rb_active]).mean()), 4),
        }

    # Agreement picks
    if agree_mask.sum() > 0:
        results["consensus"] = {
            "n_picks": int(agree_mask.sum()),
            "accuracy": round(float((xgb_picks[agree_mask] == actual[agree_mask]).mean()), 4),
            "pct_of_games": round(agree_mask.sum() / len(y_test) * 100, 1),
        }

    # Disagreement picks
    disagree_mask = (xgb_picks != rb_picks) & xgb_active & rb_active
    if disagree_mask.sum() > 0:
        xgb_wins = (xgb_picks[disagree_mask] == actual[disagree_mask]).sum()
        rb_wins = (rb_picks[disagree_mask] == actual[disagree_mask]).sum()
        results["disagreement"] = {
            "n_games": int(disagree_mask.sum()),
            "xgb_correct": int(xgb_wins),
            "rb_correct": int(rb_wins),
        }

    return results


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="YRFI XGBoost Training Pipeline")
    parser.add_argument("--retrain", action="store_true", help="Retrain on all data (no holdout)")
    parser.add_argument("--trials", type=int, default=100, help="Number of Optuna trials")
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print("=" * 60)
    print("YRFI/NRFI XGBoost Training Pipeline")
    print(f"Timestamp: {timestamp}")
    print("=" * 60)

    # ── 1. Load Data ──────────────────────────────────────────────
    print("\n[1/8] Loading data from Supabase...")
    df = fetch_data()
    X_all, y_all = prepare_features(df)

    # Handle nulls: median impute (preserves more rows than dropping)
    null_counts = X_all.isnull().sum()
    nulls_before = X_all.isnull().any(axis=1).sum()
    X_all = X_all.fillna(X_all.median())
    print(f"  Imputed {nulls_before} rows with median values")
    print(f"  Features: {len(FEATURE_NAMES)}, Samples: {len(X_all)}")
    print(f"  YRFI rate: {y_all.mean():.3f}")

    # ── 2. Temporal Split ─────────────────────────────────────────
    print("\n[2/8] Temporal split...")
    seasons = df["season"].astype(int)

    if args.retrain:
        X_train, y_train = X_all, y_all
        X_test, y_test = X_all[seasons == 2025], y_all[seasons == 2025]
        print(f"  RETRAIN mode: using all {len(X_train)} games for training")
        print(f"  (2025 holdout stats still computed for reference: {len(X_test)} games)")
    else:
        train_mask = seasons.isin([2023, 2024])
        test_mask = seasons == 2025
        X_train, y_train = X_all[train_mask], y_all[train_mask]
        X_test, y_test = X_all[test_mask], y_all[test_mask]
        print(f"  Train (2023-2024): {len(X_train)} games, YRFI rate: {y_train.mean():.3f}")
        print(f"  Test  (2025):      {len(X_test)} games, YRFI rate: {y_test.mean():.3f}")

    # ── 3. Hyperparameter Tuning ──────────────────────────────────
    print("\n[3/8] Hyperparameter tuning...")
    best_params = tune_hyperparameters(X_train, y_train, n_trials=args.trials)

    # ── 4. Train Final Model ──────────────────────────────────────
    print("\n[4/8] Training final model...")
    model = train_model(X_train, y_train, best_params)
    print("  Model trained successfully")

    # ── 5. Evaluate ───────────────────────────────────────────────
    print("\n[5/8] Evaluating on 2025 holdout...")
    metrics, y_pred, y_proba = evaluate_model(model, X_test, y_test)
    print(f"  Accuracy:  {metrics['accuracy']:.4f}")
    print(f"  Precision: {metrics['precision']:.4f}")
    print(f"  Recall:    {metrics['recall']:.4f}")
    print(f"  F1:        {metrics['f1']:.4f}")
    print(f"  AUC-ROC:   {metrics['auc_roc']:.4f}")
    print(f"  Log Loss:  {metrics['log_loss']:.4f}")

    # Confusion matrix
    cm_path = os.path.join(MODELS_DIR, "confusion_matrix.png")
    plot_confusion_matrix(y_test, y_pred, cm_path)
    print(f"  Confusion matrix → {cm_path}")

    # Calibration plot
    cal_path = os.path.join(MODELS_DIR, "calibration_plot.png")
    cal_data = plot_calibration(y_test, y_proba, cal_path)
    print(f"  Calibration plot → {cal_path}")

    # Threshold analysis
    print("\n  Threshold Analysis:")
    threshold_results = threshold_analysis(y_test, y_proba)
    print(f"  {'Threshold':>10} {'Accuracy':>10} {'Prec(YRFI)':>12} {'Recall(YRFI)':>14} {'F1':>8} {'YRFI':>6} {'NRFI':>6}")
    for r in threshold_results:
        print(f"  {r['threshold']:>10.2f} {r['accuracy']:>10.4f} {r['precision_yrfi']:>12.4f} {r['recall_yrfi']:>14.4f} {r['f1']:>8.4f} {r['yrfi_picks']:>6} {r['nrfi_picks']:>6}")

    # ── 6. SHAP Analysis ─────────────────────────────────────────
    print("\n[6/8] SHAP analysis...")
    shap_path = os.path.join(MODELS_DIR, "shap_summary.png")
    importance_csv = os.path.join(MODELS_DIR, "feature_importance.csv")
    importance_df = shap_analysis(model, X_test, shap_path, importance_csv)
    print(f"\n  Top 10 Features (mean |SHAP|):")
    for _, row in importance_df.head(10).iterrows():
        print(f"    {int(row['rank']):>2}. {row['feature']:30s} {row['mean_abs_shap']:.4f}")
    print(f"  SHAP summary → {shap_path}")
    print(f"  Feature importance CSV → {importance_csv}")

    # ── 7. Confidence Tiers ───────────────────────────────────────
    print("\n[7/8] Confidence tier breakdown...")
    tier_results = confidence_tier_breakdown(y_test, y_proba)
    print(f"  {'Tier':>15} {'Games':>7} {'YRFI Rate':>11} {'Accuracy':>10} {'% of Total':>12}")
    for t in tier_results:
        acc_str = f"{t['accuracy']:.1%}" if t["accuracy"] is not None else "N/A"
        print(f"  {t['tier']:>15} {t['n_games']:>7} {t['actual_yrfi_rate']:>11.1%} {acc_str:>10} {t['pct_of_total']:>11.1f}%")

    # ── 8. Hybrid Comparison ──────────────────────────────────────
    print("\n[8/8] Hybrid model comparison...")
    rb_proba = simulate_rule_based(X_test)
    hybrid = hybrid_comparison(y_test, y_proba, rb_proba)

    if "xgboost" in hybrid:
        print(f"  XGBoost:    {hybrid['xgboost']['accuracy']:.1%} accuracy on {hybrid['xgboost']['n_picks']} picks ({hybrid['xgboost']['n_skip']} skipped)")
    if "rule_based" in hybrid:
        print(f"  Rule-based: {hybrid['rule_based']['accuracy']:.1%} accuracy on {hybrid['rule_based']['n_picks']} picks ({hybrid['rule_based']['n_skip']} skipped)")
    if "consensus" in hybrid:
        print(f"  Consensus:  {hybrid['consensus']['accuracy']:.1%} accuracy on {hybrid['consensus']['n_picks']} picks ({hybrid['consensus']['pct_of_games']:.1f}% of games)")
    if "disagreement" in hybrid:
        d = hybrid["disagreement"]
        print(f"  Disagreements: {d['n_games']} games — XGB correct {d['xgb_correct']}, RB correct {d['rb_correct']}")

    # ── Save Artifacts ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("Saving artifacts...")

    # Model
    model_path = os.path.join(MODELS_DIR, "yrfi_xgboost.joblib")
    joblib.dump(model, model_path)
    print(f"  Model → {model_path}")

    # Full metrics JSON
    full_results = {
        "timestamp": timestamp,
        "model_version": f"xgb_v1_{timestamp}",
        "train_seasons": [2023, 2024] if not args.retrain else [2023, 2024, 2025],
        "test_season": 2025,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "features": FEATURE_NAMES,
        "best_hyperparameters": best_params,
        "holdout_metrics": metrics,
        "threshold_analysis": threshold_results,
        "confidence_tiers": tier_results,
        "hybrid_comparison": hybrid,
        "shap_top_10": importance_df.head(10).to_dict("records"),
    }
    metrics_path = os.path.join(MODELS_DIR, "evaluation_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(full_results, f, indent=2, default=str)
    print(f"  Metrics JSON → {metrics_path}")

    # Feature config for inference
    config = {
        "feature_names": FEATURE_NAMES,
        "feature_map": FEATURE_MAP,
        "confidence_tiers": {k: list(v) for k, v in TIERS.items()},
        "model_version": full_results["model_version"],
    }
    config_path = os.path.join(MODELS_DIR, "model_config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    print(f"  Config → {config_path}")

    print("\n" + "=" * 60)
    print("Training pipeline complete!")
    print(f"Model version: {full_results['model_version']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
