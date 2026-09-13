from pathlib import Path
import os
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DB_URL_Shipping")

# ======================================================
# File Path
# ======================================================
FILE_PATH = r"C:\Users\Administrator\Downloads\Untitled spreadsheet.xlsx"

TABLE_NAME = "shipments"

# ======================================================
# Database Columns
# ======================================================
DB_COLUMNS = [
    "AWB",
    "Return AWB",
    "OrderID",
    "Phone",
    "Date Shipped",
    "Status",
    "Status Date",
    "Product",
    "Number Of attempts",
    "Problem Reason",
    "Payment Type",
    "COD Value",
    "HUB",
    "NDR",
    "Shipment Type",
    "Shipping Company",
    "Reshipping - New",
    "CST Name"
]


def clean_value(v):
    if pd.isna(v):
        return None

    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()

    if isinstance(v, np.datetime64):
        return pd.to_datetime(v).to_pydatetime()

    return v


# ======================================================
# Read File
# ======================================================
file = Path(FILE_PATH)

if not file.exists():
    raise FileNotFoundError(FILE_PATH)

print(f"📄 Reading: {file.name}")
print(f"📦 File Size: {file.stat().st_size:,} bytes")

suffix = file.suffix.lower()

if suffix == ".csv":
    df = pd.read_csv(file)
elif suffix in [".xlsx", ".xls"]:
    df = pd.read_excel(file)
else:
    raise Exception("Unsupported file type.")

if df.empty:
    raise Exception("File is empty.")

print(f"Rows : {len(df):,}")
print(f"Columns : {len(df.columns)}")

# ======================================================
# Keep only required columns
# ======================================================
df = df.reindex(columns=DB_COLUMNS)

# تنظيف AWB
df["AWB"] = (
    df["AWB"]
    .astype(str)
    .str.strip()
    .str.replace(r"\.0$", "", regex=True)
)

df = df[df["AWB"] != ""]
df = df[df["AWB"].str.lower() != "nan"]

# الاحتفاظ بآخر سجل لنفس AWB
df = df.drop_duplicates(subset=["AWB"], keep="last")

values = [
    tuple(clean_value(v) for v in row)
    for row in df.to_numpy()
]

columns_sql = ",".join(f'"{c}"' for c in DB_COLUMNS)

update_sql = ",".join(
    f'"{c}" = EXCLUDED."{c}"'
    for c in DB_COLUMNS
    if c != "AWB"
)

query = f"""
INSERT INTO {TABLE_NAME} ({columns_sql})
VALUES %s
ON CONFLICT ("AWB")
DO UPDATE SET
{update_sql};
"""

# ======================================================
# Upload
# ======================================================
with psycopg2.connect(DB_URL) as conn:
    with conn.cursor() as cur:

        execute_values(
            cur,
            query,
            values,
            page_size=1000
        )

print(f"\n✅ Uploaded / Updated {len(values):,} rows successfully.")