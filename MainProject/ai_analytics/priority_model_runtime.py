import os
import joblib

BASE_DIR = os.path.dirname(__file__)
MODEL_PATH = os.path.join(BASE_DIR, "priority_model.joblib")

_bundle_cache = None

def load_bundle():
    global _bundle_cache
    if _bundle_cache is not None:
        return _bundle_cache
    if not os.path.exists(MODEL_PATH):
        return None
    try:
        _bundle_cache = joblib.load(MODEL_PATH)
        return _bundle_cache
    except Exception:
        return None

def clamp_1_10(v, default=5):
    try:
        v = int(round(float(v)))
    except Exception:
        return default
    return max(1, min(10, v))

def _expected_n_features(model):
    """
    Works for plain estimators and (most) sklearn Pipelines.
    """
    n = getattr(model, "n_features_in_", None)
    if n is not None:
        return int(n)

    # Pipeline fallback
    try:
        if hasattr(model, "named_steps"):
            # try common last-step names
            for key in ("model", "estimator", "clf", "regressor"):
                step = model.named_steps.get(key)
                if step is not None and hasattr(step, "n_features_in_"):
                    return int(step.n_features_in_)
            # else last step
            last = list(model.named_steps.values())[-1]
            if hasattr(last, "n_features_in_"):
                return int(last.n_features_in_)
    except Exception:
        pass

    return None

def _coerce_feature_vector(features, expected_n):
    """
    Ensures a numeric list of length expected_n.
    Pads with 0.0 or truncates as needed.
    """
    # normalize to list
    if features is None:
        feats = []
    elif isinstance(features, (list, tuple)):
        feats = list(features)
    else:
        feats = [features]

    # coerce numerics safely
    out = []
    for v in feats:
        try:
            out.append(float(v))
        except Exception:
            out.append(0.0)

    if expected_n is None:
        return out

    if len(out) < expected_n:
        out.extend([0.0] * (expected_n - len(out)))
    elif len(out) > expected_n:
        out = out[:expected_n]

    return out

def predict_priority(features):
    """
    Backward/forward compatible predictor.

    You *intended* feature order:
      ["pool_used_monthly", "mode_is_historical", "ui_is_monthly", "min_req", "max_cap"]

    If the stored model expects a different feature count (e.g., 7),
    this function will pad/truncate so prediction won't crash.
    """
    bundle = load_bundle()
    if not bundle:
        return None

    model = bundle.get("model")
    if model is None:
        return None

    expected_n = _expected_n_features(model)
    feats = _coerce_feature_vector(features, expected_n)

    # Optional debug (swap with logging if preferred)
    # if expected_n is not None and len(features) != expected_n:
    #     print(f"[predict_priority] feature mismatch: got {len(features)} expected {expected_n}; coerced={feats}")

    try:
        pred = model.predict([feats])[0]
    except Exception:
        return None

    return clamp_1_10(pred)