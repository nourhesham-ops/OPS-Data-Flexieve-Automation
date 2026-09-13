from pathlib import Path
import shutil
import tempfile
import re
import os
from rapidfuzz import process, fuzz
import pandas as pd
import zipfile


CODE_MAP = {
    "A01": "Not Available",
    "A02": "Not Available",
    "A03": "Not Available",
    "A04": "Wrong Address",
    "A05": "Wrong Address",
    "A06": "Not Available",
    "A07": "Rescheduled",
    "A08": "Charges Due",
    "A10": "Operational",
    "A11": "Operational",
    "A13": "Not Available",
    "A16": "Wrong Address",
    "A18": "Charges Due",
    "A19": "Refused",
    "A21": "Returned",
    "A22": "Operational",
    "A23": "Refused",
    "A27": "Refused",
    "U11": "Wrong Phone",
    "U13": "No Answer",
    "U14": "No Answer",
    "U15": "No Answer"
}

KEYWORD_MAP = {
    "Refused": ["refused", "rejected", "cancelled", "cancellation"],
    "Rescheduled": ["reschedule", "postponed", "retry"],
    "No Answer": ["no answer", "not answering", "unreachable"],
    "Wrong Address": ["incorrect address", "address not found", "address not clear"],
    "Change Address": ["change delivery address", "changed the address"],
    "Wrong Phone": ["wrong phone", "wrong mobile"],
    "Operational": ["driver out of time", "incorrect sorting", "signed-off"],
    "Returned": ["returned shipment"],
    "Weather": ["weather"]
}


# ----------------- Helpers -----------------
def repair_excel_aggressive(src: Path) -> Path:
    print(f"Attempting aggressive repair on: {src.name}")
    out = src.with_name(f"fixed_{src.name}")
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        with zipfile.ZipFile(src, 'r') as z:
            z.extractall(tmp_dir)
        
        styles_path = tmp_dir / "xl" / "styles.xml"
        if styles_path.exists():
            content = styles_path.read_text(encoding='utf-8')
            fixed_content = re.sub(r'rgb=["\'].*?["\']', 'rgb="FF000000"', content)
            styles_path.write_text(fixed_content, encoding='utf-8')

        with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
            for f in tmp_dir.rglob('*'):
                z.write(f, f.relative_to(tmp_dir))
        return out
    except Exception as e:
        print(f"Repair failed: {e}")
        return src
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def parse_dates(s, formats, dayfirst=False):
    s = s.astype(str).str.strip().replace({'nan': pd.NA, 'None': pd.NA, '': pd.NA})
    nums = pd.to_numeric(s, errors='coerce')
    dates = pd.Series(pd.NaT, index=s.index)

    if nums.notna().any():
        dates[nums.notna()] = pd.to_datetime(nums[nums.notna()], unit='D', origin='1899-12-30')

    mask = dates.isna() & s.notna()
    for fmt in formats:
        if not mask.any():
            break
        dates[mask] = pd.to_datetime(s[mask], format=fmt, errors='coerce')
        mask = dates.isna() & s.notna()

    if mask.any():
        dates[mask] = pd.to_datetime(s[mask], errors='coerce', dayfirst=dayfirst)
    
    return dates.dt.strftime("%Y-%m-%d")

def unify_cities(df, col='City'):
    if col not in df.columns or df[col].empty:
        return df
    df[col] = df[col].astype(str).str.strip().str.lower()
    cities = df[col].unique()
    mapping = {}

    for c in cities:
        if c in mapping:
            continue
        matches = process.extract(c, cities, scorer=fuzz.token_sort_ratio, score_cutoff=90)
        canonical = max([m[0] for m in matches], key=lambda x: (len(df[df[col] == x]), x))
        for m in matches:
            mapping[m[0]] = canonical

    df[col] = df[col].map(mapping).fillna(df[col])
    return df

def normalize_egypt_phone(phone):
    if pd.isna(phone):
        return pd.NA

    p = re.sub(r'\D', '', str(phone))

    if p == "":
        return pd.NA

    if p.startswith("20") and len(p) == 12:
        return "0" + p[2:]

    if p.startswith("0") and len(p) == 11:
        return p

    if len(p) == 10:
        return "0" + p

    if len(p) == 9:
        return "01" + p

    return pd.NA




def normalize_problem_reason(reason):

    if (
        pd.isna(reason)
        or str(reason).strip() == ""
        or str(reason).strip().lower() in ["nan", "none"]
    ):
        return ""

    text = str(reason)
    text_lower = text.lower()

    # -------- Level 1: Codes --------
    code_match = re.search(r'\b([AU]\d{2})\b', text)
    if code_match:
        code = code_match.group(1)
        if code in CODE_MAP:
            return CODE_MAP[code]

    # -------- Level 2: Keywords --------
    for category, keywords in KEYWORD_MAP.items():
        if any(k in text_lower for k in keywords):
            return category

    return text.strip()



def clean_product(name):
    if pd.isna(name):
        return ""

    parts = [p.strip() for p in str(name).split(",") if p.strip()]

    results = []

    for part in parts:
        matched_value = PRODUCT_KEYWORDS.get(part.lower())

        if matched_value is not None:
            results.append(matched_value)
        else:
            results.append(part)

    results = list(dict.fromkeys(results))
    return " , ".join(results)

PRODUCT_KEYWORDS = {

# ================= IONIC =================
"ionic brush": "Ionic Brush - Black",
"ionic brush - black": "Ionic Brush - Black",
"brush": "Ionic Brush - Black",  # Will map to Black as default
"pink brush": "Ionic Brush - Pink",
"فرشاة فرد الشعر الأيونية": "Ionic Brush - Black",
"smart brush": "Smart Brush",  # Changed from Ionic to Smart Brush

# ================= TRI DRY =================
"tri dry volumizer brush": "Tri dry",
"tri dry": "Tri dry",
"فرشاة تراي دراي المثلثية لتكثيف الشعر من الجذور": "Tri dry",

# ================= HOT AIR BRUSH =================
"vol pro": "Hot Air Brush Pro 2in1",
"vol gen 2": "Hot Air Brush gen. 2",
"vol gen 1": "Hot Air Brush gen. 1",
"vol mini": "Hot Air Brush Mini",

# ================= CURLA =================
"curla purple": "Curla Bruch-Baby Pink",
"curla green": "Curla Bruch-Mint Green",
"curla blue": "Curla Bruch-Navy Blue",

# ================= STRAIGHTENERS =================
"ceramic str": "Ceramic Straightener",
"slim str": "Slim Ceramic Straightener",
"str wide": "Wide Straightener",
"str float": "Float Straightener",
"str": "Hot Air Straightener",  # Default for "str"
"str 2*1": "Hot Air Straightener",

# ================= INFRARED =================
"str pro": "Infrared Steam Straightener Pro.",
"str lite": "Infrared lite straightener",

# ================= DRYER =================
"dryer": "Sleek Blow Dryer",

# ================= BRUSHES =================
"smooth brush": "Smooth Brush",
"super brush": "Super Dryer Brush",

# ================= CURL / WAVER =================
"auto waver": "Auto Waver",
"super cur": "Super Thin Curler",
"cur": "Instant Curler",  # Default for "cur"
"cur 3*1": "3 in 1 waver",
"cur 5*1": "5 in 1 Curling set",  # Note: Changed from "5 in 1" to match expected output

# ================= PREMIUM =================
"p.7*1": "Premium Styler 7 in 1",

# ================= EXTRA =================
"tanglend": "Tanglend",

# ================= ADDITIONAL MAPPINGS FOR COMPLETENESS =================
"فرشاة فرد الشعر الأيونية - black": "Ionic Brush - Black",
"فرشاة فرد الشعر الأيونية - pink": "Ionic Brush - Pink",
"ionic brush pink": "Ionic Brush - Pink",
"tri dry volumizer + ionic brush": "Tri dry-Ionic",
"vol pro": "Hot Air Brush Pro 2in1",
"فرشاة التكثيف الاحترافية  2 في 1 | النسخة المطورة": "Hot Air Brush Pro 2in1",
"فرشاة التكثيف من الجيل الثاني": "Hot Air Brush gen. 2",
"فرشاة التجفيف والتصفيف والتكثيف | الجيل الثاني": "Hot Air Brush gen. 2",
"فرشاة التجفيف والتكثيف | ميني": "Hot Air Brush Mini",
"curla brush - mint green": "Curla Bruch-Mint Green",
"curla brush - navy blue": "Curla Bruch-Navy Blue",
"curla brush - baby pink": "Curla Bruch-Baby Pink",
"sticker - ceramic straightener": "Ceramic Straightener",
"sticker - slim ceramic straightener": "Slim Ceramic Straightener",
"مكواة الفرد السريعة": "Wide Straightener",
"مكواة الفرد السحرية": "Float Straightener",
"مكواة فرد الشعر بالهواء الساخن 2 في 1": "Hot Air Straightener",
"مكواة الفرد والويفي 2 في 1": "Hot Air Straightener",
"hot air straightener": "Hot Air Straightener",
"مكواة البخار الاحترافية": "Infrared Steam Straightener Pro.",
"مكواة فرد الشعر بالبخار": "Infrared Steam Straightener",
"infrared steam straightener": "Infrared Steam Straightener",
"مجفف الشعر الاحترافي": "Sleek Blow Dryer",
"fast dryer - كبير": "Sleek Blow Dryer",
"fast dryer - وسط": "Sleek Blow Dryer",
"super dryer brush": "Super Dryer Brush",
"فرشاة التدليك": "Scalp",
"scalp": "Scalp",
"فرشاة الفرد والويفي الدائرية": "Heat Rounded Brush",
"heat rounded brush": "Heat Rounded Brush",
"مكواة الشعر الكيرلي الدوارة | الأوتوماتيكية": "Auto Waver",
"مكواة الكيرلي الأوتوماتيك": "Instant Curler",
"مجموعة الكيرلي والويفي (3في1)": "3 in 1 waver",
"5 in 1 curling set": "5 in 1 Curling set",
"مجموعة الكيرلي ٥ في ١": "5 in 1 Curling set",
"premium styler 7in1": "Premium Styler 7 in 1",
"premium styler 7 in 1": "Premium Styler 7 in 1",

}



def normalize_text(text):
    return re.sub(r'\s+', ' ', str(text).strip().lower())

def map_product(name):

    if pd.isna(name):
        return name

    name_clean = normalize_text(name)

    for key, value in PRODUCT_KEYWORDS.items():

        if name_clean == normalize_text(key):
            return value

    return name


import pandas as pd

def map_payment(method):
    """
    تعيين طرق الدفع إلى فئات محددة مع الاحتفاظ باسم الطريقة الأصلية أو المختصرة
    
    المعالجة:
    - القيم الفارغة (NaN, None, pd.NA, "", " ") => COD
    - Cash, COD, تحصيل, نقدي, كاش, delivery => COD
    - Credit card, بطاقة ائتمان => Paid - Credit card
    - InstaPay, إنستاباي => Paid - InstaPay
    - Pre-Paid, Prepaid, Pre-Paid Payments => Paid - Pre-Paid
    - تجميع Paymob (جميع الأنواع) => Paid - Paymob
    - تجميع Geidea => Paid - Geidea Pay
    - Talabat Payment => Paid - Talabat Payment
    - manual => Paid - manual
    - أي قيمة أخرى => Paid - (اسم طريقة الدفع الأصلية)
    
    Returns:
        str: "COD" أو f"Paid - {category}"
    """
    # التعامل مع جميع أنواع القيم الفارغة
    if pd.isna(method) or method is None:
        return "COD"
    
    # التعامل مع pd.NA
    try:
        if method is pd.NA:
            return "COD"
    except:
        pass
    
    # حفظ اسم طريقة الدفع الأصلي
    original_method_name = str(method).strip()
    
    # تحويل إلى string وتنظيف للمقارنة
    m = original_method_name.lower()
    
    # إذا كانت القيمة فارغة بعد التنظيف
    if not m or m in ["", "nan", "none", "null"]:
        return "COD"
    
    # أنماط الدفع النقدي عند الاستلام
    cash_patterns = ["cash", "cod", "تحصيل", "نقدي", "كاش", "delivery", "c.o.d", "c.o.d."]
    
    if any(pattern in m for pattern in cash_patterns):
        return "COD"

    # التحقق من Credit Card (مع استثناء Native Checkout لأنه سيتم تجميعه تحت Paymob)
    if ("credit" in m or "card" in m or "بطاقة" in m or "ائتمان" in m) and "native checkout" not in m:
        return "Paid - Credit card"
    
    # التحقق من Pre-Paid Payments (دمج Pre-Paid و Pre-Paid Payments)
    if "pre-paid" in m or "prepaid" in m or "pre paid" in m or ("pre" in m and "paid" in m):
        return "Paid - Pre-Paid"
    
    # التحقق من إنستاباي
    if "إنستاباي" in m or "instapay" in m:
        return "Paid - InstaPay"
    
    # تجميع كل أنواع Paymob
    if "paymob" in m:
        return "Paid - Paymob"
    
    # Geidea Pay
    if "geidea" in m:
        return "Paid - Geidea Pay"
    
    # Talabat Payment
    if "talabat" in m:
        return "Paid - Talabat Payment"
    
    # Manual payment
    if m == "manual" or "manual" in m:
        return "Paid - manual"
    
    # أي طريقة دفع أخرى: نرجع "Paid" متبوعة باسم الطريقة الأصلية
    return f"Paid - {original_method_name}"


def clean_tags(tags):

    # None safety
    if tags is None:
        return []

    # float NaN safety
    if isinstance(tags, float) and pd.isna(tags):
        return []

    # list / tuple case (important)
    if isinstance(tags, (list, tuple)):
        return [str(t).strip().lower() for t in tags if t]

    # string case
    if isinstance(tags, str):
        return [t.strip().lower() for t in tags.split(",") if t.strip()]

    # fallback (any weird type)
    return [str(tags).strip().lower()]

def extract_courier(tags):

    couriers = ["bosta", "aramex", "mylerz", "wheelify", "yfs"]

    for t in tags:

        if not isinstance(t, str):
            continue

        clean_t = t.lower().strip()

        for c in couriers:
            if c in clean_t:
                return c.title()

    return "Unknown"

def extract_confirmation(tags):
    # =========================
    # HANDLE EMPTY LIST (NO TAG)
    # =========================
    if not tags:
        return "No Tag"
    
    # تنظيف كل tag من المسافات الزائدة للمقارنة الدقيقة
    cleaned_tags = [tag.strip() for tag in tags]
    tags_lower = [tag.lower() for tag in cleaned_tags]
    
    # =========================
    # HIGH PRIORITY STATES
    # =========================
    if any("order confirmed" in t for t in tags_lower):
        return "Confirmed"

    if any("order rejected" in t for t in tags_lower):
        return "Rejected"

    # =========================
    # MID STATES
    # =========================
    if any("pending confirmation" in t for t in tags_lower):
        return "Pending"

    if any("no answer" in t for t in tags_lower):
        return "No Answer"

    if any("second trial" in t for t in tags_lower):
        return "Second Trial"

    if any("schedule" in t for t in tags_lower):
        return "Scheduled"

    # =========================
    # PICKUP CASES (مرنة أكثر)
    # =========================
    # لأي tag يحتوي على pickup و green plaza (بأي رموز بينهما)
    if any("pickup" in t and "green plaza" in t for t in tags_lower):
        return "Pickup Plaza"

    # لأي tag يحتوي على pickup و city stars (بأي رموز بينهما)
    if any("pickup" in t and "city stars" in t for t in tags_lower):
        return "Pickup City Stars"
    
    # لأي tag يحتوي فقط على pickup (بدون تحديد فرع) - اختياري
    # if any("pickup" in t for t in tags_lower):
    #     return "Pickup"

    # =========================
    # ALL POS CASES (unified)
    # =========================
    if any("pos" in t for t in tags_lower):
        return "POS"

    # =========================
    # EMPLOYEE CASE
    # =========================
    if any("employee" in t for t in tags_lower):
        return "Employee"
    
    if any("sales staff" in t for t in tags_lower):
        return "Employee"


    if any(re.fullmatch(r'test', t.strip().lower()) for t in cleaned_tags):
        return "Test"
    
    if any("pr / free orders" in t for t in tags_lower):
        return "PR"
    
    if any("cases" in t for t in tags_lower):
        return "Cases"

    if any("on hold" in t for t in tags_lower):
        return "On Hold"

    if any("reservation" in t for t in tags_lower):
        return "Reservation"

    # =========================
    # DEFAULT
    # =========================
    return cleaned_tags[0]


def parse_mixed_date(series):
    """
    Handles mixed date formats (US + ISO) safely - VECTORIZED
    """
    # Try ISO format first (faster)
    parsed = pd.to_datetime(series, errors='coerce', format='%Y-%m-%d')
    
    # Only try US format for remaining nulls
    mask = parsed.isna()
    if mask.any():
        # Use vectorized operation on subset
        us_dates = series[mask].astype(str)
        parsed.loc[mask] = pd.to_datetime(
            us_dates,
            format='%m/%d/%Y',
            errors='coerce'
        )
    return parsed


def normalize_awb(series):
    """
    Deep cleaning for AWB values - SAFE VERSION
    """

    s = series.astype(str).str.strip()

    # detect REAL scientific notation numbers only
    sci_mask = s.str.match(r'^\d+\.?\d*e\+\d+$', case=False, na=False)

    # convert only scientific numeric values
    s.loc[sci_mask] = (
        s.loc[sci_mask]
        .apply(lambda x: str(int(float(x))))
    )

    return (
        s
        .str.replace(r'\.0$', '', regex=True)
        .str.replace(r'[\n\r\t]', '', regex=True)
        .str.replace(r'\s+', '', regex=True)
        .str.replace(u'\xa0', '', regex=False)
        .str.upper()
        .replace(['NAN', 'NONE', ''], '')
        .str.strip()
    )
