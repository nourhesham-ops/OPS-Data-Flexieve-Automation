import pandas as pd
import numpy as np
from pathlib import Path
import os

from pipeline.Helpping.HelppingFun import (
    normalize_egypt_phone,
    normalize_problem_reason,
    parse_dates,
    repair_excel_aggressive,
    unify_cities,
)


PRIMARY_KEY = "AWB"
STATUS_DATE_COL = "Status Date"


# ============================================================
# STATUS MAPS
# ============================================================

STATUS_MAPS = {
    "Mylerz": {
        "Delivered": "Delivered",
        "Returned": "Returned",
        "In Progress": "In Progress",
        "Undelivered": "OFR",
    },

    "Aramex": {
        "Delivered": "Delivered",
        "Paid": "Delivered",
        "Data Received": "Order Created",
        "Returned": "Returned",
        "Customer Has Refused The Shipment": "OFR",
        "Still At Origin": "In Progress",
        "Out For Delivery": "Out For Delivery",
        "Held For Pickup": "In Progress",
        "At Destination Facility": "In Progress",
        "Address Acquired": "In Progress",
        "Lost": "Lost",
    },

    "Bosta": {
        "Delivered": "Delivered",
        "Created": "Order Created",
        "Returned": "Returned",
        "Rejected Return": "OFR",
        "Lost": "Lost",
        "Canceled": "OFR",
        "Requested": "In Progress",
        "Returned to origin": "Returned",
        "Received at warehouse": "In Progress",
        "Ready to Dispatch": "In Progress",
        "Out for delivery": "Out For Delivery",
        "Out for pickup": "In Progress",
        "On hold": "In Progress",
        "Picked up": "In Progress",
        "In transit between hubs": "In Progress",
        "Received at warehouse-On Hold": "In Progress",
        "Picked up from business": "In Progress",
        "Picked up from consignee": "In Progress",
        "Route assigned": "In Progress",
        "Exception": "In Progress",
        "Exchanged & Returned": "Exchanged",
        "Out for return": "OFR",
        "Not Found": "Not Found",
    },
}


# ============================================================
# LOAD + CLEAN SINGLE SHIPPING FILE
# ============================================================

def load_clean_sheet(path, company):

    if not path.exists():
        return pd.DataFrame()

    # ========================================================
    # READ FILE
    # ========================================================

    try:
        df = pd.read_excel(
            path,
            engine="openpyxl"
        )

    except ValueError:

        fixed_path = repair_excel_aggressive(path)

        try:
            df = pd.read_excel(
                fixed_path,
                engine="openpyxl"
            )

            try:
                os.remove(fixed_path)
            except Exception:
                pass

        except Exception as e:
            print(
                f"Failed to read {company} even after repair: {e}"
            )
            return pd.DataFrame()

    # ========================================================
    # CONFIG
    # ========================================================

    status_map = STATUS_MAPS.get(company, {})

    date_fmts = [
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]

    cols_map = {}

    # ========================================================
    # MYLERZ
    # ========================================================

    if company == "Mylerz":

        mask = df.astype(str).apply(
            lambda x: x.str.contains(
                "Reference Number",
                case=False,
                na=False
            )
        )

        if mask.any().any():

            header_idx = df[
                mask.any(axis=1)
            ].index[0]

            df.columns = df.iloc[header_idx]

            df = df.iloc[header_idx + 1:]

            if len(df) > 2:
                df = df.iloc[:-2]

        cols_map = {
            "Reference Number": "OrderID",
            "Tracking Number": "AWB",
            "Destination Hub": "HUB",
            "Rescheduled/Rejection Reason": "Problem Reason",
            "COD": "COD Value",
            "Pick-Up Date": "Date Shipped",
            "Number of Attempts": "Number Of attempts",
            "Status Date": "Status Date",
            "Customer Mobile": "Phone",
            "Description": "Product",
        }

        if "Reference Number" in df.columns:
            df["Reference Number"] = (
                df["Reference Number"]
                .astype(str)
                .str.replace("#", "", regex=False)
            )

        df["Payment Type"] = np.where(
            pd.to_numeric(
                df.get(
                    "COD",
                    pd.Series(0, index=df.index)
                ),
                errors="coerce"
            ).fillna(0) == 0,
            "Paid",
            "COD"
        )

        date_fmts = [
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y",
        ]

        df["Shipment Type"] = "Outbound"

    # ========================================================
    # ARAMEX
    # ========================================================

    elif company == "Aramex":

        try:

            df = pd.read_excel(
                path,
                sheet_name="Detailed Data",
                engine="openpyxl",
                converters={
                    "Return AWB Number": (
                        lambda x:
                        str(x).replace(".0", "")
                        if pd.notna(x)
                        else ""
                    ),

                    "Shipper Reference": (
                        lambda x:
                        str(x).replace("#", "")
                        if pd.notna(x)
                        else ""
                    ),
                }
            )

        except Exception as e:

            print(
                f"Failed to read Aramex file: {e}"
            )

            return pd.DataFrame()

        cols_map = {
            "Shipper Reference": "OrderID",
            "Last Status Action Date": "Status Date",
            "Last Attempted Delivery Problem Code": "Problem Reason",
            "Pickup Date (Creation Date)": "Date Shipped",
            "Destination City": "HUB",
            "Return AWB Number": "Return AWB",
            "Total Delivery Attempts": "Number Of attempts",
            "Consignee Phone Number": "Phone",
            "ConsigneeName": "CST Name",
            "Commodity Description": "Product",
        }

        df["Payment Type"] = np.where(
            pd.to_numeric(
                df.get(
                    "COD Value",
                    pd.Series(0, index=df.index)
                ),
                errors="coerce"
            ).fillna(0) == 0,
            "Paid",
            "COD"
        )

        df["Shipment Type"] = np.where(
            df["AWB"]
            .astype(str)
            .isin(
                df["Return AWB Number"]
                .astype(str)
            ),
            "Return Request",
            "Outbound"
        )

    # ========================================================
    # BOSTA
    # ========================================================

    elif company == "Bosta":

        cols_map = {
            "Delivery State": "Status",
            "Tracking Number": "AWB",
            "Business Reference Number": "OrderID",
            "Latest Exception Reason": "Problem Reason",
            "Updated at": "Status Date",
            "Created At": "Date Shipped",
            "DropOff City": "HUB",
            "Cod Amount": "COD Value",
            "Consignee phone": "Phone",
            "Consignee Name": "CST Name",
            "Description": "Product",
        }

        if "Business Reference Number" in df.columns:

            df["Business Reference Number"] = (
                df["Business Reference Number"]
                .replace(
                    {
                        r"#": "",
                        r"chandbe:": "",
                    },
                    regex=True
                )
            )

        df["Payment Type"] = np.where(
            pd.to_numeric(
                df.get(
                    "Cod Amount",
                    pd.Series(0, index=df.index)
                ),
                errors="coerce"
            ).fillna(0) == 0,
            "Paid",
            "COD"
        )

        date_fmts = [
            "%m-%d-%Y, %H:%M:%S",
            "%m-%d-%Y",
            "%d-%m-%Y",
        ]

        # ----------------------------------------------------
        # Shipment Type
        # ----------------------------------------------------

        conditions = [
            df["Type"] == "CUSTOMER_RETURN_PICKUP",
            df["Type"] == "EXCHANGE_return",
        ]

        choices = [
            "Return Request",
            "Exchange Request",
        ]

        df["Shipment Type"] = np.select(
            conditions,
            choices,
            default="Outbound"
        )

    # ========================================================
    # RENAME COLUMNS
    # ========================================================

    df = df.rename(columns=cols_map)

    # ========================================================
    # REQUIRED COLUMNS
    # ========================================================

    req_cols = [
        "AWB",
        "Return AWB",
        "OrderID",
        "CST Name",
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
    ]

    for c in req_cols:

        if c not in df.columns:
            df[c] = pd.NA

    df = df[req_cols].copy()

    # ========================================================
    # BASIC CLEANING
    # ========================================================

    df["Phone"] = df["Phone"].apply(
        normalize_egypt_phone
    )


    df["Shipping Company"] = company

    df["Problem Reason"] = (
        df["Problem Reason"]
        .apply(normalize_problem_reason)
    )

    # ========================================================
    # NORMALIZE STATUSES
    # ========================================================

    # Keep original status for detecting unknown statuses
    original_statuses = (
        df["Status"]
        .astype("string")
        .str.strip()
    )

    # Apply mapping
    df["Status"] = original_statuses.replace(
        status_map
    )

    known_statuses = set(
        status_map.values()
    )

    # --------------------------------------------------------
    # Detect unknown statuses BEFORE replacing them
    # --------------------------------------------------------

    unknown_mask = ~df["Status"].isin(
        known_statuses
    )

    unknown_statuses = (
        df.loc[
            unknown_mask,
            "Status"
        ]
        .dropna()
        .unique()
    )

    if len(unknown_statuses) > 0:

        print(
            f"⚠️ New / Unknown statuses detected "
            f"for {company}: {unknown_statuses}"
        )

        # Unknown statuses become In Progress
        df.loc[
            unknown_mask,
            "Status"
        ] = "In Progress"

    # ========================================================
    # PARSE STATUS DATE
    # ========================================================

    # IMPORTANT:
    #
    # parse_dates() may return a STRING dtype.
    # We must convert it to datetime BEFORE assigning
    # pd.Timestamp values.
    # ========================================================

    df["Status Date"] = parse_dates(
        df["Status Date"],
        date_fmts,
        dayfirst=(company == "Mylerz")
    )

    # Force datetime dtype
    df["Status Date"] = pd.to_datetime(
        df["Status Date"],
        errors="coerce"
    )

    # ========================================================
    # IN PROGRESS → TODAY
    # ========================================================

    today = pd.Timestamp.today().normalize()

    in_progress_mask = (
        df["Status"]
        .astype("string")
        .str.strip()
        .str.lower()
        .eq("in progress")
    )

    df.loc[
        in_progress_mask,
        "Status Date"
    ] = today

    # ========================================================
    # FINAL STATUS DATE FORMAT
    # ========================================================

    # Convert to YYYY-MM-DD strings only AFTER
    # all datetime assignments are finished.
    df["Status Date"] = (
        pd.to_datetime(
            df["Status Date"],
            errors="coerce"
        )
        .dt.strftime("%Y-%m-%d")
    )

    # ========================================================
    # PARSE DATE SHIPPED
    # ========================================================

    pickup_formats = {
        "Mylerz": [
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y",
        ],

        "Aramex": [
            "%m/%d/%Y",
            "%Y-%m-%d",
        ],

        "Bosta": [
            "%m-%d-%Y, %H:%M:%S",
            "%m-%d-%Y",
            "%d-%m-%Y",
        ],
    }

    df["Date Shipped"] = parse_dates(
        df["Date Shipped"],
        pickup_formats.get(
            company,
            ["%Y-%m-%d"]
        ),
        dayfirst=(company == "Mylerz")
    )

    # Force datetime first
    df["Date Shipped"] = pd.to_datetime(
        df["Date Shipped"],
        errors="coerce"
    )

    # Final uniform format
    df["Date Shipped"] = (
        df["Date Shipped"]
        .dt.strftime("%Y-%m-%d")
    )

    # ========================================================
    # NDR
    # ========================================================
    
    # Make Number Of attempts numeric before comparison
    df["Number Of attempts"] = pd.to_numeric(
        df["Number Of attempts"],
        errors="coerce"
    ).fillna(0)
    
    df["NDR"] = np.where(
        (
            (df["Number Of attempts"] >= 1)
            &
            (~df["Status"].isin(
                [
                    "Delivered",
                    "Exchanged",
                    "Returned",
                    "Out For Delivery",
                    "OFR",
                    "Lost",
                ]
            ))
        )
        |
        (df["Status"] == "Not Found"),
        "Failed Attempt",
        ""
    )
    
    return df

    



# ============================================================
# MAIN SHIPPING MERGE
# ============================================================

def clean_shipping_merge(
    input_dir,
    output_dir
):

    input_dir = (
        Path(input_dir)
        / "shipping companies"
    )

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    # ========================================================
    # FIND EXCEL FILES
    # ========================================================

    all_excel_files = (
        list(input_dir.glob("*.xlsx"))
        +
        list(input_dir.glob("*.xls"))
    )

    if not all_excel_files:

        print(
            f"No Excel files found in {input_dir}"
        )

        return None

    print(
        f"Found {len(all_excel_files)} "
        f"Excel file(s):"
    )

    for f in all_excel_files:
        print(f"  - {f.name}")

    # ========================================================
    # IDENTIFY FILES
    # ========================================================

    mylerz_file = None
    aramex_file = None
    bosta_file = None

    remaining_files = []

    for file in all_excel_files:

        name_lower = file.name.lower()

        if (
            name_lower.startswith("orders_export")
            and bosta_file is None
        ):
            bosta_file = file

        elif (
            name_lower.startswith("shipmentstatusreport")
            and aramex_file is None
        ):
            aramex_file = file

        elif (
            name_lower.startswith("mylerz")
            and mylerz_file is None
        ):
            mylerz_file = file

        else:
            remaining_files.append(file)

    # ========================================================
    # FALLBACK FILE ASSIGNMENT
    # ========================================================

    if bosta_file is None and remaining_files:

        bosta_file = remaining_files.pop(0)

        print(
            f"No Bosta file found, using: "
            f"{bosta_file.name}"
        )

    if aramex_file is None and remaining_files:

        aramex_file = remaining_files.pop(0)

        print(
            f"No Aramex file found, using: "
            f"{aramex_file.name}"
        )

    if mylerz_file is None and remaining_files:

        mylerz_file = remaining_files.pop(0)

        print(
            f"No Mylerz file found, using: "
            f"{mylerz_file.name}"
        )

    # ========================================================
    # MYLERZ
    # ========================================================

    print("\n" + "=" * 50)
    print("Processing Mylerz...")

    df_mylerz = (
        load_clean_sheet(
            mylerz_file,
            "Mylerz"
        )
        if mylerz_file
        else pd.DataFrame()
    )

    if mylerz_file:

        print(
            f"  File: {mylerz_file.name} "
            f"| Rows: {len(df_mylerz)}"
        )

    else:

        print(
            "  No Mylerz file found"
        )

    # ========================================================
    # ARAMEX
    # ========================================================

    print("\nProcessing Aramex...")

    df_aramex = (
        load_clean_sheet(
            aramex_file,
            "Aramex"
        )
        if aramex_file
        else pd.DataFrame()
    )

    if aramex_file:

        print(
            f"  File: {aramex_file.name} "
            f"| Rows: {len(df_aramex)}"
        )

    else:

        print(
            "  No Aramex file found"
        )

    # ========================================================
    # BOSTA
    # ========================================================

    print("\nProcessing Bosta...")

    df_bosta = (
        load_clean_sheet(
            bosta_file,
            "Bosta"
        )
        if bosta_file
        else pd.DataFrame()
    )

    if bosta_file:

        print(
            f"  File: {bosta_file.name} "
            f"| Rows: {len(df_bosta)}"
        )

    else:

        print(
            "  No Bosta file found"
        )

    # ========================================================
    # CHECK DATA
    # ========================================================

    if (
        df_mylerz.empty
        and df_aramex.empty
        and df_bosta.empty
    ):

        print(
            "\nNo data found or all files failed."
        )

        return None

    # ========================================================
    # NORMALIZE DATA TYPES
    # ========================================================

    for df in [
        df_mylerz,
        df_aramex,
        df_bosta
    ]:

        if df.empty:
            continue

        df["COD Value"] = pd.to_numeric(
            df["COD Value"],
            errors="coerce"
        ).fillna(0)

        df["Number Of attempts"] = pd.to_numeric(
            df["Number Of attempts"],
            errors="coerce"
        ).fillna(0)

        if "HUB" in df.columns:

            df["HUB"] = (
                df["HUB"]
                .astype("string")
                .str.strip()
            )

    # ========================================================
    # CONCATENATE
    # ========================================================

    final = pd.concat(
        [
            df_mylerz,
            df_aramex,
            df_bosta
        ],
        ignore_index=True
    )

    # ========================================================
    # BOSTA FLYERS COST
    # ========================================================

    final["Flyers Cost"] = np.where(
        final["Shipping Company"].eq("Bosta"),
        7,
        0
    )


    # ========================================================
    # ORDER ID
    # ========================================================

    final["OrderID"] = (
        final["OrderID"]
        .astype(str)
        .str.strip()
    )

    final["OrderID"] = (
        final["OrderID"]
        .str.replace(
            r"(?i)^re_",
            "",
            regex=True
        )
    )

    # ========================================================
    # FINAL NUMERIC CLEANING
    # ========================================================

    final["COD Value"] = pd.to_numeric(
        final["COD Value"],
        errors="coerce"
    ).fillna(0)

    final["Number Of attempts"] = pd.to_numeric(
        final["Number Of attempts"],
        errors="coerce"
    ).fillna(0)

    # ========================================================
    # UNIFY CITIES
    # ========================================================

    if "HUB" in final.columns:

        final = unify_cities(
            final,
            "HUB"
        )

    # ========================================================
    # SAVE CSV
    # ========================================================

    csv_path = (
        output_dir
        / "shipping_companies.csv"
    )

    final.to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig"
    )

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n" + "=" * 50)
    print("✅ Done. All files saved successfully.")
    print(f"📁 Output: {csv_path}")
    print(f"📊 Total rows: {len(final):,}")
    print("=" * 50)

    return final


# ============================================================
# RUN DIRECTLY
# ============================================================

if __name__ == "__main__":

    base_path = (
        Path(__file__).resolve().parent.parent
        / "files"
    )

    output_path = (
        base_path
        / "cleaned_files"
    )

    clean_shipping_merge(
        base_path,
        output_path,
    )
