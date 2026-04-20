import os
import joblib
import numpy as np
from datetime import timedelta
from decimal import Decimal

from django.apps import apps
from django.core.management.base import BaseCommand
from django.db.models import Sum, Max
from django.db.models.functions import Coalesce

from ai_analytics.models import OptimizerRunLog

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # ai_analytics/
MODEL_DIR = os.path.join(BASE_DIR, "models")
MODEL_PATH = os.path.join(MODEL_DIR, "priority_model.joblib")


def _safe_float(x, default=0.0):
    try:
        if x is None or x == "":
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def clamp_1_10(v):
    try:
        v = int(round(float(v)))
    except Exception:
        v = 5
    return max(1, min(10, v))


def _net_spent_ytd_until(ReleasedBudget, church_id, ministry_id, cutoff_date):
    """
    Net spent YTD up to cutoff_date:
      released YTD - returned YTD
    """
    year_start = cutoff_date.replace(month=1, day=1)

    released = (
        ReleasedBudget.objects.filter(
            church_id=church_id,
            ministry_id=ministry_id,
            date_released__gte=year_start,
            date_released__lte=cutoff_date,
        ).aggregate(t=Coalesce(Sum("amount"), Decimal("0.00")))["t"]
    )

    returned = (
        ReleasedBudget.objects.filter(
            church_id=church_id,
            ministry_id=ministry_id,
            is_liquidated=True,
            liquidated_date__isnull=False,
            liquidated_date__gte=year_start,
            liquidated_date__lte=cutoff_date,
        ).aggregate(t=Coalesce(Sum("amount_returned"), Decimal("0.00")))["t"]
    )

    net = _safe_float(released, 0.0) - _safe_float(returned, 0.0)
    return max(0.0, net)


def _future_priority_label(future_released, future_returned, min_req):
    """
    Build a 1..10 target score from FUTURE ministry behavior.

    Signals:
    - utilization: how much of released money was actually used
    - need_vs_min: how much future net use reached/exceeded the ministry's min requirement
    """
    future_released = max(0.0, _safe_float(future_released, 0.0))
    future_returned = max(0.0, _safe_float(future_returned, 0.0))
    min_req = max(0.0, _safe_float(min_req, 0.0))

    net_used = max(0.0, future_released - future_returned)

    utilization = (net_used / future_released) if future_released > 0 else 0.0

    if min_req > 0:
        need_vs_min = min(1.0, net_used / min_req)
    else:
        need_vs_min = 1.0 if net_used > 0 else 0.0

    activity = 1.0 if future_released > 0 else 0.0

    composite = (0.60 * utilization) + (0.30 * need_vs_min) + (0.10 * activity)

    score = 1 + (9 * composite)
    return clamp_1_10(score)


class Command(BaseCommand):
    help = "Train priority model from OptimizerRunLog using future ministry outcomes (6-feature version with spent_ytd)."

    def add_arguments(self, parser):
        parser.add_argument("--church_id", type=int, required=True)
        parser.add_argument("--min_rows", type=int, default=50)
        parser.add_argument("--horizon_days", type=int, default=90)

    def handle(self, *args, **opts):
        church_id = opts["church_id"]
        min_rows = opts["min_rows"]
        horizon_days = opts["horizon_days"]

        ReleasedBudget = apps.get_model("Register", "ReleasedBudget")
        if ReleasedBudget is None:
            self.stdout.write(self.style.ERROR("ReleasedBudget model not found."))
            return

        logs = list(
            OptimizerRunLog.objects
            .filter(church_id=church_id)
            .order_by("created_at")
        )
        if not logs:
            self.stdout.write(self.style.ERROR("No optimizer logs found for that church_id."))
            return

        # Latest observable date in financial activity
        latest_release = (
            ReleasedBudget.objects
            .filter(church_id=church_id)
            .aggregate(d=Max("date_released"))["d"]
        )
        latest_liquidation = (
            ReleasedBudget.objects
            .filter(church_id=church_id, liquidated_date__isnull=False)
            .aggregate(d=Max("liquidated_date"))["d"]
        )

        latest_observed_date = max(
            [d for d in [latest_release, latest_liquidation] if d is not None],
            default=None
        )

        if latest_observed_date is None:
            self.stdout.write(
                self.style.ERROR(
                    "No ReleasedBudget history found. Cannot build future-outcome labels yet."
                )
            )
            return

        samples = []
        outcome_cache = {}
        spent_ytd_cache = {}

        for log in logs:
            log_date = log.created_at.date()
            window_start = log_date
            window_end = log_date + timedelta(days=horizon_days)

            # Skip logs that do not yet have a full future observation window
            if window_end > latest_observed_date:
                continue

            pool = _safe_float(log.pool_used_monthly, 0.0)
            mode_is_historical = 1.0 if (log.mode or "").lower() == "historical" else 0.0
            ui_is_monthly = 1.0 if (log.timeframe or "").lower() == "monthly" else 0.0

            constraints = log.ministry_constraints or {}
            if not isinstance(constraints, dict):
                continue

            for mid, c in constraints.items():
                mid_str = str(mid)
                try:
                    ministry_id = int(mid_str)
                except Exception:
                    continue

                min_req = _safe_float((c or {}).get("min_req"), 0.0)
                max_cap = _safe_float((c or {}).get("max_cap"), 0.0)

                spent_cache_key = (church_id, ministry_id, log_date)
                if spent_cache_key not in spent_ytd_cache:
                    spent_ytd_cache[spent_cache_key] = _net_spent_ytd_until(
                        ReleasedBudget=ReleasedBudget,
                        church_id=church_id,
                        ministry_id=ministry_id,
                        cutoff_date=log_date,
                    )

                spent_ytd = spent_ytd_cache[spent_cache_key]

                # Features available at prediction time
                feats = [
                    pool,               # pool_used_monthly
                    mode_is_historical, # 1 if historical, else 0
                    ui_is_monthly,      # 1 if monthly UI, else 0
                    min_req,            # min requirement (monthly)
                    max_cap,            # max cap (monthly)
                    spent_ytd,          # net spent YTD up to decision date
                ]

                outcome_cache_key = (church_id, ministry_id, window_start, window_end)
                if outcome_cache_key not in outcome_cache:
                    future_released = (
                        ReleasedBudget.objects
                        .filter(
                            church_id=church_id,
                            ministry_id=ministry_id,
                            date_released__gt=window_start,
                            date_released__lte=window_end,
                        )
                        .aggregate(t=Coalesce(Sum("amount"), Decimal("0.00")))["t"]
                    )

                    future_returned = (
                        ReleasedBudget.objects
                        .filter(
                            church_id=church_id,
                            ministry_id=ministry_id,
                            is_liquidated=True,
                            liquidated_date__isnull=False,
                            liquidated_date__gt=window_start,
                            liquidated_date__lte=window_end,
                        )
                        .aggregate(t=Coalesce(Sum("amount_returned"), Decimal("0.00")))["t"]
                    )

                    outcome_cache[outcome_cache_key] = (
                        _safe_float(future_released, 0.0),
                        _safe_float(future_returned, 0.0),
                    )

                future_released, future_returned = outcome_cache[outcome_cache_key]
                label = _future_priority_label(
                    future_released=future_released,
                    future_returned=future_returned,
                    min_req=min_req,
                )

                samples.append({
                    "x": feats,
                    "y": float(label),
                    "t": log.created_at,
                })

        n = len(samples)
        if n < min_rows:
            self.stdout.write(
                self.style.ERROR(
                    f"Not enough training rows with complete future windows: {n} < {min_rows}"
                )
            )
            return

        # Time-based split: train on older samples, test on newer samples
        samples.sort(key=lambda s: s["t"])
        split_idx = max(1, int(n * 0.8))
        if split_idx >= n:
            split_idx = n - 1

        train_samples = samples[:split_idx]
        test_samples = samples[split_idx:]

        X_train = np.array([s["x"] for s in train_samples], dtype=float)
        y_train = np.array([s["y"] for s in train_samples], dtype=float)

        X_test = np.array([s["x"] for s in test_samples], dtype=float)
        y_test = np.array([s["y"] for s in test_samples], dtype=float)

        model = RandomForestRegressor(
            n_estimators=400,
            random_state=42,
            min_samples_leaf=2,
            n_jobs=-1,
        )
        model.fit(X_train, y_train)

        preds = model.predict(X_test)
        mae = mean_absolute_error(y_test, preds)
        r2 = r2_score(y_test, preds)

        os.makedirs(MODEL_DIR, exist_ok=True)
        joblib.dump(
            {
                "model": model,
                "church_id": church_id,
                "feature_order": [
                    "pool_used_monthly",
                    "mode_is_historical",
                    "ui_is_monthly",
                    "min_req",
                    "max_cap",
                    "spent_ytd",
                ],
                "feature_count": 6,
                "model_version": "priority_rf_future_outcome_v2_spent_ytd",
                "label_source": f"future_{horizon_days}d_release_return_behavior",
                "train_rows": len(train_samples),
                "test_rows": len(test_samples),
            },
            MODEL_PATH,
        )

        self.stdout.write(self.style.SUCCESS(f"Model saved to: {MODEL_PATH}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Samples: total={n}, train={len(train_samples)}, test={len(test_samples)}"
            )
        )
        self.stdout.write(self.style.SUCCESS(f"Test MAE: {mae:.3f}"))
        self.stdout.write(self.style.SUCCESS(f"Test R^2: {r2:.3f}"))