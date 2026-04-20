import logging

logger = logging.getLogger(__name__)


def _to_float(v, default=0.0):
    try:
        if v is None or v == "":
            return float(default)
        return float(v)
    except Exception:
        return float(default)


def _to_int(v, default=0):
    try:
        if v is None or v == "":
            return int(default)
        return int(v)
    except Exception:
        return int(default)


def _normalize_ministries(ministries_data):
    """
    Normalize raw ministry rows into a safe internal structure.

    Returns:
      rows: list[dict]
      all_ids: list[str]
    """
    rows = []
    all_ids = []

    for m in ministries_data or []:
        m_id = m.get("id")
        if m_id is None:
            continue

        mid = str(m_id)
        priority = _to_int(m.get("priority_score"), 0)
        min_req = max(0.0, _to_float(m.get("min_req"), 0.0))
        max_cap = max(0.0, _to_float(m.get("max_cap"), 0.0))  # 0 means no cap

        if max_cap > 0 and max_cap < min_req:
            max_cap = min_req

        rows.append({
            "id": mid,
            "priority_score": priority,
            "priority": priority,   # alias for LP path
            "min_req": min_req,
            "max_cap": max_cap,
            "cap": max_cap,         # alias for LP path
        })
        all_ids.append(mid)

    return rows, all_ids


def _zero_allocations_from_input(ministries_data):
    return {
        str(m.get("id")): 0.0
        for m in (ministries_data or [])
        if m.get("id") is not None
    }


def _build_optimizer_result(allocations, source, status):
    return {
        "allocations": allocations,
        "optimizer_source": source,
        "optimizer_status": status,
    }


def _priority_factor(priority_score, priority_boost=1.0):
    """
    Converts priority 1..10 into a multiplier.

    With priority_boost=1.0:
      priority 1  -> 1.0
      priority 10 -> 2.0
    """
    p = max(1, _to_int(priority_score, 1))
    boost = max(0.0, _to_float(priority_boost, 1.0))
    return 1.0 + boost * ((p - 1) / 9.0)


def _weighted_shortage_allocation(rows, available_pool, priority_boost=1.0, max_rounds=50):
    """
    Weighted shortage allocator for cases where available_pool < total minimums.

    Purpose:
      - Higher-priority ministries receive a larger share of the shortage pool
      - No ministry can receive more than its min_req in shortage mode
      - Total distributed amount stays within available_pool

    Weight basis:
      weight = min_req * priority_factor

    Returns:
      dict[str(ministry_id)] = allocation (rounded to 2dp)
    """
    available_pool = max(0.0, _to_float(available_pool, 0.0))
    if available_pool <= 0 or not rows:
        return {r["id"]: 0.0 for r in rows}

    # Prepare working structures
    out = {r["id"]: 0.0 for r in rows}
    caps = {r["id"]: max(0.0, _to_float(r.get("min_req"), 0.0)) for r in rows}
    weights = {}

    for r in rows:
        min_req = caps[r["id"]]
        priority = _to_int(r.get("priority"), r.get("priority_score", 1))
        factor = _priority_factor(priority, priority_boost=priority_boost)
        weights[r["id"]] = max(0.0, min_req * factor)

    remaining = available_pool
    rounds = 0
    eps = 1e-9

    while remaining > eps and rounds < max_rounds:
        rounds += 1

        eligible = [
            mid for mid in out.keys()
            if caps[mid] > out[mid] + eps
        ]
        if not eligible:
            break

        total_weight = sum(weights[mid] for mid in eligible)
        if total_weight <= eps:
            break

        distributed = 0.0
        overflow = 0.0

        for mid in eligible:
            share = remaining * (weights[mid] / total_weight)
            if share <= 0:
                continue

            room = max(0.0, caps[mid] - out[mid])
            give = min(share, room)

            out[mid] += give
            distributed += give
            overflow += (share - give)

        if distributed <= eps:
            break

        remaining = overflow if overflow > eps else 0.0

    # Final rounding
    for mid in list(out.keys()):
        val = out[mid]
        if val < 0 and abs(val) < eps:
            val = 0.0
        out[mid] = round(val, 2)

    return out


def optimize_budget_distribution(
    total_funds,
    ministries_data,
    *,
    max_rounds=50,
    shortage_priority_boost=1.0,
):
    """
    LEGACY allocator (keep for backward compatibility).

    Weighted proportional allocator with:
      1) Minimums first
      2) If minimums cannot all be met, shortage is shared using
         min_req + priority weighting
      3) Surplus distribution by priority
      4) Caps enforcement + overflow redistribution

    Returns:
      dict[str(ministry_id)] = allocation (float, 2dp)
    """
    total_funds = _to_float(total_funds, 0.0)
    if total_funds <= 0 or not ministries_data:
        return _zero_allocations_from_input(ministries_data)

    normalized, all_ids = _normalize_ministries(ministries_data)
    allocations = {mid: 0.0 for mid in all_ids}

    active = [m for m in normalized if m["priority_score"] > 0]
    if not active:
        return allocations

    total_min_req = sum(m["min_req"] for m in active)

    # If minimums alone exceed available funds, do weighted shortage sharing.
    if total_min_req > total_funds:
        shortage_alloc = _weighted_shortage_allocation(
            active,
            total_funds,
            priority_boost=shortage_priority_boost,
            max_rounds=max_rounds,
        )
        for mid, amt in shortage_alloc.items():
            allocations[mid] = amt
        return {k: round(v, 2) for k, v in allocations.items()}

    remaining = total_funds
    for m in active:
        allocations[m["id"]] = m["min_req"]
        remaining -= m["min_req"]

    if remaining <= 1e-9:
        return {k: round(v, 2) for k, v in allocations.items()}

    rounds = 0
    while remaining > 1e-9 and rounds < max_rounds:
        rounds += 1

        eligible = []
        for m in active:
            cap = m["max_cap"]
            current = allocations[m["id"]]

            if cap <= 0:
                eligible.append(m)
            elif current < cap - 1e-9:
                eligible.append(m)

        if not eligible:
            break

        total_points = sum(m["priority_score"] for m in eligible)
        if total_points <= 0:
            break

        overflow = 0.0
        distributed = 0.0

        for m in eligible:
            share = remaining * (m["priority_score"] / total_points)
            if share <= 0:
                continue

            cap = m["max_cap"]
            cur = allocations[m["id"]]

            if cap > 0:
                room = max(0.0, cap - cur)
                give = min(share, room)
                allocations[m["id"]] = cur + give
                distributed += give
                overflow += (share - give)
            else:
                allocations[m["id"]] = cur + share
                distributed += share

        if distributed <= 1e-9:
            break

        remaining = overflow if overflow > 1e-9 else 0.0

    out = {}
    for k, v in allocations.items():
        if v < 0 and abs(v) < 1e-9:
            v = 0.0
        out[k] = round(v, 2)

    if remaining > 0.01:
        logger.info("Unallocated funds due to caps/eligibility: %.2f", remaining)

    return out


# ============================================================
# AI PRESCRIPTIVE (Option 1): LP Multi-Objective + Constraints
# - SAFE: does not replace legacy; you call it explicitly.
# - Falls back to legacy if solver unavailable or errors.
# ============================================================

def optimize_budget_distribution_lp(
    total_funds,
    ministries_data,
    *,
    reserve_ratio=0.0,         # e.g. 0.10 keeps 10% unallocated
    w_priority=1.0,            # reward higher priority allocations
    w_fairness=0.15,           # penalize inequality range (max-min)
    w_stability=0.0,           # penalize deviation vs last allocations (optional)
    last_allocations=None,
    shortage_priority_boost=1.0,
):
    """
    LP-based prescriptive optimizer (multi-objective via weighted sum).

    Variables:
      x_i = allocation for ministry i

    Constraints:
      sum(x_i) <= pool_after_reserve
      x_i >= min_req_i (if active)
      x_i <= max_cap_i (if cap > 0)
      inactive (priority<=0) -> x_i = 0

    Objective (maximize):
      + w_priority * Σ(priority_i * x_i)
      - w_fairness * (max_x - min_x)
      - w_stability * Σ|x_i - last_i|   (if provided)

    IMPORTANT:
      If usable_pool is below total minimums, the function does not
      run LP. Instead, it applies weighted shortage sharing using
      minimum requirements and priority.

    Returns:
      {
        "allocations": dict[str(ministry_id)] = allocation (float, 2dp),
        "optimizer_source": "lp_solver" | "legacy_fallback",
        "optimizer_status": str
      }
    """
    total_funds = _to_float(total_funds, 0.0)
    if total_funds <= 0 or not ministries_data:
        return _build_optimizer_result(
            _zero_allocations_from_input(ministries_data),
            "lp_solver",
            "zero_or_empty_input",
        )

    reserve_ratio = max(0.0, min(1.0, _to_float(reserve_ratio, 0.0)))
    reserve = total_funds * reserve_ratio
    usable_pool = total_funds - reserve

    if usable_pool <= 1e-9:
        return _build_optimizer_result(
            _zero_allocations_from_input(ministries_data),
            "lp_solver",
            "reserve_consumed_pool",
        )

    rows, all_ids = _normalize_ministries(ministries_data)
    if not rows:
        return _build_optimizer_result({}, "lp_solver", "no_rows")

    active = [r for r in rows if r["priority"] > 0]
    if not active:
        return _build_optimizer_result(
            {mid: 0.0 for mid in all_ids},
            "lp_solver",
            "no_active_ministries",
        )

    # If minimums exceed pool, do weighted shortage sharing.
    total_min = sum(r["min_req"] for r in active)
    if total_min > usable_pool + 1e-9:
        out = {mid: 0.0 for mid in all_ids}
        shortage_alloc = _weighted_shortage_allocation(
            active,
            usable_pool,
            priority_boost=shortage_priority_boost,
        )
        for mid, amt in shortage_alloc.items():
            out[mid] = amt

        return _build_optimizer_result(
            out,
            "lp_solver",
            "weighted_prorated_minimums",
        )

    try:
        from ortools.linear_solver import pywraplp
    except Exception as e:
        logger.warning("OR-Tools not available, fallback to legacy. %s", e)
        return _build_optimizer_result(
            optimize_budget_distribution(
                total_funds,
                ministries_data,
                shortage_priority_boost=shortage_priority_boost,
            ),
            "legacy_fallback",
            "ortools_missing",
        )

    solver = pywraplp.Solver.CreateSolver("GLOP")
    if not solver:
        logger.warning("LP solver creation failed; fallback to legacy.")
        return _build_optimizer_result(
            optimize_budget_distribution(
                total_funds,
                ministries_data,
                shortage_priority_boost=shortage_priority_boost,
            ),
            "legacy_fallback",
            "solver_creation_failed",
        )

    # Variables x_i
    x = {}
    for r in rows:
        if r["priority"] <= 0:
            x[r["id"]] = solver.NumVar(0.0, 0.0, f"x_{r['id']}")
            continue

        lb = float(r["min_req"])
        ub = solver.infinity() if r["cap"] <= 0 else float(r["cap"])
        x[r["id"]] = solver.NumVar(lb, ub, f"x_{r['id']}")

    # Pool constraint
    solver.Add(sum(x[r["id"]] for r in rows) <= float(usable_pool))

    # Fairness range vars over ACTIVE only
    max_x = solver.NumVar(0.0, solver.infinity(), "max_x")
    min_x = solver.NumVar(0.0, solver.infinity(), "min_x")
    for r in active:
        solver.Add(x[r["id"]] <= max_x)
        solver.Add(x[r["id"]] >= min_x)

    # Stability |x_i - last_i|
    abs_dev = {}
    last_allocations = last_allocations or {}
    use_stability = _to_float(w_stability, 0.0) > 0.0 and isinstance(last_allocations, dict)

    if use_stability:
        for r in active:
            last = _to_float(last_allocations.get(r["id"], 0.0), 0.0)
            d = solver.NumVar(0.0, solver.infinity(), f"dev_{r['id']}")
            abs_dev[r["id"]] = d
            solver.Add(d >= x[r["id"]] - last)
            solver.Add(d >= last - x[r["id"]])

    # Objective: maximize priority reward - fairness penalty - stability penalty
    obj = solver.Objective()
    w_priority = _to_float(w_priority, 1.0)
    w_fairness = _to_float(w_fairness, 0.0)
    w_stability = _to_float(w_stability, 0.0)

    for r in active:
        obj.SetCoefficient(x[r["id"]], w_priority * float(r["priority"]))

    # -(max-min) = -max + min
    obj.SetCoefficient(max_x, -w_fairness)
    obj.SetCoefficient(min_x, +w_fairness)

    for _, d in abs_dev.items():
        obj.SetCoefficient(d, -w_stability)

    obj.SetMaximization()

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL:
        logger.warning("LP not optimal (status=%s), fallback to legacy.", status)
        return _build_optimizer_result(
            optimize_budget_distribution(
                total_funds,
                ministries_data,
                shortage_priority_boost=shortage_priority_boost,
            ),
            "legacy_fallback",
            f"lp_status_{status}",
        )

    out = {}
    for mid in all_ids:
        val = max(0.0, x[mid].solution_value())
        if val < 1e-9:
            val = 0.0
        out[mid] = round(val, 2)

    return _build_optimizer_result(out, "lp_solver", "optimal")


def optimize_budget_distribution_ai(total_funds, ministries_data, **kwargs):
    """
    Safe wrapper:
      - Prefer AI LP optimizer
      - Always fall back to legacy allocator

    Returns:
      {
        "allocations": dict,
        "optimizer_source": str,
        "optimizer_status": str,
      }
    """
    try:
        return optimize_budget_distribution_lp(total_funds, ministries_data, **kwargs)
    except Exception as e:
        logger.exception("AI optimizer failed; using legacy allocator. %s", e)
        return _build_optimizer_result(
            optimize_budget_distribution(
                total_funds,
                ministries_data,
                shortage_priority_boost=kwargs.get("shortage_priority_boost", 1.0),
            ),
            "legacy_fallback",
            "exception_fallback",
        )