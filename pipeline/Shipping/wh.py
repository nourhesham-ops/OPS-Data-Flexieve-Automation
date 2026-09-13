# ============================================================
# تنظيف ملف Transfer (stock.picking)
# + تجميع كل معلومات الأوردر في صف واحد
# + تجميع المنتجات والكميات
# + عدم حذف أي بيانات من ملف Excel
# + Sync إلى Supabase orders
# + قياس وقت كل مرحلة
# ============================================================

from pathlib import Path
import os
import time

import pandas as pd
from dotenv import load_dotenv

from DBManage import sync_to_supabase_shipping


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[2]

FILES_DIR = BASE_DIR / "files" / "WH"


# ملف الإخراج
OUTPUT_FILE = Path(
    r"C:\Users\user\Downloads\OPS Data Management Flexieve\output\Cleaned_Orders.xlsx"
)

SEPARATOR = ", "


GROUP_COLUMN = "Source Document"

PRODUCT_COLUMN = "Sales Order/Order Lines/Product"


# ============================================================
# ENV
# ============================================================

load_dotenv()

DB_URL = os.getenv("DB_URL_Orders")

if not DB_URL:

    raise ValueError(
        "DB_URL_Orders غير موجود في ملف .env"
    )


# ============================================================
# COLUMN RENAME
# ============================================================

COLUMN_RENAME = {

    "Source Document":
        "OrderID",

    "Reference":
        "AWB",

    "Scheduled Date":
        "Date",

    "Sales Order/Order Lines/Product":
        "Product",

    "Sales Order/Order Lines/Product Qty":
        "Quantity",

    "Sales Order/Invoices/Preferred Payment Method Line":
        "Payment Type",

    "Contact":
        "Customer",

    "Contact/State":
        "City",

    "Sales Order/Order Lines/Pricelist Item":
        "Pricelist Item",

    "Sales Order/Order Lines/Order Status":
        "Order Status",

    "Sales Order/Customer/Sale Order Count":
        "Order Count",

    "Sales Order/Already invoiced":
        "Invoiced",

    "Sales Order/Online payment":
        "Online Payment",

    "Sales Order/Order Lines/Price Reduce Tax excl":
        "Price Excl Tax",

    "Sales Order/Order Lines/Price Reduce Tax incl":
        "Price Incl Tax",

    "Sales Order/Net Price":
        "Net Price",
}


# ============================================================
# FINAL COLUMNS
# ============================================================

FINAL_COLUMNS = [

    "OrderID",

    "Date",

    "AWB",

    "Payment Type",

    "Customer",

    "City",

    "Status",

    "Product",

    "Quantity",

    "Priority",

    "Address",

    "Source Location",

    "Batch Transfer",

    "Pricelist Item",

    "Order Status",

    "Order Count",

    "Invoiced",

    "Online Payment",

    "Price Excl Tax",

    "Price Incl Tax",

    "Net Price",
]


# ============================================================
# ORDER LEVEL COLUMNS
# ============================================================

ORDER_COLUMNS = [

    "Date",

    "AWB",

    "Payment Type",

    "Customer",

    "City",

    "Status",

    "Priority",

    "Address",

    "Source Location",

    "Batch Transfer",

    "Order Count",

    "Invoiced",

    "Online Payment",

    "Net Price",
]


# ============================================================
# LINE LEVEL COLUMNS
# ============================================================

LINE_COLUMNS = [

    "Product",

    "Quantity",

    "Pricelist Item",

    "Order Status",

    "Price Excl Tax",

    "Price Incl Tax",
]


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    """
    تحويل القيمة إلى نص نظيف.
    """

    if pd.isna(value):

        return ""

    return str(value).strip()


def first_non_empty(series):
    """
    إرجاع أول قيمة غير فارغة.

    تستخدم فقط عندما نكون متأكدين
    أن اختلاف القيم غير مهم.
    """

    for value in series:

        if pd.isna(value):

            continue

        value = str(value).strip()

        if value:

            return value

    return ""


def join_unique(series):
    """
    تجميع القيم بدون تكرار
    مع الحفاظ على ترتيب ظهورها.
    """

    result = []

    seen = set()

    for value in series:

        if pd.isna(value):

            continue

        value = str(value).strip()

        if not value:

            continue

        if value not in seen:

            seen.add(value)

            result.append(value)

    return SEPARATOR.join(result)


def format_quantity(value):
    """
    تحويل الكمية إلى شكل مناسب.

    مثال:

    2.0  -> 2
    2.5  -> 2.5
    """

    if pd.isna(value):

        return ""

    try:

        number = float(value)

        if number.is_integer():

            return str(int(number))

        return str(number)

    except Exception:

        return str(value)


# ============================================================
# START
# ============================================================

total_start = time.perf_counter()


print("=" * 70)
print("START")
print("=" * 70)


# ============================================================
# FIND INPUT EXCEL FILE
# ============================================================

print("\nChecking input folder...")


if not FILES_DIR.exists():

    raise FileNotFoundError(
        f"الفولدر غير موجود:\n{FILES_DIR}"
    )


# البحث عن ملفات Excel
excel_files = list(FILES_DIR.glob("*.xlsx"))


if not excel_files:

    raise FileNotFoundError(
        f"لا يوجد أي ملف Excel داخل الفولدر:\n{FILES_DIR}"
    )


# لو فيه أكثر من ملف
if len(excel_files) > 1:

    print("\nExcel files found:")

    for file in excel_files:

        print(f" - {file.name}")

    raise ValueError(
        "\nيوجد أكثر من ملف Excel داخل الفولدر.\n"
        "برجاء ترك ملف Excel واحد فقط داخل فولدر WH."
    )


# الملف الوحيد
FILE_PATH = excel_files[0]


print(
    f"\nInput file:\n{FILE_PATH}"
)


# ============================================================
# CHECK OUTPUT FOLDER
# ============================================================

OUTPUT_FILE.parent.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# READ EXCEL
# ============================================================

start = time.perf_counter()


print("\n[1/7] Reading Excel...")


df = pd.read_excel(
    FILE_PATH,
    dtype=object,
    engine="openpyxl"
)


original_row_count = len(df)


print(
    f"Rows loaded: {original_row_count:,}"
)


print(
    f"Columns loaded: {len(df.columns):,}"
)


print(
    f"TIME READ EXCEL: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# CHECK REQUIRED COLUMNS
# ============================================================

required_columns = [

    GROUP_COLUMN,

    PRODUCT_COLUMN,

    "Reference",

    "Scheduled Date",

    "Sales Order/Order Lines/Product Qty",

    "Sales Order/Invoices/Preferred Payment Method Line",

    "Contact",

    "Contact/State",

    "Sales Order/Order Lines/Pricelist Item",

    "Sales Order/Order Lines/Order Status",

    "Sales Order/Customer/Sale Order Count",

    "Sales Order/Already invoiced",

    "Sales Order/Online payment",

    "Sales Order/Order Lines/Price Reduce Tax excl",

    "Sales Order/Order Lines/Price Reduce Tax incl",

    "Sales Order/Net Price",
]


missing_columns = [

    column

    for column in required_columns

    if column not in df.columns

]


if missing_columns:

    print("\nMissing columns:")

    for column in missing_columns:

        print(f" - {column}")


    raise ValueError(
        "\nملف Excel لا يحتوي على الأعمدة المطلوبة."
    )


# ============================================================
# NO FILTERING
# ============================================================

start = time.perf_counter()


print("\n[2/7] Checking data WITHOUT deleting rows...")


# ============================================================
# IMPORTANT
# ============================================================
#
# هنا لا نحذف أي Row.
#
# لا يوجد:
#
# df = df.loc[mask]
#
# ولا يوجد:
#
# Product != "[BWA] Bosta Delivery"
#
# ولا يوجد:
#
# OrderID != ""
#
# ============================================================


empty_order_ids = (

    df[GROUP_COLUMN]

    .isna()

    | df[GROUP_COLUMN]
    .astype(str)
    .str.strip()
    .eq("")
).sum()


empty_products = (

    df[PRODUCT_COLUMN]

    .isna()

    | df[PRODUCT_COLUMN]
    .astype(str)
    .str.strip()
    .eq("")
).sum()


bosta_rows = (

    df[PRODUCT_COLUMN]

    .fillna("")

    .astype(str)

    .str.strip()

    .eq("[BWA] Bosta Delivery")
).sum()


print(
    f"Rows before processing: "
    f"{len(df):,}"
)


print(
    f"Rows with empty OrderID: "
    f"{empty_order_ids:,}"
)


print(
    f"Rows with empty Product: "
    f"{empty_products:,}"
)


print(
    f"Bosta Delivery rows: "
    f"{bosta_rows:,}"
)


print(
    "No rows were deleted."
)


print(
    f"TIME CHECK: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# RENAME
# ============================================================

start = time.perf_counter()


print("\n[3/7] Renaming and cleaning...")


df.rename(
    columns=COLUMN_RENAME,
    inplace=True
)


# ============================================================
# CREATE MISSING OPTIONAL COLUMNS
# ============================================================

for column in FINAL_COLUMNS:

    if column not in df.columns:

        df[column] = ""


# ============================================================
# CLEAN ORDER ID
# ============================================================

df["OrderID"] = (

    df["OrderID"]

    .fillna("")

    .astype(str)

    .str.strip()

    .str.replace(
        "#",
        "",
        regex=False
    )
)


# ============================================================
# CLEAN PRODUCT
# ============================================================

df["Product"] = (

    df["Product"]

    .fillna("")

    .astype(str)

    .str.strip()
)


# ============================================================
# QUANTITY
# ============================================================

df["Quantity"] = pd.to_numeric(
    df["Quantity"],
    errors="coerce"
).fillna(0)


# ============================================================
# DATE
# ============================================================

df["Date"] = pd.to_datetime(
    df["Date"],
    errors="coerce"
)


# ============================================================
# CLEAN OBJECT COLUMNS
# ============================================================

text_columns = [

    "AWB",

    "Payment Type",

    "Customer",

    "City",

    "Status",

    "Priority",

    "Address",

    "Source Location",

    "Batch Transfer",

    "Pricelist Item",

    "Order Status",

    "Order Count",

    "Invoiced",

    "Online Payment",

    "Price Excl Tax",

    "Price Incl Tax",

    "Net Price",
]


for column in text_columns:

    if column in df.columns:

        df[column] = (

            df[column]

            .fillna("")

            .astype(str)

            .str.strip()
        )


print(
    f"TIME CLEAN: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# GROUP PRODUCTS
# ============================================================

start = time.perf_counter()


print("\n[4/7] Grouping products...")


# ============================================================
# First grouping
#
# OrderID + Product
#
# مثال:
#
# Order 100
#
# Product A - 1
# Product A - 1
# Product B - 2
#
# يصبح:
#
# Product A - 2
# Product B - 2
#
# ============================================================


product_grouped = (

    df

    .groupby(
        [
            "OrderID",
            "Product"
        ],

        sort=False,

        as_index=False,

        dropna=False
    )

    .agg({

        "Quantity":
            "sum",

        "Pricelist Item":
            join_unique,

        "Order Status":
            join_unique,

        "Price Excl Tax":
            join_unique,

        "Price Incl Tax":
            join_unique,

    })

)


# ============================================================
# FORMAT QUANTITY
# ============================================================

product_grouped["Quantity"] = (

    product_grouped["Quantity"]

    .map(format_quantity)
)


# ============================================================
# SECOND GROUP
#
# OrderID
#
# Product:
# A, B
#
# Quantity:
# 2, 5
#
# ============================================================

line_grouped = (

    product_grouped

    .groupby(
        "OrderID",

        sort=False,

        dropna=False
    )

    .agg({

        "Product":
            join_unique,

        "Quantity":
            join_unique,

        "Pricelist Item":
            join_unique,

        "Order Status":
            join_unique,

        "Price Excl Tax":
            join_unique,

        "Price Incl Tax":
            join_unique,

    })

)


print(
    f"Unique orders: "
    f"{line_grouped.index.nunique():,}"
)


print(
    f"TIME PRODUCT GROUPING: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# GROUP ORDER DATA
# ============================================================

start = time.perf_counter()


print("\n[5/7] Grouping order information...")


# ============================================================
# IMPORTANT
#
# هنا بدل first_non_empty
# نستخدم join_unique
#
# عشان لو فيه أكثر من قيمة مختلفة
# ما نخسرش البيانات.
#
# مثال:
#
# Customer:
# Ahmed
# Ahmed
#
# النتيجة:
# Ahmed
#
#
# Address:
# Cairo
# Alexandria
#
# النتيجة:
# Cairo, Alexandria
#
# ============================================================


order_grouped = (

    df

    .groupby(
        "OrderID",

        sort=False,

        dropna=False
    )[ORDER_COLUMNS]

    .agg(join_unique)

)


# ============================================================
# MERGE
# ============================================================

df_grouped = (

    order_grouped

    .join(
        line_grouped,
        how="left"
    )

    .reset_index()

)


print(
    f"Final orders: "
    f"{len(df_grouped):,}"
)


print(
    f"TIME ORDER GROUPING: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# FINAL COLUMNS
# ============================================================

start = time.perf_counter()


print("\n[6/7] Preparing final data...")


# ============================================================
# CREATE ANY MISSING FINAL COLUMNS
# ============================================================

for column in FINAL_COLUMNS:

    if column not in df_grouped.columns:

        df_grouped[column] = ""


# ============================================================
# KEEP FINAL COLUMNS
# ============================================================

df_grouped = df_grouped[
    FINAL_COLUMNS
]


# ============================================================
# SORT
# ============================================================

df_grouped = (

    df_grouped

    .sort_values(
        [
            "Date",
            "OrderID"
        ],

        na_position="last"

    )

    .reset_index(drop=True)

)


# ============================================================
# FINAL CLEAN
# ============================================================

df_grouped = df_grouped.fillna("")


# ============================================================
# DATE FORMAT
# ============================================================

if "Date" in df_grouped.columns:

    df_grouped["Date"] = (

        pd.to_datetime(
            df_grouped["Date"],
            errors="coerce"
        )

        .dt.strftime("%Y-%m-%d %H:%M:%S")

        .fillna("")
    )


print(
    f"Final rows: "
    f"{len(df_grouped):,}"
)


print(
    f"TIME FINAL PROCESSING: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# SUPABASE SYNC
# ============================================================

start = time.perf_counter()


print("\n[7/7] Syncing to Supabase...")


sync_to_supabase_shipping(
    df_grouped,
    DB_URL,
    "OrderID",
    "orders"
)


print(
    f"TIME SUPABASE SYNC: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# SAVE EXCEL
# ============================================================

start = time.perf_counter()


print("\nSaving cleaned Excel...")


df_grouped.to_excel(
    OUTPUT_FILE,
    index=False,
    engine="openpyxl"
)


print(
    f"TIME SAVE EXCEL: "
    f"{time.perf_counter() - start:.2f} sec"
)


# ============================================================
# TOTAL
# ============================================================

total_time = (

    time.perf_counter()

    - total_start
)


print("\n")

print("=" * 70)

print("DONE")

print("=" * 70)


print(
    f"Original rows : "
    f"{original_row_count:,}"
)


print(
    f"Rows after check: "
    f"{len(df):,}"
)


print(
    f"Final orders : "
    f"{len(df_grouped):,}"
)


print(
    f"Rows removed : "
    f"{original_row_count - len(df):,}"
)


print(
    f"Input file : "
    f"{FILE_PATH}"
)


print(
    f"Output file: "
    f"{OUTPUT_FILE}"
)


print(
    f"TOTAL TIME : "
    f"{total_time:.2f} sec"
)


print("=" * 70)
