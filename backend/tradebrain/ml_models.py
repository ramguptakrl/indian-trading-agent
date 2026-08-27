"""Deterministic baseline model family for Trade Brain v0.14 ML.

Research-only classifiers: no broker, order, account, or policy mutation capability.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

METHOD_VERSION = "BSE_ML_MODELS_V1"
DEFAULT_RANDOM_STATE = 1729
MODEL_LOGISTIC = "LOGISTIC_REGRESSION"
MODEL_DECISION_TREE = "DECISION_TREE"
MODEL_RANDOM_FOREST = "RANDOM_FOREST"
MODEL_EXTRA_TREES = "EXTRA_TREES"
MODEL_HIST_GRADIENT_BOOSTING = "HIST_GRADIENT_BOOSTING"
MODEL_FAMILIES = (MODEL_LOGISTIC, MODEL_DECISION_TREE, MODEL_RANDOM_FOREST, MODEL_EXTRA_TREES, MODEL_HIST_GRADIENT_BOOSTING)

@dataclass(frozen=True)
class ModelSpec:
    family: str
    params: dict[str, Any]
    def validate(self) -> None:
        if self.family not in MODEL_FAMILIES:
            raise ValueError(f"Unsupported ML model family: {self.family}")

def feature_schema_hash(feature_columns: Iterable[str]) -> str:
    columns = [str(value) for value in feature_columns]
    if len(columns) != len(set(columns)):
        raise ValueError("Feature columns must be unique")
    return hashlib.sha256(json.dumps(columns, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()

def default_model_specs() -> tuple[ModelSpec, ...]:
    return (
        ModelSpec(MODEL_LOGISTIC, {"C": 0.5}),
        ModelSpec(MODEL_LOGISTIC, {"C": 1.0}),
        ModelSpec(MODEL_DECISION_TREE, {"max_depth": 4, "min_samples_leaf": 20}),
        ModelSpec(MODEL_DECISION_TREE, {"max_depth": 7, "min_samples_leaf": 12}),
        ModelSpec(MODEL_RANDOM_FOREST, {"n_estimators": 160, "max_depth": 7, "min_samples_leaf": 10}),
        ModelSpec(MODEL_RANDOM_FOREST, {"n_estimators": 220, "max_depth": 10, "min_samples_leaf": 8}),
        ModelSpec(MODEL_EXTRA_TREES, {"n_estimators": 160, "max_depth": 7, "min_samples_leaf": 10}),
        ModelSpec(MODEL_EXTRA_TREES, {"n_estimators": 220, "max_depth": 10, "min_samples_leaf": 8}),
        ModelSpec(MODEL_HIST_GRADIENT_BOOSTING, {"learning_rate": 0.05, "max_iter": 140, "max_leaf_nodes": 15, "l2_regularization": 1.0}),
        ModelSpec(MODEL_HIST_GRADIENT_BOOSTING, {"learning_rate": 0.04, "max_iter": 200, "max_leaf_nodes": 31, "l2_regularization": 2.0}),
    )

def _model_for(spec: ModelSpec, *, random_state: int) -> Any:
    spec.validate(); p = dict(spec.params)
    if spec.family == MODEL_LOGISTIC:
        return LogisticRegression(C=float(p.get("C", 1.0)), class_weight="balanced", max_iter=2500, random_state=random_state, solver="lbfgs")
    if spec.family == MODEL_DECISION_TREE:
        return DecisionTreeClassifier(max_depth=int(p.get("max_depth", 6)), min_samples_leaf=int(p.get("min_samples_leaf", 12)), class_weight="balanced", random_state=random_state)
    if spec.family == MODEL_RANDOM_FOREST:
        return RandomForestClassifier(n_estimators=int(p.get("n_estimators", 180)), max_depth=int(p.get("max_depth", 8)), min_samples_leaf=int(p.get("min_samples_leaf", 10)), class_weight="balanced_subsample", random_state=random_state, n_jobs=1)
    if spec.family == MODEL_EXTRA_TREES:
        return ExtraTreesClassifier(n_estimators=int(p.get("n_estimators", 180)), max_depth=int(p.get("max_depth", 8)), min_samples_leaf=int(p.get("min_samples_leaf", 10)), class_weight="balanced", random_state=random_state, n_jobs=1)
    if spec.family == MODEL_HIST_GRADIENT_BOOSTING:
        return HistGradientBoostingClassifier(learning_rate=float(p.get("learning_rate", 0.05)), max_iter=int(p.get("max_iter", 160)), max_leaf_nodes=int(p.get("max_leaf_nodes", 15)), l2_regularization=float(p.get("l2_regularization", 1.0)), random_state=random_state)
    raise ValueError(f"Unsupported ML model family: {spec.family}")

def build_model(spec: ModelSpec, *, random_state: int = DEFAULT_RANDOM_STATE) -> Pipeline:
    steps: list[tuple[str, Any]] = [("imputer", SimpleImputer(strategy="median"))]
    if spec.family == MODEL_LOGISTIC:
        steps.append(("scaler", StandardScaler()))
    steps.append(("model", _model_for(spec, random_state=random_state)))
    return Pipeline(steps)

def _numeric_matrix(frame: pd.DataFrame, feature_columns: Iterable[str]) -> pd.DataFrame:
    columns = tuple(str(value) for value in feature_columns)
    missing = [name for name in columns if name not in frame.columns]
    if missing:
        raise ValueError(f"Feature frame missing columns: {missing[:12]}")
    work = frame.loc[:, list(columns)].copy()
    for column in columns:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    return work

def fit_model(frame: pd.DataFrame, *, feature_columns: Iterable[str], spec: ModelSpec, target_column: str = "label_net_positive", random_state: int = DEFAULT_RANDOM_STATE) -> Pipeline:
    if target_column not in frame.columns:
        raise ValueError(f"Training frame missing target column: {target_column}")
    y = pd.to_numeric(frame[target_column], errors="raise").astype(int).to_numpy()
    if len(frame) < 20:
        raise ValueError("At least 20 chronological training rows are required")
    if set(y.tolist()) != {0, 1}:
        raise ValueError("Training labels must contain both positive and negative outcomes")
    model = build_model(spec, random_state=random_state)
    model.fit(_numeric_matrix(frame, feature_columns), y)
    return model

def predict_positive_probability(model: Pipeline, frame: pd.DataFrame, *, feature_columns: Iterable[str]) -> np.ndarray:
    values = model.predict_proba(_numeric_matrix(frame, feature_columns)); classes = list(model.classes_)
    if 1 not in classes:
        raise ValueError("Model does not expose positive class probability")
    return np.asarray(values[:, classes.index(1)], dtype=float)

def feature_importance(model: Pipeline, feature_columns: Iterable[str]) -> list[dict[str, float | str]]:
    columns = list(feature_columns); estimator = model.named_steps["model"]; raw = getattr(estimator, "feature_importances_", None)
    if raw is None and hasattr(estimator, "coef_"):
        raw = np.abs(np.asarray(estimator.coef_)[0])
    if raw is None or len(raw) != len(columns):
        return []
    values = np.asarray(raw, dtype=float); denom = float(np.sum(np.abs(values))) or 1.0
    return sorted(({"feature": name, "importance": float(abs(value) / denom)} for name, value in zip(columns, values)), key=lambda item: item["importance"], reverse=True)
