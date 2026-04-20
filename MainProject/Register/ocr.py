import re, os
from PIL import Image
import pytesseract
from dateutil import parser as dateparser
from django.conf import settings

# Point to tesseract.exe on Windows if set in settings
if getattr(settings, "TESSERACT_CMD", None):
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

# -------------------------------------------------------------------
# REGEXES
# -------------------------------------------------------------------

TOTAL_HINTS = re.compile(
    r'\b(total|total\s*amount|amount\s*due|balance\s*due|grand\s*total)\b',
    re.I
)

# Match money in US/PH (1,234.56), EU (1.234,56), or plain decimals/ints.
MONEY = re.compile(
    r'(?:₱|\u20B1|\bPHP\b|\bPhp\b)?\s*('
    r'(?:\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?)'   # 1,234.56
    r'|(?:\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?)'  # 1.234,56
    r'|(?:\d+(?:\.\d{1,2})?)'                 # 1200 or 1200.50
    r')'
)

DATE_CANDIDATES = re.compile(
    r'(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|'
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s*\d{4})',
    re.I
)

# -------------------------------------------------------------------
# HELPERS
# -------------------------------------------------------------------

def _open_image(path):
    # For images only; if you need PDFs, convert upstream
    return Image.open(path)

def _normalize_amount_str(num_str: str) -> str:
    """
    Normalize OCR number strings:
      - "1,234.56" -> "1234.56"
      - "1.234,56" -> "1234.56"
      - "1 234.56" -> "1234.56"
      - "1,234" or "1.234" -> "1234"
    """
    s = num_str.strip()
    s = re.sub(r'\s+', '', s)

    # EU-style full: 1.234,56
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+,\d{1,2}', s):
        return s.replace('.', '').replace(',', '.')

    # US/PH-style: 1,234.56 (or no decimals)
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?', s):
        return s.replace(',', '')

    # US/PH thousands only: 1,234
    if re.fullmatch(r'\d{1,3}(?:,\d{3})+', s):
        return s.replace(',', '')

    # EU thousands only: 1.234
    if re.fullmatch(r'\d{1,3}(?:\.\d{3})+', s):
        return s.replace('.', '')

    # Plain: 1200 or 1200.50
    if re.fullmatch(r'\d+(?:\.\d{1,2})?', s):
        return s

    # Fallback scrub
    filtered = re.sub(r'[^0-9.,]', '', s).replace(',', '')
    if filtered.count('.') > 1:
        parts = filtered.split('.')
        filtered = ''.join(parts[:-1]) + '.' + parts[-1]
    return filtered

def _parse_amounts_from_text(text: str):
    """
    Extract & normalize all currency-like values to floats.
    Skip 4-digit integers that look like years (1900–2099) unless they have decimals.
    """
    vals = []
    for m in MONEY.finditer(text):
        raw = m.group(1)
        try:
            norm = _normalize_amount_str(raw)
            # Skip likely years: exactly 4 digits, between 1900 and 2099, and NO decimals
            if re.fullmatch(r'\d{4}', norm):
                year = int(norm)
                if 1900 <= year <= 2099:
                    continue
            vals.append(float(norm))
        except Exception:
            pass
    return vals

def _best_total(text):
    """
    Prefer numbers on lines that contain TOTAL-like hints.
    If none on the same line (OCR split), also scan the next 2 lines.
    Fallback: largest plausible amount in the whole text (ignoring year-like ints).
    """
    lines = text.splitlines()

    for i, ln in enumerate(lines):
        if TOTAL_HINTS.search(ln):
            # 1) Try same line
            vals = _parse_amounts_from_text(ln)
            if vals:
                return max(vals)

            # 2) Try window: this line + next 2 lines (handles ₱ and number split)
            window = ' '.join(lines[i:i+3])
            vals_window = _parse_amounts_from_text(window)
            if vals_window:
                return max(vals_window)

    # Fallback: take the largest overall (years already filtered)
    all_vals = _parse_amounts_from_text(text)
    return max(all_vals) if all_vals else None

def _best_date(text):
    subs = DATE_CANDIDATES.findall(text)
    for s in subs:
        try:
            dt = dateparser.parse(s, dayfirst=False, fuzzy=True)
            return dt.date().isoformat()
        except:
            continue
    try:
        dt = dateparser.parse(text, dayfirst=False, fuzzy=True)
        return dt.date().isoformat()
    except:
        return None

def _guess_type(text):
    t = text.lower()
    pairs = [
        ("Electric Bill", ["kwh","electric","power","veco","Visayan Electric Company","meralco","kuryente"]),
        ("Internet Bill", ["internet","fiber","wifi","converge","pldt","globe at home","bayantel"]),
        ("Salary",        ["salary","payroll","wage","honorarium"]),
        ("Ministry",      ["ministry","youth","worship","event","program"]),
        ("Miscellaneous", ["supplies","stationery","ink","paper","misc"]),
    ]
    for label, keys in pairs:
        if any(k in t for k in keys):
            return label
    return "Others"

# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------

def run_ocr(file_path):
    img = _open_image(file_path)
    text = pytesseract.image_to_string(img)

    amount = _best_total(text)   # now robust vs. year “2024”
    date   = _best_date(text)
    etype  = _guess_type(text)

    return {
        "raw_text": text,
        "amount": amount,
        "date": date,
        "expense_type": etype
    }
