from __future__ import annotations

import json
from django.conf import settings
from openai import OpenAI


def build_budget_insights(summary: dict, scope_label: str) -> dict | None:
    """
    Uses OpenAI only for explanation/insight generation.
    Your Django analytics remains the source of truth.
    """
    api_key = getattr(settings, "OPENAI_API_KEY", None)
    if not api_key:
        return None

    client = OpenAI(api_key=api_key)

    ministries = summary.get("ministries", [])

    compact_payload = {
        "scope": scope_label,
        "totals": {
            "allocated_total": float(summary.get("allocated_total", 0) or 0),
            "released_total": float(summary.get("released_total", 0) or 0),
            "returned_total": float(summary.get("returned_total", 0) or 0),
            "spent_total": float(summary.get("spent_total", 0) or 0),
            "unliquidated_total": float(summary.get("unliquidated_total", 0) or 0),
            "available_total": float(summary.get("available_total", 0) or 0),
            "utilization_pct": float(summary.get("utilization_pct", 0) or 0),
            "burn_rate_monthly_avg": float(summary.get("burn_rate_monthly_avg", 0) or 0),
            "projected_year_end_spend": float(summary.get("projected_year_end_spend", 0) or 0),
            "ministry_count": int(summary.get("ministry_count", 0) or 0),
        },
        "ministries": [
            {
                "ministry_name": row.get("ministry_name"),
                "structure_type": row.get("structure_type"),
                "allocated_total": float(row.get("allocated_total", 0) or 0),
                "released_total": float(row.get("released_total", 0) or 0),
                "returned_total": float(row.get("returned_total", 0) or 0),
                "spent_total": float(row.get("spent_total", 0) or 0),
                "unliquidated_total": float(row.get("unliquidated_total", 0) or 0),
                "available_total": float(row.get("available_total", 0) or 0),
                "utilization_pct": float(row.get("utilization_pct", 0) or 0),
                "burn_rate_monthly_avg": float(row.get("burn_rate_monthly_avg", 0) or 0),
                "projected_year_end_spend": float(row.get("projected_year_end_spend", 0) or 0),
                "highest_spending_month": (
                    row.get("highest_spending_month", {}).get("month")
                    if row.get("highest_spending_month")
                    else None
                ),
                "category_mix": [
                    {
                        "category": c.get("category"),
                        "amount": float(c.get("amount", 0) or 0),
                        "percent": float(c.get("percent", 0) or 0),
                    }
                    for c in row.get("category_mix", [])[:5]
                ],
            }
            for row in ministries[:20]
        ],
    }

    prompt = (
        "Analyze this church budget report. "
        "Use only the provided data. "
        "Do not invent figures or causes not supported by the data. "
        "Write practical management insights for church leaders. "
        "Keep the tone concise and professional.\n\n"
        f"{json.dumps(compact_payload, ensure_ascii=False)}"
    )

    response = client.responses.create(
        model="gpt-5-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "You are a church finance analysis assistant. "
                    "You summarize trends, identify risks, and suggest practical actions. "
                    "Never fabricate numbers or unsupported explanations."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "budget_insights",
                "schema": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "forecast_note": {"type": "string"},
                        "risks": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "recommendations": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["summary", "forecast_note", "risks", "recommendations"],
                    "additionalProperties": False,
                },
            }
        },
    )

    # SDKs may expose parsed structured output differently depending on version.
    if hasattr(response, "output_parsed") and response.output_parsed:
        return response.output_parsed

    try:
        return json.loads(response.output_text)
    except Exception:
        return {
            "summary": response.output_text or "",
            "forecast_note": "",
            "risks": [],
            "recommendations": [],
        }