# main.py
from pathlib import Path
import pandas as pd
from pipeline.Shopify.get_shopify_data import fetch_shopify_orders_graphql
from pipeline.Shopify.CLShopify import shopify_clean_df,group_shopify_orders
from pipeline.Shopify.DBManage import sync_to_supabase_shopify,get_last_updated_date
from datetime import datetime
from pipeline.Shopify.MergeWH_Shopify import (
    auth,
    load_sheet,
    filter_shopify,
    filter_warehouse,
    full_join,
    fast_update
)

# =========================
# SETTINGS
# =========================
date_field = "updated_at"  # created_at / updated_at
include_cancelled=True

Custom_date = datetime.strptime(
    "2026-0-01",
    "%Y-%m-%d"
).strftime("%Y-%m-%dT%H:%M:%SZ")

Updated_date = get_last_updated_date()

RUN_SHOPIFY = True
RUN_Merge = False

start_date_merge = "2025-03-01"

BASE_DIR = Path(__file__).resolve().parent

client = auth(BASE_DIR)

# ===== 3️⃣ سحب البيانات من Shopify =====
if RUN_SHOPIFY:
    print("...fetching Shopify orders...")
    df_orders = fetch_shopify_orders_graphql(Updated_date,date_field,include_cancelled)
else:
    print("Shopify fetch SKIPPED (FROZEN MODE)")
    df_orders = pd.DataFrame()

# ===== 3.1️⃣ حماية الطباعة =====
if not df_orders.empty:
    print(f"Fetched {len(df_orders)} orders | Columns: {len(df_orders.columns)}")
else:
    print("No Shopify data loaded")

# ===== 4️⃣ تنظيف وتجهيز البيانات =====
if RUN_SHOPIFY and not df_orders.empty:
    print("...Cleaning Shopify data...")
    df_clean = shopify_clean_df(df_orders)

    grouped_df = group_shopify_orders(df_clean)
    grouped_df.to_csv("shopify.csv", 
                  index=False, 
                  encoding="utf-8-sig",
                  compression=None)

    print(f"Data cleaned: {len(grouped_df)} orders")

    if client and df_clean is not None:
        sync_to_supabase_shopify(grouped_df)
        
        print("Data synced to Google Sheet")
    else:
        print("Google Sheets sync skipped (no data or credentials)")
    
    print("...Loading Shopify & Warehouse sheets...")

else:
    print("Cleaning SKIPPED")
    grouped_df = None


if RUN_Merge:
    
    shopify_df = load_sheet(
        client,
        sheet_id="1B2nktYv4HbZudu2XNHhPlB7gsaKFfdArIuyESlcfv7c",
        sheet_name="Shopify Data",
        col_map={
            "OrderID": "OrderID",
            "Created Date": "Created Date",
            "Final Order Price": "Price",
            "Payment": "Payment",
            "Discount Code": "Disc Code",
            "Phone": "Phone",
            "Discount Amount": "Disc Amount",
            "Created Day": "Day",
            "Created Hour": "Hour",
            "Confirmation Status": "Confirm Status",
            "City": "City"
        }
    )
    
    warehouse_df = load_sheet(
        client,
        sheet_id="12q_q7lU_zPRaywuTP3mVkliYEl_SM8WNl0wFi5bMC2Y",
        sheet_name="Warehouse Shipping",
        col_map={
            "OrderID": "OrderID",
            "Date": "Warehouse Date",
            "Product": "WH Product",
            "Quantity": "WH Quantity",
            "AWB": "AWB",
            "Return AWB": "RT AWB",
            "Status": "Status",
            "Status Date": "Status Date",
            "Transit Days": "Transit Days",
            "Return Date": "RT Date",
            "Return Days": "RT Days",
            "Problem Reason": "Problem Reason",
            "Shipped With": "Shipped With",
            "Type": "Type",
            "Reshipping - New": "Reshipping",
            "Escalation - OPS": "OPS-Flags",
            "Delivery Classification": "Delivery Status",
            "Number Of attempts": "Attempts"
        }
    )
    
    # ===== 8️⃣ فلترة =====
    date_filter = pd.to_datetime(start_date_merge)
    
    shopify_df = filter_shopify(shopify_df, date_filter)
    warehouse_df = filter_warehouse(warehouse_df, date_filter)
    
    # ===== 9️⃣ دمج =====
    print("...Merging data...")
    merged_df = full_join(shopify_df, warehouse_df)
    
    print(f"Merged rows: {len(merged_df)}")
    
    # ===== 🔟 رفع الناتج النهائي =====
    
    fast_update(client, merged_df)
else:
    print("Merging SKIPPED")

print("All done")
