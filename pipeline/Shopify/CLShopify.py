import pandas as pd
import numpy as np
from pipeline.Helpping.ShopifyFun import (
    map_product,
    map_payment,
    normalize_egypt_phone,
    clean_tags,
    extract_confirmation,
)


# =========================
# BUNDLE DETECTION & SPLITTING - OPTIMIZED VERSION
# =========================
def detect_and_split_bundles(df):
    """
    Detect bundles (SKU contains '+') and split them into separate rows
    Each product in bundle becomes a separate row with quantity = 1
    """
    if df is None or df.empty:
        return df

    df = df.copy()
    df['Is Bundle'] = False
    
    # Identify bundle rows
    bundle_mask = df['SKU'].astype(str).str.contains(r'\+', na=False)
    
    if not bundle_mask.any():
        return df
    
    # Separate bundles and non-bundles
    non_bundles = df[~bundle_mask].copy()
    bundles_df = df[bundle_mask].copy()
    
    # Pre-allocate list with estimated size
    expanded_rows = []
    expand_append = expanded_rows.append
    
    # Vectorized split of SKUs
    sku_lists = bundles_df['SKU'].astype(str).str.split(r'\s*\+\s*')
    n_items = sku_lists.str.len()
    
    # Process each bundle
    for idx in bundles_df.index:
        skus = sku_lists[idx]
        row = bundles_df.loc[idx]
        
        # Get product names - use list comprehension for speed
        products = [map_product({'SKU': s, 'Product': row.get('Product', s)}) for s in skus]
        
        # Handle Item Total
        total_str = str(row.get('Item Total', '')) if pd.notna(row.get('Item Total', '')) else ''
        
        if total_str and '+' in total_str:
            # Parse item totals
            parts = [p.strip() for p in total_str.split('+') if p.strip()]
            item_totals = []
            for part in parts:
                try:
                    clean_part = ''.join(c for c in part if c.isdigit() or c == '.')
                    item_totals.append(float(clean_part) if clean_part else 0)
                except:
                    item_totals.append(0)
        else:
            # Equal distribution
            clean_total = ''.join(c for c in total_str if c.isdigit() or c == '.')
            total_val = float(clean_total) if clean_total else 0
            item_totals = [total_val / len(skus)] * len(skus)
        
        # Ensure correct length
        while len(item_totals) < len(skus):
            item_totals.append(0)
        item_totals = item_totals[:len(skus)]
        
        # Create rows efficiently
        for i, sku in enumerate(skus):
            new_row = row.copy()
            new_row['SKU'] = sku
            new_row['Product'] = products[i]
            new_row['Quantity'] = 1
            new_row['Item Total'] = item_totals[i]
            new_row['Is Bundle'] = True
            expand_append(new_row)
    
    # Combine results
    if expanded_rows:
        expanded_df = pd.DataFrame(expanded_rows)
        result_df = pd.concat([non_bundles, expanded_df], ignore_index=True)
    else:
        result_df = non_bundles
    
    return result_df


# =========================
# GROUP ORDERS - OPTIMIZED WITH BETTER PERFORMANCE
# =========================
def group_shopify_orders(df):
    if df is None or df.empty:
        return df

    if 'Is Bundle' not in df.columns:
        df['Is Bundle'] = False

    # Use first and join aggregation for better performance
    agg_dict = {
        "Created Date": "first",
        "Week Name": "first",
        "Created Day": "first",
        "Created Hour": "first",
        "Discount Code": "first",
        "Discount Amount": "first",
        "Final Order Price": "first",
        "Fulfillment Status": "first",
        "Fulfilled Date": "first",
        "Fulfillment Hour": "first",
        "Fulfillment Days": "first",
        "Ctr Name": "first",
        "Phone": "first",
        "City": "first",
        "Shipping Carrier": "first",
        "Confirmation Status": "first",
        "Branch": "first",
        "Payment": "first",
        "Payment Status": "first",
        "Source Name": "first",
        "Updated At": "first",
        "Is Bundle": "first",
        "Product Type": "first",
        "AWB": lambda x: list(x.dropna().unique()),
    }
    
    # Convert to string and join in one step
    for col in ['SKU', 'Product', 'Quantity', 'Item Total']:
        if col in df.columns:
            df[f'{col}_str'] = df[col].astype(str)
            agg_dict[f'{col}_str'] = lambda x: ", ".join(x.dropna().astype(str))
    
    grouped = df.groupby("OrderID", as_index=False).agg(agg_dict)
    
    # Rename columns back
    for col in ['SKU', 'Product', 'Quantity', 'Item Total']:
        if f'{col}_str' in grouped.columns:
            grouped = grouped.rename(columns={f'{col}_str': col})
    
    if 'Is Bundle' not in grouped.columns:
        grouped['Is Bundle'] = False
    
    return grouped


# =========================
# CLEAN + TRANSFORM - HEAVILY OPTIMIZED
# =========================
def shopify_clean_df(df):
    if df is None or df.empty:
        return df

    df = df.copy()

    # =========================
    # NORMALIZE ORDER ID - VECTORIZED
    # =========================
    df["OrderID"] = (
        df["OrderID"]
        .astype(str)
        .str.strip()
        .str.replace("#", "", regex=False)
        .str.replace(".0", "", regex=False)
    )
    df = df[df["OrderID"].notna()]

    # =========================
    # ENSURE IS BUNDLE COLUMN EXISTS
    # =========================
    if 'Is Bundle' not in df.columns:
        df['Is Bundle'] = False

    # =========================
    # APPLY PRODUCT MAPPING - USE APPLY WITH REDUCED OVERHEAD
    # =========================
    if "Product" in df.columns and "SKU" in df.columns:
        # Use a more efficient approach
        def map_products(row):
            return map_product(row)
        df["Product"] = df.apply(map_products, axis=1)

    # =========================
    # PAYMENT MAPPING - VECTORIZED
    # =========================
    if "Payment" in df.columns:
        df["Payment"] = (
            df["Payment"]
            .map(map_payment)
            .fillna("COD")
            .astype(str)
            .str.strip()
        )

    # =========================
    # CITY MAPPING - VECTORIZED REPLACE
    # =========================
    if "City" in df.columns:
        df["City"] = df["City"].replace("Helwan", "Cairo")

    # =========================
    # PHONE NORMALIZATION - OPTIMIZED MAP
    # =========================
    if "Phone" in df.columns:
        df["Phone"] = df["Phone"].map(normalize_egypt_phone)

    # =========================
    # DATES - OPTIMIZED CONVERSION
    # =========================
    def convert_shopify_time(col):
        if col is not None and col in df.columns and df[col].notna().any():
            return (
                pd.to_datetime(df[col], utc=True, errors="coerce")
                .dt.tz_convert("Africa/Cairo")
                .dt.tz_localize(None)
            )
        return df[col] if col in df.columns else None

    if "Created Date" in df.columns:
        df["Created Date"] = convert_shopify_time("Created Date")

    if "Fulfilled Date" in df.columns:
        df["Fulfilled Date"] = convert_shopify_time("Fulfilled Date")

    if "Updated At" in df.columns:
        df["Updated At"] = convert_shopify_time("Updated At")

    if "Total Discount (Updated)" in df.columns:
        df["Discount Amount"] = df["Total Discount (Updated)"]
    elif "Discount Amount" not in df.columns:
        df["Discount Amount"] = 0.0

    # =========================
    # PRICE CALCULATION - OPTIMIZED
    # =========================
    numeric_cols = ["Product Price", "Shipping Cost", "Quantity", "Discount Amount"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Calculate Item Total
    if "Product Price" in df.columns and "Quantity" in df.columns:
        df["Item Total"] = df["Product Price"] * df["Quantity"]

    # Calculate Order Gross and Final Order Price
    if "OrderID" in df.columns and "Item Total" in df.columns:
        df["Order Gross"] = df.groupby("OrderID")["Item Total"].transform("sum")
        df["Final Order Price"] = (
            df["Order Gross"] + df["Shipping Cost"] - df["Discount Amount"]
        ).clip(lower=0)

    # =========================
    # DETECT AND SPLIT BUNDLES (AFTER PRICE CALCULATION)
    # =========================
    df = detect_and_split_bundles(df)

    # =========================
    # SORT BEFORE FILL - OPTIMIZED
    # =========================
    if "Created Date" in df.columns and df["Created Date"].notna().any():
        df = df.sort_values(["OrderID", "Created Date"], na_position="first")
    else:
        df = df.sort_values("OrderID", na_position="first")

    # =========================
    # TAGS - VECTORIZED
    # =========================
    if "Tags" in df.columns:
        df["Tags List"] = df["Tags"].map(clean_tags)
    else:
        df["Tags List"] = [[] for _ in range(len(df))]

    df["Confirmation Status"] = df["Tags List"].map(extract_confirmation)

    # =========================
    # DATE FEATURES - OPTIMIZED
    # =========================
    if "Created Date" in df.columns and df["Created Date"].notna().any():
        created_dt = pd.to_datetime(df["Created Date"], errors="coerce")
        df["Created Hour"] = created_dt.dt.strftime("%H:%M")
        df["Created Day"] = created_dt.dt.strftime("%a")
        week = ((created_dt.dt.day - 1) // 7 + 1).clip(upper=4)
        df["Week Name"] = "Week " + week.astype(str)
    else:
        df[["Created Hour", "Created Day", "Week Name"]] = None

    # =========================
    # FULFILLMENT - OPTIMIZED
    # =========================
    if "Fulfilled Date" in df.columns and "Created Date" in df.columns:
        today_date = pd.Timestamp.now(tz="Africa/Cairo").date()
        fulfilled_dt = pd.to_datetime(df["Fulfilled Date"], errors="coerce")
        created_dt = pd.to_datetime(df["Created Date"], errors="coerce")

        # Today mask
        today_mask = (
            fulfilled_dt.notna() &
            (fulfilled_dt.dt.date == today_date) &
            (fulfilled_dt.dt.hour >= 14) &
            (df["Confirmation Status"] == "Confirmed")
        )
        
        if today_mask.any():
            df.loc[today_mask, "Fulfilled Date"] = fulfilled_dt[today_mask] + pd.Timedelta(days=1)

        # Fulfillment Days
        valid_mask = fulfilled_dt.notna() & created_dt.notna()
        if valid_mask.any():
            df.loc[valid_mask, "Fulfillment Days"] = (
                (fulfilled_dt[valid_mask] - created_dt[valid_mask])
                .dt.days
                .clip(lower=0)
            )
        if "Fulfillment Days" in df.columns:
            df["Fulfillment Days"] = df["Fulfillment Days"].fillna(0)
        else:
            df["Fulfillment Days"] = 0

        # Fulfillment Hour
        df["Fulfillment Hour"] = fulfilled_dt.dt.strftime("%H:%M")

        # Item Fulfillment
        if "Item Fulfillment" not in df.columns:
            df["Item Fulfillment"] = "unfulfilled"

        if "Fulfillment Status" in df.columns:
            mask = df["Fulfillment Status"].astype(str).str.lower() == "fulfilled"
            df.loc[mask, "Item Fulfillment"] = "fulfilled"

    # =========================
    # FINAL CLEAN - VECTORIZED
    # =========================
    df = df.replace({pd.NA: None, np.nan: None})

    # =========================
    # DATE ONLY FOR DATABASE - OPTIMIZED
    # =========================
    for col in ["Created Date", "Fulfilled Date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce").dt.date

    # =========================
    # ENSURE IS BUNDLE COLUMN EXISTS
    # =========================
    if 'Is Bundle' not in df.columns:
        df['Is Bundle'] = False

    # =========================
    # OUTPUT COLUMNS - USE REINDEX FOR SPEED
    # =========================
    OUTPUT_COLUMNS = [
        "OrderID", "Created Date", "Week Name", "Created Day", "Created Hour",
        "SKU", "Product", "Quantity", "Product Type", "Item Total", "Discount Code", "Discount Amount",
        "Final Order Price", "Fulfillment Status", "Item Fulfillment",
        "Fulfilled Date", "Fulfillment Hour", "Fulfillment Days", "Ctr Name",
        "Phone", "City", "Shipping Carrier", "Confirmation Status", "Branch", "Source Name",
        "Payment", "Payment Status", "AWB", "Updated At", "Is Bundle"
    ]

    # Add missing columns efficiently
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[OUTPUT_COLUMNS]