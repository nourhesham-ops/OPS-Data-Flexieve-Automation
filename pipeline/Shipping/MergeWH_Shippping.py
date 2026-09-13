import os

import pandas as pd
import numpy as np
import gspread
import psycopg2

from dotenv import load_dotenv

from pipeline.Helpping.HelppingFun import (
    clean_product,
    parse_mixed_date,
    normalize_awb,
)


load_dotenv()


# ============================================================
# DATABASE
# ============================================================

DB_URL = os.getenv("DB_URL_Shipping")


# ============================================================
# NDR LOGIC
# ============================================================

# ========================================================
# NDR LOGIC
# ========================================================

def determine_ndr(row):

    order_date = row.get("Date")
    status_date = row.get("Status Date")

    status = str(
        row.get("Status", "")
    ).strip()

    shipment_type = str(
        row.get("Shipment Type", "")
    ).strip()

    problem_reason = str(
        row.get("Problem Reason", "")
    ).strip()

    # ========================================================
    # CLOSED STATUSES
    # NDR لا ينطبق على الشحنات المقفولة
    # ========================================================

    closed_statuses = [
        "Delivered",
        "Returned",
        "Exchanged",
        "Lost"
    ]

    if status in closed_statuses:
        return ""

    # ========================================================
    # ALLOWED DAYS BY SHIPMENT TYPE
    # ========================================================

    if shipment_type == "Outbound":

        allowed_days = 3

    elif shipment_type == "Exchange Request":

        allowed_days = 4

    else:

        return ""

    # ========================================================
    # PROBLEM REASON
    # ========================================================

    if problem_reason not in [
        "",
        "nan",
        "None"
    ]:

        return "Failed Attempt"

    # ========================================================
    # MISSING DATES
    # ========================================================

    if pd.isna(order_date) or pd.isna(status_date):
        return ""

    # ========================================================
    # CALCULATE DAYS
    # ========================================================

    try:

        order_date = pd.to_datetime(
            order_date
        )

        status_date = pd.to_datetime(
            status_date
        )

        days_passed = (
            status_date - order_date
        ).days

    except Exception:

        return ""

    # ========================================================
    # NDR BY SLA
    # ========================================================

    if (
            status in ["In Progress", "Not Found"]

        and days_passed > allowed_days
    ):

        return "Failed Attempt"

    return ""



# ============================================================
# GOOGLE SHEET LOADER
# ============================================================

def load_worksheet(
    client,
    sheet_id,
    sheet_name,
    date_filters=None,
    start_date=None
):

    """
    Optimized Google Sheet loader.

    Uses get_all_values() instead of get_all_cells().
    """

    ws = (
        client
        .open_by_key(sheet_id)
        .worksheet(sheet_name)
    )

    all_data = ws.get_all_values()

    if (
        not all_data
        or len(all_data) <= 1
    ):

        return pd.DataFrame()

    # --------------------------------------------------------
    # Headers
    # --------------------------------------------------------

    headers = all_data[0]

    data = all_data[1:]

    df = pd.DataFrame(
        data,
        columns=headers
    )

    # --------------------------------------------------------
    # AWB
    # --------------------------------------------------------

    for col in [
        "AWB",
        "Return AWB"
    ]:

        if col in df.columns:

            df[col] = normalize_awb(
                df[col]
            )

    # --------------------------------------------------------
    # Phone
    # --------------------------------------------------------

    if "Phone" in df.columns:

        df["Phone"] = (
            df["Phone"]
            .astype(str)
            .str.strip()
            .replace(
                [
                    "nan",
                    "None",
                    ""
                ],
                ""
            )
        )

    # --------------------------------------------------------
    # Dates
    # --------------------------------------------------------

    if date_filters and start_date:

        start_date_parsed = pd.to_datetime(
            start_date,
            dayfirst=True
        )

        if sheet_name == "Shipping Companies":

            start_date_parsed = (
                start_date_parsed
                - pd.DateOffset(months=1)
            )

        mask = pd.Series(
            False,
            index=df.index
        )

        for col in date_filters:

            if col in df.columns:

                df[col] = parse_mixed_date(
                    df[col]
                )

                mask = (
                    mask
                    | (
                        df[col]
                        >= start_date_parsed
                    )
                )

        df = df[mask]

    elif date_filters:

        for col in date_filters:

            if col in df.columns:

                df[col] = parse_mixed_date(
                    df[col]
                )

    return df


# ============================================================
# DATABASE LOADER
# ============================================================

def load_data_from_db(
    db_url,
    table_name,
    start_date=None,
    date_columns=None
):

    """
    Generic DB loader.

    Works for both:

        shipments
        orders

    Example:

        load_data_from_db(
            DB_URL_Shipping,
            "shipments",
            "2026-01-01",
            ["Date Shipped"]
        )

    or:

        load_data_from_db(
            DB_URL_Orders,
            "orders",
            "2026-01-01",
            ["Date"]
        )
    """

    query = f"""
        SELECT *
        FROM {table_name}
    """

    # --------------------------------------------------------
    # Validate DB URL
    # --------------------------------------------------------

    if not db_url:

        raise ValueError(
            f"Database URL is missing for table: {table_name}"
        )

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    with psycopg2.connect(db_url) as conn:

        df = pd.read_sql_query(
            query,
            conn
        )

    # ========================================================
    # CLEAN AWB
    # ========================================================

    if "AWB" in df.columns:

        df["AWB"] = (
            df["AWB"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # CLEAN RETURN AWB
    # ========================================================

    if "Return AWB" in df.columns:

        df["Return AWB"] = (
            df["Return AWB"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # CLEAN PHONE
    # ========================================================

    if "Phone" in df.columns:

        df["Phone"] = (
            df["Phone"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # DATE CONVERSION
    # ========================================================

    if date_columns:

        for col in date_columns:

            if col in df.columns:

                df[col] = pd.to_datetime(
                    df[col],
                    errors="coerce"
                )

    # ========================================================
    # DATE FILTER
    # ========================================================

    if (
        start_date
        and date_columns
    ):

        start_date_parsed = pd.to_datetime(
            start_date
        )

        masks = []

        for col in date_columns:

            if col in df.columns:

                masks.append(
                    df[col]
                    >= start_date_parsed
                )

        if masks:

            mask = masks[0]

            for current_mask in masks[1:]:

                mask = (
                    mask
                    | current_mask
                )

            df = df[mask]

    return df.reset_index(
        drop=True
    )


# ============================================================
# MERGE SHIPPING + WAREHOUSE
# ============================================================

def merge_shipping_with_warehouse(
    shipping_df,
    warehouse_df
):

    # ========================================================
    # COPY
    # ========================================================

    shipping_df = shipping_df.copy()

    warehouse_df = warehouse_df.copy()

    # ========================================================
    # AWB
    # ========================================================

    if "AWB" not in shipping_df.columns:

        raise KeyError(
            "Shipping data does not contain 'AWB'"
        )

    if "AWB" not in warehouse_df.columns:

        raise KeyError(
            "Warehouse data does not contain 'AWB'"
        )

    shipping_df["AWB"] = (
        shipping_df["AWB"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    warehouse_df["AWB"] = (
        warehouse_df["AWB"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # ========================================================
    # DATE CONVERSION
    # ========================================================

    if "Date" in warehouse_df.columns:

        warehouse_df["Date"] = pd.to_datetime(
            warehouse_df["Date"],
            errors="coerce"
        )

    if "Date Shipped" in shipping_df.columns:

        shipping_df["Date Shipped"] = pd.to_datetime(
            shipping_df["Date Shipped"],
            errors="coerce"
        )

    if "Status Date" in shipping_df.columns:

        shipping_df["Status Date"] = pd.to_datetime(
            shipping_df["Status Date"],
            errors="coerce"
        )

    # ========================================================
    # WAREHOUSE COLUMNS
    # ========================================================

    warehouse_cols = [
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

    # Only existing columns

    warehouse_cols = [
        col
        for col in warehouse_cols
        if col in warehouse_df.columns
    ]

    warehouse_df = warehouse_df[
        warehouse_cols
    ]

    # ========================================================
    # SHIPPING COLUMNS
    # ========================================================

    shipping_cols = [
        "Date Shipped",
        "Return AWB",
        "OrderID",
        "AWB",
        "Status",
        "Status Date",
        "Flyers Cost",
        "Phone",
        "Shipping Company",
        "Number Of attempts",
        "Problem Reason",
        "Payment Type",
        "COD Value",
        "Reshipping - New",
        "Shipment Type",
        "Shipping Cost",
    ]

    # Only existing columns

    shipping_cols = [
        col
        for col in shipping_cols
        if col in shipping_df.columns
    ]

    shipping_df = shipping_df[
        shipping_cols
    ]

    # ========================================================
    # RENAME DUPLICATE COLUMNS
    # ========================================================

    warehouse_rename = {}

    for col in [
        "OrderID",
        "Payment Type",
        "Status"
    ]:

        if col in warehouse_df.columns:

            warehouse_rename[col] = (
                f"{col}_WH"
            )

    warehouse_df = warehouse_df.rename(
        columns=warehouse_rename
    )

    # --------------------------------------------------------

    shipping_rename = {}

    for col in [
        "OrderID",
        "Payment Type",
        "Status"
    ]:

        if col in shipping_df.columns:

            shipping_rename[col] = (
                f"{col}_Shipping"
            )

    shipping_df = shipping_df.rename(
        columns=shipping_rename
    )

    # ========================================================
    # MERGE
    # ========================================================

    merged_df = pd.merge(
        warehouse_df,
        shipping_df,
        on="AWB",
        how="outer",
        indicator=True
    )

    # ========================================================
    # DATA SOURCE
    # ========================================================

    merged_df["Data Source"] = (
        merged_df["_merge"]
        .map({
            "left_only": "Warehouse Only",
            "right_only": "Shipping",
            "both": "WH-Shipping"
        })
    )

    merged_df.drop(
        columns=["_merge"],
        inplace=True
    )

    # ========================================================
    # ORDER ID
    # ========================================================

    if "OrderID_WH" in merged_df.columns:

        merged_df["OrderID"] = (
            merged_df["OrderID_WH"]
            .fillna("")
            .astype(str)
        )

    else:

        merged_df["OrderID"] = ""

    if "OrderID_Shipping" in merged_df.columns:

        mask = merged_df["OrderID"].isin(
            [
                "",
                "nan",
                "None"
            ]
        )

        merged_df.loc[
            mask,
            "OrderID"
        ] = (
            merged_df.loc[
                mask,
                "OrderID_Shipping"
            ]
            .fillna("")
            .astype(str)
        )

    # ========================================================
    # STATUS
    # ========================================================
    #
    # Shipping status has priority.
    # If it is empty, use Warehouse status.
    #

    if "Status_Shipping" in merged_df.columns:

        merged_df["Status"] = (
            merged_df["Status_Shipping"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    else:

        merged_df["Status"] = ""

    if "Status_WH" in merged_df.columns:

        mask = merged_df["Status"].isin(
            [
                "",
                "nan",
                "None"
            ]
        )

        merged_df.loc[
            mask,
            "Status"
        ] = (
            merged_df.loc[
                mask,
                "Status_WH"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # PAYMENT TYPE
    # ========================================================

    if "Payment Type_Shipping" in merged_df.columns:

        merged_df["Payment Type"] = (
            merged_df["Payment Type_Shipping"]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    else:

        merged_df["Payment Type"] = ""

    if "Payment Type_WH" in merged_df.columns:

        mask = merged_df[
            "Payment Type"
        ].isin(
            [
                "",
                "nan",
                "None"
            ]
        )

        merged_df.loc[
            mask,
            "Payment Type"
        ] = (
            merged_df.loc[
                mask,
                "Payment Type_WH"
            ]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    # ========================================================
    # DATE
    # ========================================================

    if "Date" not in merged_df.columns:

        merged_df["Date"] = pd.NaT

    if "Date Shipped" not in merged_df.columns:

        merged_df["Date Shipped"] = pd.NaT

    merged_df["Date"] = pd.to_datetime(
        merged_df["Date"],
        errors="coerce"
    )

    merged_df["Date Shipped"] = pd.to_datetime(
        merged_df["Date Shipped"],
        errors="coerce"
    )

    # Use shipping date if warehouse date is missing

    merged_df["Date"] = (
        merged_df["Date"]
        .fillna(
            merged_df["Date Shipped"]
        )
    )

    # ========================================================
    # STATUS DATE
    # ========================================================

    if "Status Date" not in merged_df.columns:

        merged_df["Status Date"] = pd.NaT

    merged_df["Status Date"] = pd.to_datetime(
        merged_df["Status Date"],
        errors="coerce"
    )

    # ========================================================
    # RETURN AWB
    # ========================================================

    if "Return AWB" not in merged_df.columns:

        merged_df["Return AWB"] = ""

    # ========================================================
    # PHONE
    # ========================================================

    if "Phone" not in merged_df.columns:

        merged_df["Phone"] = ""

    # ========================================================
    # SHIPPING COST
    # ========================================================

    if "Shipping Cost" not in merged_df.columns:

        merged_df["Shipping Cost"] = 0

    if "Flyers Cost" not in merged_df.columns:

        merged_df["Flyers Cost"] = 0

    merged_df["Shipping Cost"] = pd.to_numeric(
        merged_df["Shipping Cost"],
        errors="coerce"
    ).fillna(0)

    merged_df["Flyers Cost"] = pd.to_numeric(
        merged_df["Flyers Cost"],
        errors="coerce"
    ).fillna(0)

    merged_df["Shipping Cost"] = (
        merged_df["Shipping Cost"]
        + merged_df["Flyers Cost"]
    )

    # ========================================================
    # TRANSIT DAYS
    # ========================================================

    merged_df["Transit Days"] = (
        merged_df["Status Date"]
        - merged_df["Date"]
    ).dt.days

    # ========================================================
    # SHIPMENT TYPE
    # ========================================================

    if "Shipment Type" not in merged_df.columns:

        merged_df["Shipment Type"] = ""

    # ========================================================
    # PROBLEM REASON
    # ========================================================

    if "Problem Reason" not in merged_df.columns:

        merged_df["Problem Reason"] = ""


    # ========================================================
    # NDR
    # ========================================================
    
    merged_df["NDR"] = merged_df.apply(
        determine_ndr,
        axis=1
    )


    # ========================================================
    # DELIVERY CLASSIFICATION
    # ========================================================

    merged_df[
        "Delivery Classification"
    ] = ""

    # --------------------------------------------------------
    # Lost
    # --------------------------------------------------------

    lost_mask = (
        merged_df["Status"]
        .astype(str)
        .str.strip()
        == "Lost"
    )

    # --------------------------------------------------------
    # In Progress / OFR
    # --------------------------------------------------------

    on_time_1_mask = (
        merged_df["Status"].isin(
            [
                "In Progress",
                "OFR"
            ]
        )
        &
        (
            merged_df["Transit Days"]
            <= 3
        )
    )

    delayed_1_mask = (
        merged_df["Status"].isin(
            [
                "In Progress",
                "OFR"
            ]
        )
        &
        (
            merged_df["Transit Days"]
            > 3
        )
    )

    # --------------------------------------------------------
    # Exchanged
    # --------------------------------------------------------

    on_time_2_mask = (
        merged_df["Status"]
        == "Exchanged"
    ) & (
        merged_df["Transit Days"]
        <= 5
    )

    delayed_2_mask = (
        merged_df["Status"]
        == "Exchanged"
    ) & (
        merged_df["Transit Days"]
        > 5
    )

    # --------------------------------------------------------
    # Delivered / Returned
    # --------------------------------------------------------

    on_time_3_mask = (
        merged_df["Status"].isin(
            [
                "Delivered",
                "Returned"
            ]
        )
        &
        (
            merged_df["Transit Days"]
            <= 3
        )
    )

    delayed_3_mask = (
        merged_df["Status"].isin(
            [
                "Delivered",
                "Returned"
            ]
        )
        &
        (
            merged_df["Transit Days"]
            > 3
        )
    )

    # ========================================================
    # APPLY CLASSIFICATION
    # ========================================================

    merged_df.loc[
        lost_mask,
        "Delivery Classification"
    ] = "Lost"

    merged_df.loc[
        (
            on_time_1_mask
            | on_time_2_mask
            | on_time_3_mask
        ),
        "Delivery Classification"
    ] = "On Time"

    merged_df.loc[
        (
            delayed_1_mask
            | delayed_2_mask
            | delayed_3_mask
        ),
        "Delivery Classification"
    ] = "Delayed"

    # ========================================================
    # FINAL COLUMNS
    # ========================================================

    final_cols = [
    "Date",
    "AWB",
    "Return AWB",
    "OrderID",
    "Date Shipped",
    "Status",
    "Status Date",
    "Shipping Cost",
    "Transit Days",
    "Delivery Classification",
    "Phone",
    "Quantity",
    "Product",
    "Number Of attempts",
    "Problem Reason",
    "Payment Type",
    "NDR",
    "COD Value",
    "Shipping Company",
    "Shipment Type",
    "Data Source",

    "Order Status",
    "Order Count",
    "Invoiced",
    "Online Payment",
    "Price Excl Tax",
    "Price Incl Tax",
    "Net Price",
    "City",
]

    # ========================================================
    # ADD MISSING COLUMNS
    # ========================================================

    for col in final_cols:

        if col not in merged_df.columns:

            merged_df[col] = ""

    # ========================================================
    # FINAL SELECTION
    # ========================================================

    merged_df = merged_df[
        final_cols
    ]

    # ========================================================
    # REMOVE DUPLICATE AWB
    # ========================================================

    merged_df = (
        merged_df
        .drop_duplicates(
            subset=["AWB"],
            keep="last"
        )
    )

    # ========================================================
    # SORT
    # ========================================================

    merged_df = merged_df.sort_values(
        by=[
            "Date",
            "Status Date"
        ],
        ascending=[
            True,
            True
        ],
        na_position="last"
    )

    # ========================================================
    # FORMAT DATES
    # ========================================================

    merged_df["Date"] = (
        pd.to_datetime(
            merged_df["Date"],
            errors="coerce"
        )
        .dt.strftime(
            "%Y-%m-%d"
        )
    )

    merged_df["Date Shipped"] = (
        pd.to_datetime(
            merged_df["Date Shipped"],
            errors="coerce"
        )
        .dt.strftime(
            "%Y-%m-%d"
        )
    )

    merged_df["Status Date"] = (
        pd.to_datetime(
            merged_df["Status Date"],
            errors="coerce"
        )
        .dt.strftime(
            "%Y-%m-%d"
        )
    )

    return merged_df


# ============================================================
# GOOGLE SHEET WRITER
# ============================================================
def create_or_update_worksheet(
    client,
    sheet_id,
    sheet_name,
    new_df
):

    spreadsheet = (
        client
        .open_by_key(sheet_id)
    )

    ws = (
        spreadsheet
        .worksheet(sheet_name)
    )

    # ========================================================
    # EMPTY DATA
    # ========================================================

    if new_df is None or len(new_df) == 0:

        ws.update(
            "A1",
            [["لا توجد بيانات"]],
            value_input_option="USER_ENTERED"
        )

        ws.batch_clear(
            ["A2:ZZ100000"]
        )

        return

    # ========================================================
    # SORT
    # ========================================================

    new_df = new_df.copy()

    new_df["Date_temp"] = pd.to_datetime(
        new_df["Date"],
        errors="coerce"
    )

    new_df = new_df.sort_values(
        "Date_temp",
        ascending=False
    )

    new_df = new_df.drop(
        columns=["Date_temp"]
    )

    # ========================================================
    # PREPARE DATA
    # ========================================================

    # Convert Categorical columns to object
    # before replacing NaN with ""

    new_df = new_df.astype(object)

    # Replace NaN / NaT / None
    # without triggering Categorical errors

    new_df = new_df.where(
        pd.notna(new_df),
        ""
    )

    # Convert everything to string

    data = [
        new_df.columns.tolist()
    ] + (
        new_df
        .astype(str)
        .values
        .tolist()
    )

    # ========================================================
    # UPDATE
    # ========================================================

    ws.update(
        "A1",
        data,
        value_input_option="USER_ENTERED"
    )

    # ========================================================
    # CLEAR OLD ROWS
    # ========================================================

    current_rows = len(
        ws.get_all_values()
    )

    new_rows = len(data)

    if current_rows > new_rows:

        ws.batch_clear(
            [
                f"A{new_rows + 1}:ZZ{current_rows}"
            ]
        )
