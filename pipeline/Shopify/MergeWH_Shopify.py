import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from pathlib import Path
import re

import pandas as pd


# ================= CONFIG =================

MAIN_SHEET = "1B2nktYv4HbZudu2XNHhPlB7gsaKFfdArIuyESlcfv7c"
WAREHOUSE_SHEET_ID = "12q_q7lU_zPRaywuTP3mVkliYEl_SM8WNl0wFi5bMC2Y"

SHOPIFY_SHEET_NAME = "Shopify Data"
WAREHOUSE_SHEET_NAME = "Warehouse Shipping"
OUTPUT_SHEET = "WH-Shopify"

# ================= SCOPE =================
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

# ================= AUTH =================
def auth(BASE_DIR):
    creds_path = BASE_DIR / "credentials.json"
    creds = Credentials.from_service_account_file(creds_path, scopes=scope)
    return gspread.authorize(creds)

# ================= LOAD =================
def load_sheet(client, sheet_id, sheet_name, col_map):
    ws = client.open_by_key(sheet_id).worksheet(sheet_name)
    df = pd.DataFrame(ws.get_all_records())

    if df.empty:
        return df

    selected_cols = [c for c in col_map.keys() if c in df.columns]
    df = df[selected_cols].copy()
    df = df.rename(columns=col_map)
    
    if sheet_name == "Warehouse Shipping":
        df["Data Source"] = "WH-Shipping"

    return df

# ================= FILTER =================
def filter_shopify(df,Date):
    if "Created Date" not in df.columns:
        return df

    df["Created Date"] = pd.to_datetime(df["Created Date"], errors='coerce')
    return df[df["Created Date"] >= Date]

def filter_warehouse(df,Date):
    if "Warehouse Date" not in df.columns:
        return df

    df["Warehouse Date"] = pd.to_datetime(df["Warehouse Date"], errors='coerce')
    return df[df["Warehouse Date"] >= Date]

def full_join(shopify_df, warehouse_df):

    shopify_df = shopify_df.copy()
    warehouse_df = warehouse_df.copy()

    shopify_df['OrderID'] = shopify_df['OrderID'].astype(str).str.strip()
    warehouse_df['OrderID'] = warehouse_df['OrderID'].astype(str).str.strip()

    # Source tagging
    shopify_df["Data Source"] = "Shopify"
    warehouse_df["Data Source"] = "Warehouse"

    warehouse_df['Warehouse Date'] = pd.to_datetime(warehouse_df['Warehouse Date'], errors='coerce')
    shopify_df['Created Date'] = pd.to_datetime(shopify_df['Created Date'], errors='coerce')
    warehouse_df['RT Date'] = pd.to_datetime(warehouse_df['RT Date'], errors='coerce')

    merged = pd.merge(
        shopify_df,
        warehouse_df,
        on='OrderID',
        how='outer',
        suffixes=("_shop", "_wh")
    )

    if "Data Source_shop" in merged.columns and "Data Source_wh" in merged.columns:
        merged["Data Source"] = merged["Data Source_shop"].fillna(merged["Data Source_wh"])
        merged.drop(columns=["Data Source_shop", "Data Source_wh"], inplace=True)

    if "AWB" in merged.columns:
        merged = merged.sort_values(
            ["AWB", "Warehouse Date", "Created Date"],
            ascending=[True, False, False]
        )

        merged = merged.drop_duplicates(subset=["AWB"], keep="first")

    return merged

# ================= FAST UPDATE =================
def fast_update(client, new_df):

    spreadsheet = client.open_by_key(MAIN_SHEET)

    try:
        ws = spreadsheet.worksheet(OUTPUT_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=OUTPUT_SHEET, rows="1000", cols="50")

    if "OrderID" in new_df.columns:
        new_df["OrderID"] = new_df["OrderID"].astype(str).str.strip()

    date_cols = ["Created Date", "RT Date", "Status Date", "Warehouse Date"]
    other_cols = [c for c in new_df.columns if c not in date_cols]

    # نعالج الأعمدة الغير تاريخية
    new_df[other_cols] = new_df[other_cols].fillna("")

    # نعالج أعمدة التاريخ بشكل آمن
    for col in date_cols:
        if col in new_df.columns:
            # تحويل أي شيء ممكن لـ datetime
            new_df[col] = pd.to_datetime(new_df[col], errors='coerce')
            # تحويل الـ datetime لـ نص، وترك NaT كفارغ
            new_df[col] = new_df[col].dt.strftime('%Y-%m-%d')
            new_df[col] = new_df[col].fillna("")

    ws.clear()

    ws.append_rows(
        [new_df.columns.tolist()] +
        new_df.values.tolist(),
        value_input_option='USER_ENTERED'
    )

    print("Fast Refresh Done (Delete + Append)")

