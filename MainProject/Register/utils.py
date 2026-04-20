import base64
import json
import re
from django.conf import settings
from django.db import connection
from django.db.models import Sum
from django.db.models.functions import TruncMonth, Coalesce
from datetime import date, timedelta
from dateutil import parser  # pip install python-dateutil
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from openai import OpenAI

from .models import Ministry, Tithe, Offering, Donations, OtherIncome, Expense, MinistryBudget

client = OpenAI(api_key=settings.OPENAI_API_KEY)

# ==========================================
# PART 1: AI & OPENAI HELPERS
# ==========================================
def get_fitz():
    """Lazy import of pymupdf — only loaded when a PDF is actually processed."""
    import pymupdf as fitz
    return fitz


def clean_date_format(date_str):
    if not date_str:
        return ""
    try:
        dt = parser.parse(str(date_str))
        return dt.strftime('%Y-%m-%d')
    except (ValueError, TypeError):
        return ""


def clean_account_number(number_str):
    if not number_str:
        return ""
    s = str(number_str).upper()
    for word in ["SA", "SAVINGS", "ACCT", "ACCOUNT", "NO", "NUMBER", ":", "-"]:
        s = s.replace(word, "")
    return re.sub(r'\D', '', s)


def prepare_file_for_gpt(image_file):
    try:
        filename = getattr(image_file, "name", "").lower()

        if hasattr(image_file, "seek"):
            image_file.seek(0)

        file_bytes = image_file.read()
        mime_type = "image/jpeg"

        if filename.endswith(".pdf") or (file_bytes[:4] == b"%PDF"):
            try:
                fitz = get_fitz()
                with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                    if doc.page_count < 1:
                        return None, None, "Uploaded PDF is empty."

                    page = doc.load_page(0)
                    pix = page.get_pixmap(dpi=200)
                    file_bytes = pix.tobytes("png")
                    mime_type = "image/png"
            except Exception as e:
                return None, None, f"PDF Error: {str(e)}"

        base64_image = base64.b64encode(file_bytes).decode("utf-8")

        # ✅ IMPORTANT: reset pointer so the same uploaded file can be saved later
        if hasattr(image_file, "seek"):
            try:
                image_file.seek(0)
            except Exception:
                pass

        return base64_image, mime_type, None

    except Exception as e:
        return None, None, f"File Processing Error: {str(e)}"


def analyze_receipt_with_openai(image_file):
    try:
        base64_image, mime_type, error = prepare_file_for_gpt(image_file)
        if error:
            return {"error": error}

        system_instruction = (
            "You are an expert accountant. Extract data from this receipt image.\n"
            "Rules:\n"
            "1. DATE: Find the transaction date (Format YYYY-MM-DD).\n"
            "2. AMOUNT: Find the GRAND TOTAL.\n"
            "3. DESCRIPTION: Summarize vendor and items.\n"
            "Return JSON only: { \"date\": \"string\", \"amount\": number, \"description\": \"string\" }"
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extract details."},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]}
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )

        content = response.choices[0].message.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        return {
            "date": clean_date_format(data.get('date')),
            "amount": data.get('amount', 0.0),
            "description": data.get('description', '')
        }

    except Exception as e:
        print(f"OpenAI Analysis Error: {e}")
        return {"error": str(e)}


def _money_to_decimal(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None

    s = s.replace("₱", "").replace("PHP", "").replace("php", "").strip()
    s = s.replace(",", "")  # remove thousand separators

    try:
        return Decimal(s).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def verify_receipt_with_openai(image_file, check_type="TRANSACTION", expected_data=None):
    """
    Backwards-compatible verifier with optional STRICT flags.

    expected_data can include:
      - amount (required for TRANSACTION)
      - date (optional)
      - account_number (optional)
      - context (optional, for Version 2)
      - amount_tolerance (optional) default:
            - strict_amount False -> 5.00
            - strict_amount True  -> 0.00
      - strict_amount: bool (default False)  ✅ USE TRUE for bank movement
      - strict_date: bool (default False)
    """
    try:
        expected_data = expected_data or {}

        base64_image, mime_type, error = prepare_file_for_gpt(image_file)
        if error:
            return False, error

        strict_amount = bool(expected_data.get("strict_amount", False))
        strict_date = bool(expected_data.get("strict_date", False))

        # tolerance defaults: legacy 5.00, strict 0.00
        default_tol = "0.00" if strict_amount else "5.00"
        tolerance = _money_to_decimal(expected_data.get("amount_tolerance", default_tol)) or Decimal(default_tol)

        expected_amount = _money_to_decimal(expected_data.get("amount"))
        expected_date = clean_date_format(expected_data.get("date"))
        expected_acct = clean_account_number(expected_data.get("account_number", ""))

        # ---- Extraction prompt (still similar to your old style)
        context = expected_data.get("context") or {}
        user_prompt = (
            "Analyze this banking document and extract the main transaction details.\n"
            "Return JSON only with keys:\n"
            "{\n"
            '  "found_amount": "string or number",\n'
            '  "found_date": "string (any format)",\n'
            '  "found_account_no": "string"\n'
            "}\n"
            "Rules:\n"
            "- found_amount should be the primary transaction amount shown.\n"
            "- found_date should be the transaction date if present.\n"
            "- found_account_no should be any account number found (partial ok).\n"
        )
        if context:
            user_prompt += "\nContext (may help disambiguation): " + json.dumps(context, ensure_ascii=False)

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a strict extraction auditor. Return JSON only."},
                {"role": "user", "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]}
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )

        content = (response.choices[0].message.content or "").replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        found_amount = _money_to_decimal(data.get("found_amount"))
        found_date = clean_date_format(data.get("found_date"))
        found_acct = clean_account_number(data.get("found_account_no", ""))

        # =========================================================
        # 1) AMOUNT CHECK (TRANSACTION)
        # =========================================================
        if check_type == "TRANSACTION":
            if expected_amount is None:
                return False, "Expected amount is missing/invalid."

            # STRICT: require readable amount
            if strict_amount and (found_amount is None):
                return False, "Could not read a clear amount from the proof image."

            # Legacy: only check mismatch if we actually found an amount
            if found_amount is not None:
                diff = abs(found_amount - expected_amount)
                if diff > tolerance:
                    return False, (
                        f"Amount Mismatch. Document shows ₱{found_amount:.2f}, "
                        f"expected ₱{expected_amount:.2f} (diff ₱{diff:.2f})."
                    )

        # =========================================================
        # 2) DATE CHECK (optional)
        # =========================================================
        if expected_date:
            if strict_date and not found_date:
                return False, f"Could not read a clear date from the proof image (expected {expected_date})."
            if found_date and found_date != expected_date:
                if strict_date:
                    return False, f"Date Mismatch. Document shows {found_date}, expected {expected_date}."

        # =========================================================
        # 3) ACCOUNT CHECK
        # =========================================================
        if expected_acct:
            if not found_acct:
                if check_type == "IDENTITY":
                    return False, "Could not find a clear Account Number in the image."
            else:
                exp_last4 = expected_acct[-4:] if len(expected_acct) >= 4 else expected_acct
                f_last4 = found_acct[-4:] if len(found_acct) >= 4 else found_acct
                if (expected_acct in found_acct) or (found_acct in expected_acct) or (exp_last4 and exp_last4 == f_last4):
                    return True, "Verified Successfully"
                else:
                    if check_type == "IDENTITY":
                        return False, f"Account Mismatch. Document shows ...{f_last4}."

        # =========================================================
        # 4) FINAL FALLBACKS
        # =========================================================
        if check_type == "TRANSACTION":
            if found_amount is not None:
                return True, "Verified based on Amount."
            return False, "Verification failed: could not verify amount/account from the image."

        if check_type == "IDENTITY":
            return False, "Verification failed: could not verify identity/account from the image."

        return False, "Verification failed."

    except Exception as e:
        return False, f"System Error: {str(e)}"


# ==========================================
# PART 2: FINANCIAL ANALYSIS FUNCTIONS
# ==========================================

def _to_decimal(val, default="0.00") -> Decimal:
    try:
        if val is None or val == "":
            return Decimal(default)
        return Decimal(str(val))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _sp_unrestricted_year_row(church_id: int, year: int):
    """
    Reads one year row from Finance_UnrestrictedIncomeByYear.

    Column map:
      0  Year
      1  TotalTithes
      2  TotalOfferings
      3  TotalUnrestrictedDonations
      4  TotalUnrestrictedOtherIncome
      5  GrandTotalUnrestricted
      6  TotalBudgetReturnsToUnrestricted
      7  TotalUnrestrictedExpenses
      8  NetGrandTotalUnrestricted
      9  TotalRealExpensesAll
      10 TotalRestrictedExpenses
    """
    with connection.cursor() as cursor:
        cursor.callproc("Finance_UnrestrictedIncomeByYear", [church_id])
        rows = cursor.fetchall() or []

    for r in rows:
        try:
            if int(r[0]) == int(year):
                return {
                    "year": int(r[0]),
                    "tithes": _to_decimal(r[1]),
                    "offerings": _to_decimal(r[2]),
                    "donations": _to_decimal(r[3]),
                    "other_income": _to_decimal(r[4]),
                    "gross_unrestricted": _to_decimal(r[5]),
                    "budget_returns": _to_decimal(r[6]),
                    "unrestricted_expenses": _to_decimal(r[7]),
                    "net_unrestricted": _to_decimal(r[8]),
                    "real_expenses_all": _to_decimal(r[9]),
                    "restricted_expenses": _to_decimal(r[10]),
                }
        except Exception:
            continue

    return {
        "year": int(year),
        "tithes": Decimal("0.00"),
        "offerings": Decimal("0.00"),
        "donations": Decimal("0.00"),
        "other_income": Decimal("0.00"),
        "gross_unrestricted": Decimal("0.00"),
        "budget_returns": Decimal("0.00"),
        "unrestricted_expenses": Decimal("0.00"),
        "net_unrestricted": Decimal("0.00"),
        "real_expenses_all": Decimal("0.00"),
        "restricted_expenses": Decimal("0.00"),
    }


def calculate_financial_health(church_id, year=None):
    """
    Financial health based ONLY on Finance_UnrestrictedIncomeByYear.

    Card meaning:
      ratio = unrestricted_expenses / gross_unrestricted

    Status rules:
      - Deficit Risk: net < 0 OR ratio >= 1.00
      - Critical:     ratio >= 0.80
      - Warning:      ratio >= 0.50
      - Healthy:      ratio < 0.50
    """
    yr = year or date.today().year
    row = _sp_unrestricted_year_row(church_id, yr)

    gross = row["gross_unrestricted"]
    expenses = row["unrestricted_expenses"]
    net = row["net_unrestricted"]

    if gross > 0:
        ratio = expenses / gross
    else:
        ratio = Decimal("1.00") if expenses > 0 else Decimal("0.00")

    ratio = ratio.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if net < 0 or ratio >= Decimal("1.00"):
        status = "Deficit Risk"
        advice = "Spending exceeds income. Immediate cuts recommended."
        color = "danger"
    elif ratio >= Decimal("0.80"):
        status = "Critical"
        advice = "Spending is very high relative to income. Tight control is needed."
        color = "danger"
    elif ratio >= Decimal("0.50"):
        status = "Warning"
        advice = "Spending is manageable but should be monitored closely."
        color = "warning"
    else:
        status = "Healthy"
        advice = "Income safely covers spending."
        color = "success"

    return {
        # primary card fields
        "status": status,
        "ratio": float(ratio),
        "advice": advice,
        "color": color,
        "year": yr,

        # detailed SP-backed values
        "tithes": float(row["tithes"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "offerings": float(row["offerings"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "donations": float(row["donations"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "other_income": float(row["other_income"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "budget_returns": float(row["budget_returns"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "gross_unrestricted": float(row["gross_unrestricted"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "unrestricted_expenses": float(row["unrestricted_expenses"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "net_unrestricted": float(row["net_unrestricted"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "real_expenses_all": float(row["real_expenses_all"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "restricted_expenses": float(row["restricted_expenses"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),

        # compatibility keys for older templates / JS
        "total_income": float(row["gross_unrestricted"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "total_expenses": float(row["unrestricted_expenses"].quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
    }


def _parse_release_ministry(desc: str) -> str:
    """
    Example:
      'Budget Release: Youth | Release ID 65 | Released on 2026-02-13'
      -> 'Youth'
    """
    if not desc:
        return ""
    s = str(desc).strip()
    if not s.lower().startswith("budget release:"):
        return ""
    rest = s.split(":", 1)[1].strip()
    return rest.split("|", 1)[0].strip()


def _parse_return_ministry(desc: str) -> str:
    """
    Example:
      'Budget return from Youth | Release ID 65'
      -> 'Youth'
    """
    if not desc:
        return ""
    s = str(desc).strip()
    prefix = "budget return from"
    if not s.lower().startswith(prefix):
        return ""
    rest = s[len(prefix):].strip()
    return rest.split("|", 1)[0].strip()


def _suggest_score_from_util(util_pct: float) -> int:
    if util_pct >= 90:
        return 10
    if util_pct >= 70:
        return 9
    if util_pct >= 50:
        return 8
    if util_pct >= 30:
        return 7
    if util_pct >= 10:
        return 6
    return 5


def analyze_ministry_performance(church_id, year=None):
    """
    Real ministry analysis.

    Records used:
      - Releases: Expense rows with description starting 'Budget Release:'
      - Returns:  OtherIncome rows with description starting 'Budget return from'

    Net spent per ministry = releases - returns (clamped at 0)
    """
    yr = year or date.today().year

    ministries = list(
        Ministry.objects.filter(church_id=church_id, is_active=True).order_by("name")
    )

    # Releases by ministry name
    release_rows = (
        Expense.objects.filter(
            church_id=church_id,
            expense_date__year=yr,
            description__startswith="Budget Release:"
        )
        .exclude(status__in=["Declined", "Rejected"])
        .values_list("amount", "description")
    )

    release_by_name_lc = {}
    for amt, desc in release_rows:
        name = _parse_release_ministry(desc).strip().lower()
        if not name:
            continue
        release_by_name_lc[name] = release_by_name_lc.get(name, Decimal("0.00")) + _to_decimal(amt)

    # Returns by ministry name
    return_rows = (
        OtherIncome.objects.filter(
            church_id=church_id,
            date__year=yr,
            description__startswith="Budget return from"
        )
        .values_list("amount", "description")
    )

    return_by_name_lc = {}
    for amt, desc in return_rows:
        name = _parse_return_ministry(desc).strip().lower()
        if not name:
            continue
        return_by_name_lc[name] = return_by_name_lc.get(name, Decimal("0.00")) + _to_decimal(amt)

    # Allocated budgets by ministry
    budgets = (
        MinistryBudget.objects.filter(
            church_id=church_id,
            year=yr,
            is_active=True
        )
        .values("ministry_id")
        .annotate(allocated=Coalesce(Sum("amount_allocated"), Decimal("0.00")))
    )
    allocated_by_id = {b["ministry_id"]: _to_decimal(b["allocated"]) for b in budgets}

    total_net_spent = Decimal("0.00")
    net_spent_by_id = {}

    for m in ministries:
        key = (m.name or "").strip().lower()
        released = release_by_name_lc.get(key, Decimal("0.00"))
        returned = return_by_name_lc.get(key, Decimal("0.00"))
        net_spent = released - returned
        if net_spent < 0:
            net_spent = Decimal("0.00")

        net_spent_by_id[m.id] = net_spent
        total_net_spent += net_spent

    stats = {}
    for m in ministries:
        spent = net_spent_by_id.get(m.id, Decimal("0.00"))
        allocated = allocated_by_id.get(m.id, Decimal("0.00"))

        utilization = float((spent / allocated) * Decimal("100")) if allocated > 0 else 0.0
        share = float((spent / total_net_spent) * Decimal("100")) if total_net_spent > 0 else 0.0
        suggested = _suggest_score_from_util(utilization)

        stats[m.id] = {
            "utilization": round(utilization, 1),
            "share_percentage": round(share, 1),
            "suggested_score": suggested,
            "spent": float(spent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "allocated": float(allocated.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        }

    return stats


def get_projected_expenses(church_id):
    """
    Projects monthly recurring bills using the last 90 days.
    """
    today = date.today()
    start_date = today - timedelta(days=90)

    fixed_keywords = [
        "Utility", "Utilities", "Rent", "Lease",
        "Internet", "Wifi", "Electricity", "Water", "Bill"
    ]

    recent_bills = (
        Expense.objects.filter(
            church_id=church_id,
            expense_date__gte=start_date,
            category__name__in=fixed_keywords
        )
        .exclude(status__in=["Declined", "Rejected"])
        .aggregate(t=Coalesce(Sum("amount"), Decimal("0.00")))["t"]
    )

    recent_bills = _to_decimal(recent_bills)
    projected = (recent_bills / Decimal("3")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(projected)


def optimize_budget_distribution(total_funds, ministries):
    """
    Simple deterministic allocator:
      1) fund minimum requirements first
      2) distribute surplus by priority score
      3) never exceed max_cap
    """
    total_funds = float(total_funds or 0)
    remaining_funds = total_funds
    allocation = {}

    # Step 1: satisfy minimums in given ministry order
    for m in ministries:
        mid = str(m["id"])
        min_req = float(m.get("min_req", 0) or 0)

        if remaining_funds >= min_req:
            allocation[mid] = min_req
            remaining_funds -= min_req
        else:
            allocation[mid] = max(remaining_funds, 0)
            remaining_funds = 0

    # Step 2: distribute surplus by priority
    if remaining_funds > 0:
        total_score = sum(int(m.get("priority_score", 0) or 0) for m in ministries)
        if total_score > 0:
            surplus_chunk = remaining_funds
            for m in ministries:
                mid = str(m["id"])
                current = float(allocation.get(mid, 0))
                max_cap = float(m.get("max_cap", 0) or 0)
                score = int(m.get("priority_score", 0) or 0)

                share = (score / total_score) * surplus_chunk
                proposed = current + share

                if max_cap > 0:
                    allocation[mid] = min(proposed, max_cap)
                else:
                    allocation[mid] = proposed

    # Step 3: format result
    results = []
    for m in ministries:
        mid = str(m["id"])
        amt = float(allocation.get(mid, 0))
        results.append({
            "ministry_id": mid,
            "ministry_name": m["name"],
            "allocated_amount": round(amt, 2),
            "percentage": round((amt / total_funds * 100), 1) if total_funds > 0 else 0.0,
        })

    return {"allocations": results}