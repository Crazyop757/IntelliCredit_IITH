"""
credit_scorer.py — LightGBM credit risk scorer for intelli_credit.

Wraps a LightGBM binary classifier that predicts the probability of default
(label=1) from the 35-feature Gold-layer vector produced by FeatureBuilder.

Public API
----------
    from src.scorer.credit_scorer import CreditScorer

    scorer = CreditScorer()

    # 1. Train (one-time or periodic re-training)
    scorer.train("data/silver/training_data.csv")
    # → prints classification report + AUC
    # → saves model to models/credit_scorer.pkl

    # 2. Score a company
    result = scorer.score(feature_vector)
    # result keys:
    #   default_probability   float  0–1
    #   risk_score            float  0–10  (10 = safest)
    #   risk_band             str    PRIME / LOW / MEDIUM / HIGH
    #   raw_lgbm_proba        float  raw model P(default)
    #   shap_explanations     dict   top risk + top positive SHAP factors

    # 3. Apply credit-officer qualitative adjustment
    adjusted = scorer.apply_qualitative_adjustment(result, qualitative_delta=-1.5)
    # → re-classifies risk_band; score clamped to [0, 10]

Risk-band thresholds  (based on risk_score, higher = safer)
-----------------------------------------------------------
    PRIME    : risk_score ≥ 8.0   (default_prob ≤ 0.20)
    LOW      : 6.0 ≤ risk_score < 8.0
    MEDIUM   : 4.0 ≤ risk_score < 6.0
    HIGH     : risk_score < 4.0   (default_prob > 0.60)

SHAP explanations
-----------------
After every ``score()`` call, ``shap.TreeExplainer`` is run on the model.
The top 3 features with the most *negative* SHAP values drive HIGH RISK
(they push the prediction toward default); the top 3 with the most
*positive* SHAP values represent protective / LOW RISK signals.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Project-root path bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("intelli_credit.scorer.credit_scorer")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_MODELS_DIR   = _PROJECT_ROOT / "models"
_MODELS_DIR.mkdir(parents=True, exist_ok=True)

_DEFAULT_MODEL_PATH = _MODELS_DIR / "credit_scorer.pkl"

# ---------------------------------------------------------------------------
# Risk-band thresholds (applied to risk_score, higher = safer)
# ---------------------------------------------------------------------------
_RISK_BANDS: list[tuple[float, str]] = [
    (8.0, "PRIME"),    # risk_score ≥ 8.0
    (6.0, "LOW"),      # 6.0 ≤ risk_score < 8.0
    (4.0, "MEDIUM"),   # 4.0 ≤ risk_score < 6.0
    (0.0, "HIGH"),     # risk_score < 4.0
]

# ---------------------------------------------------------------------------
# Human-readable feature labels for SHAP output
# ---------------------------------------------------------------------------
_FEATURE_LABELS: dict[str, str] = {
    "debt_to_equity":                    "Debt-to-Equity Ratio",
    "current_ratio":                     "Current Ratio",
    "interest_coverage":                 "Interest Coverage Ratio",
    "dscr":                              "Debt Service Coverage Ratio (DSCR)",
    "pat_margin":                        "Profit After Tax Margin",
    "roce":                              "Return on Capital Employed",
    "revenue_growth_3y":                 "3-Year Revenue Growth (CAGR)",
    "avg_monthly_balance":               "Average Monthly Bank Balance",
    "debit_credit_ratio":                "Debit / Credit Ratio",
    "bounce_count":                      "Cheque / ECS Bounce Count",
    "upi_concentration":                 "UPI Transaction Concentration (%)",
    "gst_health_score":                  "GST Health Score (0–10)",
    "itc_gap_pct":                       "ITC Gap vs GSTR-2A (%)",
    "turnover_consistency":              "GST Turnover Consistency",
    "filing_regularity":                 "GST Filing Regularity",
    "circular_trading_confidence":       "Circular Trading Confidence",
    "revenue_inflation_flag":            "Revenue Inflation Flag",
    "cash_stress_flag":                  "Cash Stress Flag",
    "news_risk_score":                   "News Risk Score (0–10)",
    "litigation_count":                  "eCourts Litigation Count",
    "has_wilful_default_flag":           "RBI Wilful Defaulter Flag",
    "mca_charges_vs_declared_debt_gap":  "MCA Charges vs Declared Debt Gap",
    "ecourts_severity_score":            "eCourts Litigation Severity Score",
    "qualitative_adjustment":            "Credit-Officer Qualitative Adjustment",
    "gst_itc_fraud_flag":                "GST ITC Fraud Risk Flag",
    "documentation_risk_flag":           "Documentation Risk Flag",
    "auditor_concern_flag":              "Auditor Concern Flag",
    "director_risk_flag":                "Director Risk Flag",
    "compliance_risk_flag":              "Compliance Risk Flag",
    "ews_score":                         "Early Warning Score (0–5)",
    "ner_sentiment_score":               "NER Sentiment Score",
    "ner_risk_clause_count":             "NER Risk Clause Count",
    "ner_auditor_flag":                  "NER Auditor Flag",
    "nclt_override_flag":                "NCLT Override Flag",
    "gnn_high_risk_gstin_count":         "GNN High-Risk GSTIN Count",
}


def _classify_risk_band(risk_score: float) -> str:
    """Map a risk_score (0–10, higher = safer) to a risk band label."""
    for threshold, band in _RISK_BANDS:
        if risk_score >= threshold:
            return band
    return "HIGH"


# ===========================================================================
# CreditScorer
# ===========================================================================

class CreditScorer:
    """
    LightGBM binary classifier for credit default prediction.

    Parameters
    ----------
    model_path : str | Path | None
        Path to the serialised model file.  Defaults to
        ``models/credit_scorer.pkl``.  The model is loaded lazily on the
        first call to ``score()``.
    """

    def __init__(self, model_path: str | Path | None = None) -> None:
        self.model_path: Path = (
            Path(model_path) if model_path else _DEFAULT_MODEL_PATH
        )
        self._model = None   # lazy-loaded LightGBM pipeline

    # ==================================================================
    # 1. train
    # ==================================================================

    def train(self, training_data_path: str | Path) -> dict[str, Any]:
        """
        Load CSV, split 80/20 train/test, train an ensemble model with
        SMOTE + Optuna hyperparameter search + LightGBM & RandomForest
        voting ensemble, and persist the model artefact.

        Pipeline
        --------
        1. StandardScaler (fit on train, applied to train + test)
        2. SMOTE (applied to scaled train only; inference-time transforms
           are just scaler → ensemble, no SMOTE at inference)
        3. Optuna (50-trial CV search over LightGBM hyper-parameters)
        4. VotingClassifier(LGBM 60% + RandomForest 40%, soft voting)
        5. Separate LightGBM (same best params) kept for SHAP explanations,
           since VotingClassifier does not expose a booster.

        The CSV must contain a ``label`` column (1 = default, 0 = non-default).
        All other numeric columns are used as features.  Missing values are
        filled with 0 before training.

        Parameters
        ----------
        training_data_path : str | Path
            Path to the labelled training CSV.

        Returns
        -------
        dict — training results containing ``auc``, ``classification_report``,
        ``feature_names``, ``n_train``, ``n_test``.
        """
        try:
            import lightgbm as lgb  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "LightGBM is required for training. "
                "Install with: pip install lightgbm"
            ) from exc

        try:
            import joblib  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "joblib is required. Install with: pip install joblib"
            ) from exc

        from collections import Counter                        # noqa: PLC0415
        from sklearn.metrics import (                          # noqa: PLC0415
            classification_report,
            roc_auc_score,
        )
        from sklearn.model_selection import (                  # noqa: PLC0415
            cross_val_score,
            train_test_split,
        )
        from sklearn.preprocessing import StandardScaler       # noqa: PLC0415
        from sklearn.ensemble import (                         # noqa: PLC0415
            RandomForestClassifier,
            VotingClassifier,
        )

        # ── Optional dependencies with graceful fallback ───────────────
        try:
            from imblearn.over_sampling import SMOTE           # noqa: PLC0415
            _has_smote = True
        except ImportError:
            logger.warning(
                "imbalanced-learn not installed — skipping SMOTE.  "
                "pip install imbalanced-learn"
            )
            _has_smote = False

        try:
            import optuna                                       # noqa: PLC0415
            optuna.logging.set_verbosity(optuna.logging.WARNING)
            _has_optuna = True
        except ImportError:
            logger.warning(
                "optuna not installed — using default LightGBM params.  "
                "pip install optuna"
            )
            _has_optuna = False

        # ── Load data ─────────────────────────────────────────────────
        path = Path(training_data_path)
        logger.info("Loading training data from %s …", path)
        df = pd.read_csv(path)

        if "label" not in df.columns:
            raise ValueError(
                f"Training CSV must contain a 'label' column. "
                f"Found: {list(df.columns)}"
            )

        feature_cols = [c for c in df.columns if c != "label"]
        X = df[feature_cols].fillna(0).values.astype(np.float32)
        y = df["label"].values.astype(int)

        logger.info(
            "Dataset: %d samples, %d features, %.1f%% default rate.",
            len(df), len(feature_cols), y.mean() * 100,
        )

        # ── Train / test split (80 / 20, stratified) ──────────────────
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=0.20,
            random_state=42,
            stratify=y,
        )
        logger.info(
            "Train: %d samples | Test: %d samples.", len(X_train), len(X_test)
        )

        # ── Step 1: StandardScaler ────────────────────────────────────
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled  = scaler.transform(X_test)

        # ── Step 2: SMOTE ─────────────────────────────────────────────
        if _has_smote:
            print(f"  Before SMOTE: {Counter(y_train)}")
            smote = SMOTE(random_state=42, k_neighbors=5)
            X_train_bal, y_train_bal = smote.fit_resample(X_train_scaled, y_train)
            print(f"  After  SMOTE: {Counter(y_train_bal)}")
        else:
            X_train_bal, y_train_bal = X_train_scaled, y_train

        # Keep DataFrames with feature names so LightGBM doesn't warn
        X_train_df = pd.DataFrame(X_train_bal,   columns=feature_cols)
        X_test_df  = pd.DataFrame(X_test_scaled, columns=feature_cols)

        # ── Step 3: Optuna hyperparameter search ──────────────────────
        if _has_optuna:
            def _objective(trial: "optuna.Trial") -> float:
                params = {
                    "n_estimators":      trial.suggest_int("n_estimators",   200, 800),
                    "max_depth":         trial.suggest_int("max_depth",         4,  10),
                    "learning_rate":     trial.suggest_float("learning_rate", 0.01, 0.10),
                    "num_leaves":        trial.suggest_int("num_leaves",       31, 127),
                    "min_child_samples": trial.suggest_int("min_child_samples", 10,  50),
                    "subsample":         trial.suggest_float("subsample",       0.6, 1.0),
                    "colsample_bytree":  trial.suggest_float("colsample_bytree", 0.6, 1.0),
                    "reg_alpha":         trial.suggest_float("reg_alpha",       0.0, 0.5),
                    "reg_lambda":        trial.suggest_float("reg_lambda",      0.0, 0.5),
                    "class_weight":      "balanced",
                    "random_state":      42,
                    "verbose":           -1,
                }
                m = lgb.LGBMClassifier(**params)
                return cross_val_score(
                    m, X_train_df, y_train_bal, cv=5, scoring="roc_auc"
                ).mean()

            print("  Running Optuna (50 trials) …")
            study = optuna.create_study(direction="maximize")
            study.optimize(_objective, n_trials=50, show_progress_bar=True)
            best_params: dict[str, Any] = dict(study.best_params)
            best_params.update({"class_weight": "balanced", "random_state": 42, "verbose": -1})
            print(f"  Best Optuna CV-AUC : {study.best_value:.4f}")
            print(f"  Best params        : {best_params}")
        else:
            best_params = {
                "n_estimators":      500,
                "max_depth":         8,
                "learning_rate":     0.03,
                "num_leaves":        63,
                "min_child_samples": 20,
                "subsample":         0.8,
                "subsample_freq":    1,
                "colsample_bytree":  0.8,
                "reg_alpha":         0.1,
                "reg_lambda":        0.1,
                "class_weight":      "balanced",
                "random_state":      42,
                "verbose":           -1,
            }

        # ── Step 4: Cross-validate final LGBM config ──────────────────
        cv_scores = cross_val_score(
            lgb.LGBMClassifier(**best_params),
            X_train_df, y_train_bal,
            cv=5, scoring="roc_auc",
        )
        print(f"  5-Fold CV AUC (LGBM): {cv_scores.mean():.4f} "
              f"(+/- {cv_scores.std():.4f})")

        # ── Step 5: Build & fit ensemble ──────────────────────────────
        lgbm_clf = lgb.LGBMClassifier(**best_params)
        rf_clf   = RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=10,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
        ensemble = VotingClassifier(
            estimators=[("lgbm", lgbm_clf), ("rf", rf_clf)],
            voting="soft",
            weights=[0.6, 0.4],
        )
        print("  Training ensemble (LightGBM 60% + RandomForest 40%) …")
        ensemble.fit(X_train_df, y_train_bal)

        # ── Step 6: Dedicated LGBM for SHAP ──────────────────────────
        # VotingClassifier does not expose a booster, so keep a separate
        # LightGBM model trained on the same data.
        lgbm_for_shap = lgb.LGBMClassifier(**best_params)
        lgbm_for_shap.fit(X_train_df, y_train_bal)

        # ── Evaluation ────────────────────────────────────────────────
        y_proba_ens  = ensemble.predict_proba(X_test_df)[:, 1]
        y_pred_ens   = ensemble.predict(X_test_df)
        auc_ens      = roc_auc_score(y_test, y_proba_ens)
        clf_report   = classification_report(y_test, y_pred_ens, digits=3)

        auc_lgbm = roc_auc_score(
            y_test, lgbm_for_shap.predict_proba(X_test_df)[:, 1]
        )

        print("\n" + "=" * 60)
        print("  CreditScorer — Training Complete")
        print("=" * 60)
        print(f"  Train samples    : {len(X_train)}")
        print(f"  Test samples     : {len(X_test)}")
        print(f"  Features         : {len(feature_cols)}")
        print(f"\n  Ensemble AUC-ROC : {auc_ens:.4f}")
        print(f"  LightGBM AUC-ROC : {auc_lgbm:.4f}  (used for SHAP)")
        print("\n  Classification Report (Ensemble, test set):")
        for line in clf_report.splitlines():
            print(f"    {line}")
        print("=" * 60 + "\n")

        logger.info("Ensemble AUC-ROC: %.4f", auc_ens)

        # ── Persist model ──────────────────────────────────────────────
        # Artefact stores scaler + ensemble + SHAP-model + feature names.
        # No sklearn Pipeline wrapper — SMOTE can only be applied during
        # training, not at inference time.
        artefact: dict[str, Any] = {
            "scaler":        scaler,
            "model":         ensemble,
            "lgbm_for_shap": lgbm_for_shap,
            "feature_names": feature_cols,
        }
        joblib.dump(artefact, self.model_path)
        logger.info("Model saved → %s", self.model_path)

        # Cache in memory
        self._model = artefact

        return {
            "auc":                   round(auc_ens, 4),
            "classification_report": clf_report,
            "feature_names":         feature_cols,
            "n_train":               len(X_train),
            "n_test":                len(X_test),
        }

    # ==================================================================
    # 2. score
    # ==================================================================

    def score(self, feature_vector: dict[str, float]) -> dict[str, Any]:
        """
        Score a company using the trained LightGBM model.

        The feature vector may contain any subset of the 35 Gold-layer
        features.  Missing features are filled with 0.

        Parameters
        ----------
        feature_vector : dict[str, float]
            ``{feature_name: numeric_value}`` as returned by
            ``FeatureBuilder.build_feature_vector()``.

        Returns
        -------
        dict with keys:

        =====================  =============================================
        default_probability    float  0–1   P(default) from LightGBM
        risk_score             float  0–10  10 × (1 − default_probability)
        risk_band              str    PRIME / LOW / MEDIUM / HIGH
        raw_lgbm_proba         float  identical to default_probability
        shap_explanations      dict   top risk / positive SHAP factors
        =====================  =============================================
        """
        artefact = self._load_model()
        feature_names: list[str] = artefact["feature_names"]

        # ── Build input row in training-column order ───────────────────
        # Accept both dict[str, float] and a single-row pd.DataFrame.
        if isinstance(feature_vector, pd.DataFrame):
            # Reindex to ensure correct column order; missing cols → 0.0
            row = (
                feature_vector
                .reindex(columns=feature_names, fill_value=0.0)
                .iloc[:1]
                .astype(np.float32)
                .reset_index(drop=True)
            )
        else:
            row = pd.DataFrame(
                [[float(feature_vector.get(f, 0.0)) for f in feature_names]],
                columns=feature_names,
            ).astype(np.float32)

        # ── Predict ───────────────────────────────────────────────────
        # Support both the new ensemble artefact format (scaler + model)
        # and the legacy Pipeline format (pipeline key).
        if "scaler" in artefact and artefact.get("model") is not None:
            scaler = artefact["scaler"]
            model  = artefact["model"]
            row_scaled = pd.DataFrame(
                scaler.transform(row.values), columns=feature_names
            ).astype(np.float32)
            default_prob = float(model.predict_proba(row_scaled)[0, 1])
        else:
            pipeline = artefact["pipeline"]
            default_prob = float(pipeline.predict_proba(row)[0, 1])

        risk_score   = round(10.0 * (1.0 - default_prob), 4)
        risk_band    = _classify_risk_band(risk_score)

        # ── SHAP explanations ─────────────────────────────────────────
        shap_explanations = self._compute_shap(
            artefact, feature_names, row
        )

        return {
            "default_probability": round(default_prob, 4),
            "risk_score":          risk_score,
            "risk_band":           risk_band,
            "raw_lgbm_proba":      round(default_prob, 4),
            "shap_explanations":   shap_explanations,
        }

    # ==================================================================
    # 3. apply_qualitative_adjustment
    # ==================================================================

    def apply_qualitative_adjustment(
        self,
        score_dict:         dict[str, Any],
        qualitative_delta:  float,
    ) -> dict[str, Any]:
        """
        Apply a post-model qualitative adjustment from a credit officer.

        ⚠️  This is a **human-in-the-loop** post-processing step.  The
        LightGBM model score is treated as a prior; the credit officer's
        qualitative delta (from ``QualitativeScorer``) shifts the final
        risk score.  This adjustment is intentionally transparent and
        auditable — the original model score is preserved alongside the
        adjusted score so reviewers can see the exact human override.

        Adjustment convention
        ---------------------
        * ``qualitative_delta > 0``  — positive observation → raises
          risk_score (company looks better than the model suggests).
        * ``qualitative_delta < 0``  — negative observation → lowers
          risk_score (company looks worse than the model suggests).
        * Range expected: −5.0 … +2.0 (from ``QualitativeScorer``).

        The adjusted score is clamped to [0.0, 10.0] and the risk_band
        is re-classified using the same thresholds as ``score()``.

        Parameters
        ----------
        score_dict : dict
            The dict returned by ``score()``.
        qualitative_delta : float
            Signed adjustment to add to ``risk_score``.

        Returns
        -------
        dict — enriched copy of *score_dict* with extra keys:

        ================================  ===================================
        adjusted_risk_score               float  0–10 (clamped)
        adjusted_risk_band                str    PRIME / LOW / MEDIUM / HIGH
        qualitative_delta_applied         float  the delta that was applied
        model_risk_score_before_adj       float  original risk_score
        qualitative_adjustment_note       str    human-readable audit note
        ================================  ===================================
        """
        original_score = float(score_dict.get("risk_score", 0.0))
        raw_adjusted   = original_score + float(qualitative_delta)
        clamped        = round(max(0.0, min(10.0, raw_adjusted)), 4)
        new_band       = _classify_risk_band(clamped)

        direction = "raised" if qualitative_delta >= 0 else "lowered"
        note = (
            f"Credit-officer qualitative review {direction} the risk score "
            f"by {abs(qualitative_delta):.2f} points "
            f"(model score {original_score:.2f} → adjusted {clamped:.2f}; "
            f"band {score_dict.get('risk_band', '?')} → {new_band}). "
            f"This is a post-model human override and is fully auditable."
        )

        return {
            **score_dict,
            "adjusted_risk_score":           clamped,
            "adjusted_risk_band":            new_band,
            "qualitative_delta_applied":     round(float(qualitative_delta), 4),
            "model_risk_score_before_adj":   original_score,
            "qualitative_adjustment_note":   note,
        }

    # ==================================================================
    # Private helpers
    # ==================================================================

    def _load_model(self) -> dict[str, Any]:
        """
        Return the cached model artefact, loading from disk if needed.

        Raises
        ------
        FileNotFoundError
            When the model file does not exist (train first).
        """
        if self._model is not None:
            return self._model

        try:
            import joblib  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "joblib is required. Install with: pip install joblib"
            ) from exc

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Model file not found: {self.model_path}\n"
                "Run CreditScorer().train('data/silver/training_data.csv') first."
            )

        self._model = joblib.load(self.model_path)
        logger.info("Model loaded from %s", self.model_path)
        return self._model

    def _compute_shap(
        self,
        artefact_or_pipeline: Any,
        feature_names: list[str],
        row_df:        "pd.DataFrame",
    ) -> dict[str, Any]:
        """
        Run SHAP TreeExplainer on the LightGBM model and return explanations.

        Supports two artefact formats:
        - **New** (dict with ``scaler`` + ``lgbm_for_shap`` keys):
          the dedicated LightGBM model is used so TreeExplainer works even
          when the primary predictor is a VotingClassifier.
        - **Legacy** (``Pipeline`` with ``"scaler"`` and ``"lgbm"`` steps):
          behaviour is unchanged for any existing saved model files.

        *row_df* is always the **unscaled** single-row DataFrame.

        SHAP value interpretation
        -------------------------
        Positive SHAP → pushes prediction toward **default** (increases risk).
        Negative SHAP → pushes prediction toward **non-default** (reduces risk).

        For the user-facing output we invert the sign perspective:
        * top_risk_factors   : features with the *most positive* SHAP values
          (they most increase P(default) → HIGH RISK drivers)
        * top_positive_factors : features with the *most negative* SHAP values
          (they most decrease P(default) → protective / LOW RISK signals)

        Falls back to a feature-importance approximation if SHAP is not
        installed, so ``score()`` never raises on a missing optional dep.
        """
        # ── Extract lgbm model and scaler from either format ──────────
        if isinstance(artefact_or_pipeline, dict):
            lgbm_model = artefact_or_pipeline.get("lgbm_for_shap")
            scaler     = artefact_or_pipeline.get("scaler")
            if lgbm_model is None or scaler is None:
                return self._shap_fallback(artefact_or_pipeline, feature_names)
            row_scaled_arr = scaler.transform(row_df.values.astype(np.float32))
        else:
            # Legacy Pipeline format
            lgbm_model = artefact_or_pipeline.named_steps["lgbm"]
            scaler     = artefact_or_pipeline.named_steps["scaler"]
            row_scaled_arr = scaler.transform(row_df)

        row_for_shap = pd.DataFrame(row_scaled_arr, columns=feature_names)

        try:
            import shap  # noqa: PLC0415
        except ImportError:
            logger.info(
                "shap not installed — SHAP explanations unavailable. "
                "Install with: pip install shap"
            )
            return self._shap_fallback(artefact_or_pipeline, feature_names)

        try:
            import warnings as _warnings  # noqa: PLC0415
            booster   = lgbm_model.booster_
            explainer = shap.TreeExplainer(booster)
            with _warnings.catch_warnings():
                _warnings.filterwarnings(
                    "ignore",
                    message="LightGBM binary classifier.*list of ndarray",
                    category=UserWarning,
                )
                shap_values = explainer.shap_values(row_for_shap)

            # shap_values shape depends on SHAP + LGBM version:
            # binary: (1, n_features) or list[(1,n_features), (1,n_features)]
            if isinstance(shap_values, list) and len(shap_values) == 2:
                sv = np.array(shap_values[1]).flatten()
            elif isinstance(shap_values, np.ndarray):
                if shap_values.ndim == 3:
                    sv = shap_values[0, :, 1]
                else:
                    sv = shap_values.flatten()
            else:
                sv = np.array(shap_values).flatten()

        except Exception as exc:  # noqa: BLE001
            logger.warning("SHAP TreeExplainer failed: %s — using fallback.", exc)
            return self._shap_fallback(artefact_or_pipeline, feature_names)

        # ── Top 3 risk drivers (most positive SHAP → highest P(default)) ──
        top_risk_idx = np.argsort(sv)[::-1][:3]
        top_risk_factors = [
            {
                "feature_name":       feature_names[i],
                "human_readable_name": _FEATURE_LABELS.get(
                    feature_names[i], feature_names[i].replace("_", " ").title()
                ),
                "shap_value":         round(float(sv[i]), 5),
                "direction":          "INCREASES_DEFAULT_RISK",
            }
            for i in top_risk_idx
        ]

        # ── Top 3 protective factors (most negative SHAP → lowers P(default)) ─
        top_pos_idx = np.argsort(sv)[:3]
        top_positive_factors = [
            {
                "feature_name":       feature_names[i],
                "human_readable_name": _FEATURE_LABELS.get(
                    feature_names[i], feature_names[i].replace("_", " ").title()
                ),
                "shap_value":         round(float(sv[i]), 5),
                "direction":          "DECREASES_DEFAULT_RISK",
            }
            for i in top_pos_idx
        ]

        return {
            "method":               "shap_tree_explainer",
            "top_risk_factors":     top_risk_factors,
            "top_positive_factors": top_positive_factors,
            "all_shap_values":      {
                feature_names[i]: round(float(sv[i]), 5)
                for i in range(len(feature_names))
            },
        }

    @staticmethod
    def _shap_fallback(
        artefact_or_pipeline: Any, feature_names: list[str]
    ) -> dict[str, Any]:
        """
        Return a feature-importance-based explanation when SHAP is absent.
        Uses LightGBM ``feature_importances_`` (gain-based).
        Handles both the new dict artefact format and the legacy Pipeline.
        """
        try:
            if isinstance(artefact_or_pipeline, dict):
                lgbm_model = artefact_or_pipeline.get("lgbm_for_shap")
            else:
                lgbm_model = artefact_or_pipeline.named_steps.get("lgbm")

            if lgbm_model is None:
                raise AttributeError("lgbm model not found")

            importances = lgbm_model.feature_importances_
            idx_sorted  = np.argsort(importances)[::-1]

            top_risk_factors = [
                {
                    "feature_name":       feature_names[i],
                    "human_readable_name": _FEATURE_LABELS.get(
                        feature_names[i],
                        feature_names[i].replace("_", " ").title(),
                    ),
                    "shap_value":         None,
                    "lgbm_importance":    round(float(importances[i]), 4),
                    "direction":          "HIGH_IMPORTANCE",
                }
                for i in idx_sorted[:3]
            ]
            return {
                "method":               "lgbm_feature_importance_fallback",
                "top_risk_factors":     top_risk_factors,
                "top_positive_factors": [],
                "note":                 "Install shap for full SHAP explanations.",
            }
        except Exception:  # noqa: BLE001
            return {
                "method":               "unavailable",
                "top_risk_factors":     [],
                "top_positive_factors": [],
                "note":                 "SHAP and feature-importance unavailable.",
            }


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------

def train_scorer(
    training_data_path: str | Path = "data/silver/training_data.csv",
    model_path: str | Path | None  = None,
) -> dict[str, Any]:
    """One-liner: instantiate CreditScorer, train, return metrics dict."""
    return CreditScorer(model_path=model_path).train(training_data_path)


def score_company(
    feature_vector: dict[str, float],
    model_path: str | Path | None = None,
) -> dict[str, Any]:
    """One-liner: load model and score a feature vector."""
    return CreditScorer(model_path=model_path).score(feature_vector)


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys as _sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    )

    action = _sys.argv[1] if len(_sys.argv) > 1 else "train-score"

    scorer = CreditScorer()

    if action in ("train", "train-score"):
        print("\n[1] Training CreditScorer …")
        results = scorer.train("data/silver/training_data.csv")
        print(f"    AUC-ROC : {results['auc']:.4f}")
        print(f"    Features: {results['feature_names']}")

    if action in ("score", "train-score"):
        print("\n[2] Scoring a representative HIGH-RISK profile …")
        high_risk_fv = {
            "debt_to_equity":            6.5,
            "current_ratio":             0.7,
            "dscr":                      0.6,
            "gst_health_score":          2.0,
            "itc_gap_pct":               40.0,
            "circular_trading_confidence": 0.85,
            "litigation_count":          7,
            "news_risk_score":           8.5,
            "has_wilful_default_flag":   1,
            "bounce_count":              6,
        }
        result = scorer.score(high_risk_fv)
        print(f"\n    default_probability : {result['default_probability']:.4f}")
        print(f"    risk_score          : {result['risk_score']:.4f}")
        print(f"    risk_band           : {result['risk_band']}")

        shap = result["shap_explanations"]
        print(f"\n    SHAP method         : {shap.get('method')}")
        print("    Top risk factors:")
        for f in shap.get("top_risk_factors", []):
            sv = f.get("shap_value")
            sv_str = f"{sv:.5f}" if sv is not None else "n/a"
            print(f"      • {f['human_readable_name']:<45} SHAP={sv_str}")
        print("    Top protective factors:")
        for f in shap.get("top_positive_factors", []):
            sv = f.get("shap_value")
            sv_str = f"{sv:.5f}" if sv is not None else "n/a"
            print(f"      • {f['human_readable_name']:<45} SHAP={sv_str}")

        print("\n[3] Applying qualitative adjustment (delta = -1.5) …")
        adjusted = scorer.apply_qualitative_adjustment(result, qualitative_delta=-1.5)
        print(f"    model risk_score     : {adjusted['model_risk_score_before_adj']:.4f}")
        print(f"    adjusted_risk_score  : {adjusted['adjusted_risk_score']:.4f}")
        print(f"    adjusted_risk_band   : {adjusted['adjusted_risk_band']}")
        print(f"\n    {adjusted['qualitative_adjustment_note']}")

    print()
