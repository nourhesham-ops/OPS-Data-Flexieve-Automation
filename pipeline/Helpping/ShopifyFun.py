import re
import pandas as pd


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



SKU_TO_PRODUCT = {
    "CB-H09-BLK": "Ionic Brush - Black",
    "CB-H09-PNK": "Ionic Brush - Pink",
    "CB-S07": "Ceramic Straightener",
    "CB-H01": "Hot Air Brush Pro 2in1",
    "CB-H12-GR": "Curla Brush-Mint Green",
    "CB-H12-NB": "Curla Brush-Navy Blue",
    "CB-H12-BP": "Curla Brush-Baby Pink",
    "CB-S06": "Slim Ceramic Straightener",
    "CB-OLD-01": "Tanglend",
    "CB-H06": "Auto Waver",
    "CB-C06": "Super Thin Curler",
    "CB-C03": "3 in 1 waver",
    "CB-S04": "Wide Straightener",
    "CB-H01-G1": "Hot Air Brush gen. 1",
    "CB-H11": "Sleek Blow Dryer",
    "CB-H07": "Smooth Brush",
    "CB-S03": "Infrared lite straightener",
    "CB-H08": "Super Dryer Brush",
    "CB-OLD-03": "Hot Air Brush Mini",
    "CB-H02": "Hot Air Straightener",
    "CB-H03": "Tri dry",
    "CB-C01": "5 in 1 Curling set",
    "CB-C05": "Instant Curler",
    "CB-S05": "Float Straightener",
    "CB-C08": "Heat Rounded Brush",
    "CB-S02": "Infrared Steam Straightener Pro.",
    "CB-H05": "Hot Air Brush gen. 2",
    "CB-H04": "Smart Brush",
    "KMS-818": "Premium Styler 7 in 1",
    "CB-OLD-02": "Scalp",
    "CB-S01": "Infrared Steam Straightener",
    "CB-H10": "Fast Dryer",
    "CB-A02": "Paddle Brush",
    "CB-A04": "Volume Round Brush",
    "CB-A05": "Easy Brush",
    "CB-A06": "Detangler Set",
    "CB-A07": "Styling Comb",
    "CB-A08": "Scalp Massager Brush – Black",
    "CB-A09": "Scalp Massager Brush – Pink",
    "CB-A10": "Satin Hair Scrunchie Tie",
    "CB-A11": "Spiral Coil Hair Ties",
    "CB-A12": "Shower Bonnet - Pink",
    "CB-A13": "Microfiber Hair Towel",
    "CB-A14": "Silicone Heat-Resistant Bag & Mat"
}

def map_product(row):
    """
    ترجع اسم المنتج الجديد لو الـ SKU موجود،
    أو تحتفظ بالاسم الأصلي لو الـ SKU مش موجود
    """
    sku = row.get('SKU')
    original_product = row.get('Product')
    
    if pd.isna(sku):
        return original_product
    
    sku_clean = str(sku).strip()
    return SKU_TO_PRODUCT.get(sku_clean, original_product)



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
