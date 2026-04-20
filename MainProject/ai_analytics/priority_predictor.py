import os
import joblib
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(__file__)
MODEL_DIR = os.path.join(BASE_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "priority_model.joblib")

_bundle_cache = None


def load_bundle():
    global _bundle_cache
    if _bundle_cache is not None:
        return _bundle_cache

    if not os.path.exists(MODEL_PATH):
        logger.error("Priority model file not found: %s", MODEL_PATH)
        return None

    try:
        _bundle_cache = joblib.load(MODEL_PATH)
        return _bundle_cache
    except Exception as e:
        logger.exception("Failed to load priority model: %s", e)
        return None


def clamp_1_10(v, default=5):
    try:
        v = int(round(float(v)))
    except Exception:
        return default
    return max(1, min(10, v))


def predict_priority(features: List[float], church_id: Optional[int] = None) -> Optional[int]:
    """
    Predict priority score using the trained model.

    Expected feature order:
      [
        pool_used_monthly,
        mode_is_historical,
        ui_is_monthly,
        min_req,
        max_cap,
        spent_ytd,
      ]
    """
    bundle = load_bundle()
    if not bundle:
        return None

    model = bundle.get("model")
    if model is None:
        logger.error("Priority model bundle has no 'model' key.")
        return None

    feature_order = bundle.get("feature_order", [])

    # Safer fallback chain:
    # 1) explicit feature_count from bundle
    # 2) len(feature_order)
    # 3) sklearn model n_features_in_
    # 4) final fallback = 6
    expected_count = bundle.get("feature_count")
    if expected_count is None:
        if isinstance(feature_order, list) and feature_order:
            expected_count = len(feature_order)
        else:
            expected_count = getattr(model, "n_features_in_", 6)

    try:
        expected_count = int(expected_count)
    except Exception:
        expected_count = 6

    model_church_id = bundle.get("church_id")

    if church_id is not None and model_church_id is not None:
        try:
            if int(model_church_id) != int(church_id):
                logger.error(
                    "Priority model church mismatch. model=%s request=%s",
                    model_church_id, church_id
                )
                return None
        except Exception:
            logger.error(
                "Invalid church_id comparison. model=%s request=%s",
                model_church_id, church_id
            )
            return None

    if not isinstance(features, (list, tuple)):
        logger.error("Features must be a list or tuple. Got: %s", type(features))
        return None

    if len(features) != expected_count:
        logger.error(
            "Feature count mismatch. got=%s expected=%s order=%s",
            len(features), expected_count, feature_order
        )
        return None

    try:
        feats = [float(x) for x in features]
    except Exception as e:
        logger.exception("Failed to coerce features to float: %s", e)
        return None

    try:
        pred = model.predict([feats])[0]
        return clamp_1_10(pred)
    except Exception as e:
        logger.exception("Priority prediction failed: %s", e)
        return None