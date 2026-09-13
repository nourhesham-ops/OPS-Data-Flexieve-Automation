
from pathlib import Path

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

FILES_DIR = BASE_DIR / "files" / "odoo"

OUTPUT = BASE_DIR / "output" / "final_merged.xlsx"

CREDENTIALS = BASE_DIR / "credentials.json"

SHEET_ID = "1Hk39IVtW-zkL4ylbdsfJcVKmAhvk5gkeeWUSpSXksXs"

SHEET_NAME = "Test Data merged"

TEMPLATE_SHEET_NAME = "Test Template"

# ============================================================
# COLUMN CONFIG
# ============================================================

PHONE_COLUMN = "Phone"

REVISION_COLUMN = "Revision Completed"

GROUP_COLUMN = "Source Document"

SALES_KEY = "Order Reference"

TRANSFER_KEY = "Source Document"

TRANSFER_ADDRESS_COLUMN = "Sales Order/Customer/Street"

TRANSFER_ADDRESS_TEMP = "__CUSTOMER_ADDRESS__"

PRODUCT_COLUMN = "Sales Order/Order Lines/Product"

QTY_COLUMN = "Sales Order/Order Lines/Product Qty"

EXCLUDED_PRODUCT = "[BWA] Bosta Delivery"

# ============================================================
# COLUMN RENAME
# ============================================================

COLUMN_RENAME = {
    "Sales Order/Order Lines/Product": "Product",
    "Sales Order/Order Lines/Product Qty": "Qty",
    "Sales Order/Customer/Sale Order Count": "Orders Count",
    "Sales Order/Order Lines/Price Reduce Tax excl": "Price Reduce Tax excl",
    "Sales Order/Order Lines/Price Reduce Tax incl": "Price Reduce Tax incl",
    "Sales Order/Net Price": "Net Price",
    "Sales Order/Online payment": "Online payment",
}

# ============================================================
# FINAL COLUMNS
# ============================================================

FINAL_COLUMNS = [
    "Priority",
    "Reference",
    "Address",
    "Source Location",
    "Destination Location",
    "Scheduled Date",
    "Online payment",
    "Contact",
    "Product",
    "Qty",
    "Price Reduce Tax excl",
    "Price Reduce Tax incl",
    "Net Price",
    "Orders Count",
    "Source Document",
    "Customer Address",
    "Phone",
    "Phone Validation",
    "Revision Completed",
]

# ============================================================
# TRANSFER COLUMNS
# ============================================================

TRANSFER_FILL_COLUMNS = [
    "Priority",
    "Reference",
    "Address",
    "Source Location",
    "Destination Location",
    "Contact",
    "Scheduled Date",
    "Source Document",
]

# ============================================================
# GROUPING COLUMNS
# ============================================================

LINE_COLUMNS = [
    "Product",
    "Qty",
    "Price Reduce Tax excl",
    "Price Reduce Tax incl",
    "Net Price",
]

ORDER_COLUMNS = [
    "Priority",
    "Reference",
    "Address",
    "Source Location",
    "Destination Location",
    "Scheduled Date",
    "Online payment",
    "Contact",
    "Orders Count",
    "Source Document",
    "Customer Address",
    "Phone",
    "Phone Validation",
    "Revision Completed",
]

# ============================================================
# HELPERS
# ============================================================

def normalize(value):

    if pd.isna(value):
        return ""

    return " ".join(
        str(value)
        .replace("\xa0", " ")
        .split()
    ).strip()

def clean_columns(df):

    df.columns = (
        df.columns
        .astype(str)
        .str.replace("\xa0", " ", regex=False)
        .str.strip()
    )

    return df

def combine_values(series):

    values = []

    for value in series:

        value = normalize(value)

        if value and value not in values:
            values.append(value)

    return "\n".join(values)

def validate_phone(value):

    value = normalize(value).replace("+", "")

    if (
        value.isdigit()
        and len(value) == 12
        and value.startswith("20")
    ):
        return "Valid"

    return "Invalid"

def latest_file(pattern):

    files = [
        f
        for f in FILES_DIR.glob(pattern)
        if not f.name.startswith("~$")
    ]

    if not files:

        raise FileNotFoundError(
            f"File not found: {pattern}"
        )

    return max(
        files,
        key=lambda f: f.stat().st_mtime
    )

def update_sheet(worksheet, data):

    worksheet.clear()

    end_cell = gspread.utils.rowcol_to_a1(
        len(data),
        len(data[0])
    )

    worksheet.update(
        range_name=f"A1:{end_cell}",
        values=data,
        value_input_option="USER_ENTERED",
    )

# ============================================================
# FIND FILES
# ============================================================

sales_file = latest_file(
    "Sales Order (sale.order)*.xlsx"
)

transfer_file = latest_file(
    "Transfer (stock.picking)*.xlsx"
)

print("Sales   :", sales_file.name)
print("Transfer:", transfer_file.name)

# ============================================================
# READ FILES
# ============================================================

sales = pd.read_excel(
    sales_file,
    dtype=object
).fillna("")

transfer = pd.read_excel(
    transfer_file,
    dtype=object
).fillna("")

sales = clean_columns(sales)

transfer = clean_columns(transfer)

# ============================================================
# REMOVE UNDEFINED TRANSFER ROWS
# ============================================================

if "Priority" in transfer.columns:

    transfer = transfer[
        transfer["Priority"].apply(normalize)
        != "Undefined (71)"
    ].copy()

# ============================================================
# FILL TRANSFER DATA DOWN
# ============================================================

fill_columns = [
    col
    for col in TRANSFER_FILL_COLUMNS
    if col in transfer.columns
]

if fill_columns:

    transfer[fill_columns] = (
        transfer[fill_columns]
        .replace("", pd.NA)
        .ffill()
        .fillna("")
    )

# ============================================================
# CUSTOMER ADDRESS FROM TRANSFER
# ============================================================

if TRANSFER_ADDRESS_COLUMN in transfer.columns:

    transfer[TRANSFER_ADDRESS_TEMP] = (
        transfer[TRANSFER_ADDRESS_COLUMN]
        .apply(normalize)
    )

else:

    transfer[TRANSFER_ADDRESS_TEMP] = ""

    print(
        f"WARNING: {TRANSFER_ADDRESS_COLUMN} not found."
    )

# ============================================================
# VALIDATE MATCH COLUMNS
# ============================================================

if SALES_KEY not in sales.columns:

    raise ValueError(
        f"Missing Sales column: {SALES_KEY}"
    )

if TRANSFER_KEY not in transfer.columns:

    raise ValueError(
        f"Missing Transfer column: {TRANSFER_KEY}"
    )

# ============================================================
# CREATE MATCH KEYS
# ============================================================

sales["_key"] = (
    sales[SALES_KEY]
    .apply(normalize)
    .str.lstrip("#")
)

transfer["_key"] = (
    transfer[TRANSFER_KEY]
    .apply(normalize)
    .str.lstrip("#")
)

# ============================================================
# CLEAN SALES DATA
# ============================================================

sales = sales.drop(
    columns=[SALES_KEY]
)

sales_address_columns = [
    "Customer/Complete Address",
    "Sales Order/Customer/Street",
    "Sales Order/Customer/City",
    "Sales Order/Customer/State",
    "Sales Order/Customer/Zip",
    "Sales Order/Customer/Country",
]

sales = sales.drop(
    columns=[
        col
        for col in sales_address_columns
        if col in sales.columns
    ],
    errors="ignore"
)

# ============================================================
# MERGE SALES + TRANSFER
# ============================================================

merged = transfer.merge(
    sales,
    on="_key",
    how="left",
    suffixes=("", "_Sales")
)

merged.drop(
    columns=["_key"],
    inplace=True
)

# ============================================================
# CUSTOMER ADDRESS
# ============================================================

merged["Customer Address"] = (
    merged[TRANSFER_ADDRESS_TEMP]
    .apply(normalize)
)

merged.drop(
    columns=[TRANSFER_ADDRESS_TEMP],
    inplace=True
)

if TRANSFER_ADDRESS_COLUMN in merged.columns:

    merged.drop(
        columns=[TRANSFER_ADDRESS_COLUMN],
        inplace=True
    )

# ============================================================
# RENAME SALES COLUMNS
# ============================================================

merged.rename(
    columns=COLUMN_RENAME,
    inplace=True
)

# ============================================================
# PHONE VALIDATION
# ============================================================

if PHONE_COLUMN in merged.columns:

    merged["Phone Validation"] = (
        merged[PHONE_COLUMN]
        .apply(validate_phone)
    )

else:

    merged["Phone Validation"] = "Invalid"

    print(
        f"WARNING: {PHONE_COLUMN} not found."
    )

# ============================================================
# REQUIRED COLUMNS
# ============================================================

for column in FINAL_COLUMNS:

    if column not in merged.columns:

        merged[column] = ""

merged = merged[
    FINAL_COLUMNS
].copy()

# ============================================================
# NORMALIZE SOURCE DOCUMENT
# ============================================================

merged[GROUP_COLUMN] = (
    merged[GROUP_COLUMN]
    .apply(normalize)
)

# ============================================================
# GROUP BY SOURCE DOCUMENT
# ============================================================

grouped_rows = []

for source_document, group in merged.groupby(
    GROUP_COLUMN,
    sort=False,
    dropna=False
):

    row = {}

    # --------------------------------------------------------
    # ORDER LEVEL DATA
    # --------------------------------------------------------

    for column in ORDER_COLUMNS:

        values = (
            group[column]
            .apply(normalize)
        )

        values = values[
            values != ""
        ]

        if not values.empty:

            row[column] = values.iloc[0]

        else:

            row[column] = ""

    # --------------------------------------------------------
    # LINE LEVEL DATA
    # --------------------------------------------------------

    for column in LINE_COLUMNS:

        row[column] = combine_values(
            group[column]
        )

    row[GROUP_COLUMN] = normalize(
        source_document
    )

    grouped_rows.append(row)

# ============================================================
# CREATE GROUPED DATAFRAME
# ============================================================

merged = pd.DataFrame(
    grouped_rows
)

for column in FINAL_COLUMNS:

    if column not in merged.columns:

        merged[column] = ""

merged = merged[
    FINAL_COLUMNS
].fillna("")

# ============================================================
# CHECK DUPLICATES
# ============================================================

duplicate_mask = (
    merged[GROUP_COLUMN]
    .duplicated(keep=False)
)

duplicate_source_documents = (
    merged.loc[
        duplicate_mask,
        GROUP_COLUMN
    ]
    .tolist()
)

print()
print("=" * 60)
print("GROUPING CHECK")
print("=" * 60)

print(
    "Rows before grouping:",
    len(transfer)
)

print(
    "Rows after grouping :",
    len(merged)
)

if duplicate_source_documents:

    print()
    print(
        "ERROR: Duplicate Source Documents found:"
    )

    for value in sorted(
        set(duplicate_source_documents)
    ):

        print(repr(value))

    raise ValueError(
        "Duplicate Source Document values still exist."
    )

print(
    "Duplicate Source Documents: 0"
)

print("=" * 60)

# ============================================================
# GOOGLE AUTHENTICATION
# ============================================================

credentials = (
    Credentials.from_service_account_file(
        CREDENTIALS,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
)

client = gspread.authorize(
    credentials
)

spreadsheet = client.open_by_key(
    SHEET_ID
)

# ============================================================
# GET OLD REVISION COMPLETED VALUES
# ============================================================

worksheet = spreadsheet.worksheet(
    SHEET_NAME
)

print()
print(
    "Reading existing Revision Completed values..."
)

old_records = worksheet.get_all_records()

revision_map = {}

for record in old_records:

    source_document = normalize(
        record.get(GROUP_COLUMN, "")
    )

    revision_value = normalize(
        record.get(REVISION_COLUMN, "")
    )

    if (
        source_document
        and revision_value
        and source_document not in revision_map
    ):

        revision_map[
            source_document
        ] = revision_value

print(
    "Existing Revision values found:",
    len(revision_map)
)

# ============================================================
# RESTORE REVISION COMPLETED
# ============================================================

merged[REVISION_COLUMN] = (
    merged[GROUP_COLUMN]
    .map(revision_map)
    .fillna("")
)

# ============================================================
# SAVE EXCEL
# ============================================================

OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True
)

merged.to_excel(
    OUTPUT,
    index=False,
    engine="openpyxl"
)

print()
print(
    "Excel saved:"
)

print(
    OUTPUT
)

# ============================================================
# UPDATE TEST DATA MERGED
# ============================================================

data = (
    [merged.columns.tolist()]
    +
    merged.astype(str).values.tolist()
)

print()
print(
    "Updating Google Sheet..."
)

print(
    "Sheet :",
    SHEET_NAME
)

print(
    "Revision Completed will be preserved."
)

update_sheet(
    worksheet,
    data
)

print(
    "Test Data merged updated successfully."
)

# ============================================================
# TEST TEMPLATE
# ============================================================

if PRODUCT_COLUMN not in transfer.columns:

    raise ValueError(
        f"Missing Transfer column: {PRODUCT_COLUMN}"
    )

if QTY_COLUMN not in transfer.columns:

    raise ValueError(
        f"Missing Transfer column: {QTY_COLUMN}"
    )

# ============================================================
# GET PRODUCT + QTY
# ============================================================

template_products = transfer[
    [
        PRODUCT_COLUMN,
        QTY_COLUMN
    ]
].copy()

template_products[PRODUCT_COLUMN] = (
    template_products[PRODUCT_COLUMN]
    .apply(normalize)
)

# ============================================================
# REMOVE EMPTY PRODUCTS
# ============================================================

template_products = template_products[
    template_products[PRODUCT_COLUMN] != ""
].copy()

# ============================================================
# REMOVE BOSTA DELIVERY
# ============================================================

template_products = template_products[
    template_products[PRODUCT_COLUMN]
    != EXCLUDED_PRODUCT
].copy()

# ============================================================
# CONVERT QTY
# ============================================================

template_products[QTY_COLUMN] = pd.to_numeric(
    template_products[QTY_COLUMN],
    errors="coerce"
).fillna(0)

# ============================================================
# GROUP PRODUCTS + SUM QTY
# ============================================================

template_products = (
    template_products
    .groupby(
        PRODUCT_COLUMN,
        sort=False,
        as_index=False
    )[QTY_COLUMN]
    .sum()
)

# ============================================================
# PREPARE TEMPLATE VALUES
# ============================================================

template_values = []

for _, row in template_products.iterrows():

    qty = row[QTY_COLUMN]

    if float(qty).is_integer():

        qty = int(qty)

    template_values.append(
        [
            str(row[PRODUCT_COLUMN]),
            str(qty),
        ]
    )

# ============================================================
# TOTAL
# ============================================================

total_qty = (
    template_products[QTY_COLUMN]
    .sum()
)

if float(total_qty).is_integer():

    total_qty = int(total_qty)

template_values.append(
    [
        "Total",
        str(total_qty),
    ]
)

# ============================================================
# UPDATE TEST TEMPLATE
# ============================================================
#
# IMPORTANT:
#
# Do NOT clear the whole sheet.
#
# Only columns A and B are updated.
#
# All columns C onward remain unchanged.
#
# ============================================================

template_worksheet = spreadsheet.worksheet(
    TEMPLATE_SHEET_NAME
)

print()
print(
    "Updating Test Template..."
)

print(
    "Only columns A and B will be changed."
)

# ============================================================
# READ EXISTING TEMPLATE SIZE
# ============================================================

existing_template_values = (
    template_worksheet.get_all_values()
)

existing_template_rows = len(
    existing_template_values
)

# ============================================================
# UPDATE COLUMN NAMES
# ============================================================
#
# A1 = Product
# B1 = Qty
#
# Other headers are NOT touched.
#
# ============================================================

template_worksheet.update(
    range_name="A1:B1",
    values=[
        [
            "Product",
            "Qty"
        ]
    ],
    value_input_option="USER_ENTERED",
)

# ============================================================
# UPDATE PRODUCT + QTY
# ============================================================

if template_values:

    template_worksheet.update(
        range_name=f"A2:B{len(template_values) + 1}",
        values=template_values,
        value_input_option="USER_ENTERED",
    )

# ============================================================
# CLEAR OLD REMAINING DATA FROM A:B ONLY
# ============================================================
#
# If the new list is shorter than the previous list,
# clear only the remaining cells in columns A and B.
#
# Columns C onward are untouched.
#
# ============================================================

new_last_row = len(template_values) + 1

if existing_template_rows > new_last_row:

    template_worksheet.batch_clear(
        [
            f"A{new_last_row + 1}:B{existing_template_rows}"
        ]
    )

print(
    "Test Template updated successfully."
)

print(
    "Updated columns: Product, Qty"
)

print(
    "Other columns preserved."
)

# ============================================================
# DONE
# ============================================================

print()
print("=" * 60)
print("DONE")
print("=" * 60)

print(
    "Sales file   :",
    sales_file.name
)

print(
    "Transfer file:",
    transfer_file.name
)

print(
    "Final rows   :",
    len(merged)
)

print(
    "Final columns:",
    len(merged.columns)
)

print(
    "Excel        :",
    OUTPUT
)

print(
    "Google Sheet :",
    SHEET_NAME
)

print(
    "Google Sheet :",
    TEMPLATE_SHEET_NAME
)

print(
    "Revision preserved:",
    len(revision_map)
)

print(
    "Total Qty:",
    total_qty
)

print()
print(
    "Customer Address source:"
)

print(
    "Transfer -> Sales Order/Customer/Street"
)

print()
print(
    "Test Template source:"
)

print(
    "Transfer -> Sales Order/Order Lines/Product"
)

print(
    "Qty -> SUM(Sales Order/Order Lines/Product Qty)"
)

print()
print(
    "Excluded Product:"
)

print(
    EXCLUDED_PRODUCT
)

print()
print(
    "Test Template updated columns:"
)

print(
    "A = Product"
)

print(
    "B = Qty"
)

print(
    "Columns C onward = PRESERVED"
)

print()
print(
    "Final columns:"
)

for i, column in enumerate(
    merged.columns,
    start=1
):

    print(
        f"{i}. {column}"
    )

print("=" * 60)
