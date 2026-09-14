from pathlib import Path
import time
import os
import io

from dotenv import load_dotenv

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import gspread

from pipeline.Shipping.DBManage import (
    sync_to_supabase_shipping
)

from pipeline.Shipping.CLShipping import (
    clean_shipping_merge
)

from pipeline.Shipping.MergeWH_Shippping import (
    load_data_from_db,
    merge_shipping_with_warehouse,
    create_or_update_worksheet,
)


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# PATHS
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

# Local temporary directory.
# Shipping files from Google Drive will be downloaded here
# before cleaning.
FILES_DIR = BASE_DIR / "files"

CLEANED_DIR = BASE_DIR / "cleaned_files"

CREDENTIALS_PATH = BASE_DIR / "credentials.json"

FILES_DIR.mkdir(exist_ok=True)

CLEANED_DIR.mkdir(exist_ok=True)


# ============================================================
# GOOGLE DRIVE CONFIGURATION
# ============================================================

# Google Drive folder containing Shipping files
DRIVE_FOLDER_ID = (
    "1yThJB-tCZzAOK8WHDeoAC9aGezfX9nlS"
)


# ============================================================
# CONFIGURATION
# ============================================================

ST_Date = "2026-01-01"


date_filters_Shipping = [
    "Date Shipped"
]


date_filters_WH = [
    "Date"
]


# ============================================================
# PIPELINE CONTROL
# ============================================================

# ------------------------------------------------------------
# STEP 1
# Download Shipping files from Google Drive
# and clean them
# ------------------------------------------------------------

RUN_CLEAN_SHIPPING = True


# ------------------------------------------------------------
# STEP 2
# Sync Shipping to Database
# ------------------------------------------------------------

RUN_DB_SYNC = False


# ------------------------------------------------------------
# STEP 3
# Load Warehouse + Shipping from Database
# and merge them
# ------------------------------------------------------------

RUN_WAREHOUSE_MERGE = True


# ------------------------------------------------------------
# STEP 4
# Write merged data to Google Sheets
# ------------------------------------------------------------

RUN_WRITE_OUTPUT = True


# ============================================================
# DATABASE CONFIGURATION
# ============================================================

SHIPPING_DB_ENV = "DB_URL_Shipping"

WAREHOUSE_DB_ENV = "DB_URL_Orders"

SHIPPING_TABLE = "shipments"

WAREHOUSE_TABLE = "orders"


# ============================================================
# RETRY CONFIGURATION
# ============================================================

MAX_RETRIES = 3

RETRY_DELAY = 2


# ============================================================
# GOOGLE API SCOPES
# ============================================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ============================================================
# GOOGLE SHEET CONFIGURATION
# ============================================================

Output_ID = (
    "1FZznGDLUYS5wnXXnyyYJEWjLRwv5CsRhzXA9EpHB4j8"
)

WH_Merge = "Warehouse Shipping"


# ============================================================
# GOOGLE AUTHENTICATION
# ============================================================

def get_google_credentials():

    if not CREDENTIALS_PATH.exists():

        raise FileNotFoundError(
            f"credentials.json NOT FOUND at:\n"
            f"{CREDENTIALS_PATH}"
        )

    print(
        "Loading Google credentials..."
    )

    creds = Credentials.from_service_account_file(
        CREDENTIALS_PATH,
        scopes=scope,
    )

    return creds


# ============================================================
# GOOGLE SHEETS AUTHENTICATION
# ============================================================

def auth():

    creds = get_google_credentials()

    print(
        "Authenticating with Google Sheets..."
    )

    client = gspread.authorize(creds)

    print(
        "Google Sheets authentication successful.\n"
    )

    return client


# ============================================================
# GOOGLE DRIVE AUTHENTICATION
# ============================================================

def drive_auth():

    creds = get_google_credentials()

    print(
        "Authenticating with Google Drive..."
    )

    drive_service = build(
        "drive",
        "v3",
        credentials=creds,
    )

    print(
        "Google Drive authentication successful.\n"
    )

    return drive_service


# ============================================================
# DOWNLOAD FILES FROM GOOGLE DRIVE
# ============================================================

def download_shipping_files_from_drive(
    drive_service,
    folder_id,
    output_dir,
):
    """
    Download all supported files from a Google Drive folder.

    Supported file types:
        - CSV
        - XLSX
        - XLS

    Existing local files with the same names will be replaced.
    """

    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("=" * 60)
    print("DOWNLOADING SHIPPING FILES FROM GOOGLE DRIVE")
    print("=" * 60)

    print(
        f"Drive Folder ID: {folder_id}"
    )

    print(
        f"Local directory: {output_dir}"
    )

    # --------------------------------------------------------
    # Find files inside Drive folder
    # --------------------------------------------------------

    query = (
        f"'{folder_id}' in parents "
        "and trashed = false"
    )

    results = []

    page_token = None

    while True:

        response = drive_service.files().list(
            q=query,
            spaces="drive",
            fields=(
                "nextPageToken,"
                "files(id,name,mimeType,size,"
                "modifiedTime)"
            ),
            pageToken=page_token,
            pageSize=1000,
        ).execute()

        results.extend(
            response.get("files", [])
        )

        page_token = response.get(
            "nextPageToken"
        )

        if not page_token:
            break

    print(
        f"Found {len(results):,} item(s) in Drive folder."
    )

    # --------------------------------------------------------
    # Supported MIME types
    # --------------------------------------------------------

    supported_mime_types = {
        "text/csv",
        "application/vnd.ms-excel",
        (
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    }

    supported_extensions = {
        ".csv",
        ".xlsx",
        ".xls",
    }

    downloaded_files = []

    skipped_files = []

    # --------------------------------------------------------
    # Download each file
    # --------------------------------------------------------

    for file_info in results:

        file_id = file_info["id"]

        file_name = file_info["name"]

        mime_type = file_info.get(
            "mimeType",
            ""
        )

        # ----------------------------------------------------
        # Skip folders
        # ----------------------------------------------------

        if mime_type == (
            "application/vnd.google-apps.folder"
        ):

            print(
                f"SKIPPED FOLDER: {file_name}"
            )

            skipped_files.append(
                file_name
            )

            continue

        file_extension = (
            Path(file_name)
            .suffix
            .lower()
        )

        # ----------------------------------------------------
        # Check supported file type
        # ----------------------------------------------------

        if (
            mime_type not in supported_mime_types
            and file_extension not in supported_extensions
        ):

            print(
                f"SKIPPED unsupported file: "
                f"{file_name}"
            )

            skipped_files.append(
                file_name
            )

            continue

        destination = (
            output_dir / file_name
        )

        print(
            f"\nDownloading: {file_name}"
        )

        try:

            request = drive_service.files().get_media(
                fileId=file_id
            )

            with open(
                destination,
                "wb"
            ) as file_handle:

                downloader = MediaIoBaseDownload(
                    file_handle,
                    request,
                )

                done = False

                while not done:

                    status, done = (
                        downloader.next_chunk()
                    )

                    if status:

                        progress = (
                            status.progress()
                            * 100
                        )

                        print(
                            f"   Progress: "
                            f"{progress:.1f}%",
                            end="\r",
                        )

            print(
                f"   Downloaded: "
                f"{destination}"
            )

            downloaded_files.append(
                destination
            )

        except Exception as e:

            print(
                f"   ERROR downloading "
                f"{file_name}: {e}"
            )

            raise

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()

    print(
        f"Downloaded files: "
        f"{len(downloaded_files):,}"
    )

    print(
        f"Skipped files: "
        f"{len(skipped_files):,}"
    )

    print()

    if not downloaded_files:

        raise FileNotFoundError(
            "No supported Shipping files "
            "were found in the Google Drive folder."
        )

    return downloaded_files


# ============================================================
# OPTIONAL:
# CLEAR OLD LOCAL SHIPPING FILES
# ============================================================

def clear_local_shipping_files(
    output_dir,
):
    """
    Delete old CSV/XLS/XLSX files from the local
    temporary Shipping directory before downloading
    the latest files from Google Drive.
    """

    output_dir = Path(output_dir)

    print(
        "Cleaning old local Shipping files..."
    )

    extensions = {
        ".csv",
        ".xlsx",
        ".xls",
    }

    deleted_count = 0

    for file_path in output_dir.iterdir():

        if not file_path.is_file():
            continue

        if (
            file_path.suffix.lower()
            not in extensions
        ):
            continue

        try:

            file_path.unlink()

            deleted_count += 1

            print(
                f"   Deleted: "
                f"{file_path.name}"
            )

        except Exception as e:

            print(
                f"   Could not delete "
                f"{file_path.name}: {e}"
            )

            raise

    print(
        f"Deleted {deleted_count:,} old file(s).\n"
    )


# ============================================================
# PIPELINE
# ============================================================

def run_pipeline():

    start_time = time.time()

    step_times = {}

    # --------------------------------------------------------
    # Variables
    # --------------------------------------------------------

    client = None

    drive_service = None

    df_clean = None

    warehouse_df = None

    shipping_df = None

    merged_df = None


    # ========================================================
    # GOOGLE AUTHENTICATION
    # ========================================================

    if RUN_WRITE_OUTPUT:

        client = auth()


    # ========================================================
    # STEP 1
    # DOWNLOAD + CLEAN SHIPPING
    # ========================================================

    if RUN_CLEAN_SHIPPING:

        step_start = time.time()

        print("=" * 60)
        print(
            "STEP 1: DOWNLOAD + CLEAN SHIPPING DATA"
        )
        print("=" * 60)

        try:

            # ------------------------------------------------
            # Authenticate with Google Drive
            # ------------------------------------------------

            drive_service = drive_auth()


            # ------------------------------------------------
            # Remove old local files
            # ------------------------------------------------

            clear_local_shipping_files(
                FILES_DIR
            )


            # ------------------------------------------------
            # Download files from Google Drive
            # ------------------------------------------------

            downloaded_files = (
                download_shipping_files_from_drive(
                    drive_service=drive_service,
                    folder_id=DRIVE_FOLDER_ID,
                    output_dir=FILES_DIR,
                )
            )


            print(
                f"  → Downloaded Shipping files: "
                f"{len(downloaded_files):,}"
            )


            # ------------------------------------------------
            # Clean Shipping
            # ------------------------------------------------

            print()

            print(
                "  → Cleaning and merging "
                "Shipping data..."
            )

            df_clean = clean_shipping_merge(
                input_dir=FILES_DIR,
                output_dir=CLEANED_DIR,
            )


            # ------------------------------------------------
            # Timing
            # ------------------------------------------------

            step_times["STEP 1"] = (
                time.time() - step_start
            )

            print()

            print(
                f"STEP 1 completed in "
                f"{step_times['STEP 1']:.2f} seconds"
            )


            if df_clean is not None:

                print(
                    f"   → Cleaned rows: "
                    f"{len(df_clean):,}"
                )

            print()

        except Exception as e:

            step_times["STEP 1"] = (
                time.time() - step_start
            )

            print(
                f"ERROR in STEP 1 after "
                f"{step_times['STEP 1']:.2f} seconds"
            )

            print(
                f"   → {e}"
            )

            raise

    else:

        print("=" * 60)
        print("STEP 1 SKIPPED")
        print("=" * 60)
        print()


    # ========================================================
    # STEP 2
    # SHIPPING DATABASE SYNC
    # ========================================================

    if RUN_DB_SYNC:

        step_start = time.time()

        print("=" * 60)
        print("DATABASE SYNC - SHIPPING")
        print("=" * 60)

        try:

            # ------------------------------------------------
            # Validate DataFrame
            # ------------------------------------------------

            if df_clean is None:

                raise ValueError(
                    "RUN_DB_SYNC=True but df_clean is None.\n"
                    "Enable RUN_CLEAN_SHIPPING=True "
                    "so the shipping data can be cleaned first."
                )


            # ------------------------------------------------
            # Load DB URL
            # ------------------------------------------------

            DB_URL = os.getenv(
                SHIPPING_DB_ENV
            )

            if not DB_URL:

                raise ValueError(
                    f"{SHIPPING_DB_ENV} is not set in .env"
                )


            # ------------------------------------------------
            # Sync
            # ------------------------------------------------

            print(
                "  → Syncing Shipping data..."
            )

            sync_to_supabase_shipping(
                df_clean,
                DB_URL,
                "AWB",
                SHIPPING_TABLE
            )


            # ------------------------------------------------
            # Timing
            # ------------------------------------------------

            step_times["DB SYNC"] = (
                time.time() - step_start
            )

            print(
                f"Shipping data synced in "
                f"{step_times['DB SYNC']:.2f} seconds"
            )

            print()

        except Exception as e:

            step_times["DB SYNC"] = (
                time.time() - step_start
            )

            print(
                f"ERROR during Shipping DB sync "
                f"after "
                f"{step_times['DB SYNC']:.2f} seconds"
            )

            print(
                f"   → {e}"
            )

            raise

    else:

        print("=" * 60)
        print("SHIPPING DATABASE SYNC SKIPPED")
        print("=" * 60)
        print()


    # ========================================================
    # STEP 3
    # WAREHOUSE + SHIPPING MERGE
    # ========================================================

    if RUN_WAREHOUSE_MERGE:

        step_start = time.time()

        print("=" * 60)
        print(
            "WAREHOUSE + SHIPPING MERGE"
        )
        print("=" * 60)

        try:

            # ------------------------------------------------
            # Load Warehouse / Orders from Database
            # ------------------------------------------------

            print(
                "  → Loading Warehouse "
                "from Database..."
            )

            WAREHOUSE_DB_URL = os.getenv(
                WAREHOUSE_DB_ENV
            )

            if not WAREHOUSE_DB_URL:

                raise ValueError(
                    f"{WAREHOUSE_DB_ENV} is not set in .env"
                )


            warehouse_df = load_data_from_db(
                db_url=WAREHOUSE_DB_URL,
                table_name=WAREHOUSE_TABLE,
                start_date=ST_Date,
                date_columns=date_filters_WH,
            )


            print(
                f"  → Warehouse rows: "
                f"{len(warehouse_df):,}"
            )


            # ------------------------------------------------
            # Load Shipping from Database
            # ------------------------------------------------

            print(
                "  → Loading Shipping "
                "from Database..."
            )

            SHIPPING_DB_URL = os.getenv(
                SHIPPING_DB_ENV
            )

            if not SHIPPING_DB_URL:

                raise ValueError(
                    f"{SHIPPING_DB_ENV} is not set in .env"
                )


            shipping_df = load_data_from_db(
                db_url=SHIPPING_DB_URL,
                table_name=SHIPPING_TABLE,
                start_date=ST_Date,
                date_columns=date_filters_Shipping,
            )


            print(
                f"  → Shipping rows: "
                f"{len(shipping_df):,}"
            )


            # ------------------------------------------------
            # Merge
            # ------------------------------------------------

            print(
                "  → Merging "
                "Shipping + Warehouse..."
            )

            merged_df = (
                merge_shipping_with_warehouse(
                    shipping_df,
                    warehouse_df,
                )
            )


            print(
                f"  → Merged rows: "
                f"{len(merged_df):,}"
            )


            # ------------------------------------------------
            # Timing
            # ------------------------------------------------

            step_times["WAREHOUSE MERGE"] = (
                time.time() - step_start
            )

            print(
                f"Warehouse merge completed in "
                f"{step_times['WAREHOUSE MERGE']:.2f} seconds"
            )

            print()

        except Exception as e:

            step_times["WAREHOUSE MERGE"] = (
                time.time() - step_start
            )

            print(
                f"ERROR during warehouse merge "
                f"after "
                f"{step_times['WAREHOUSE MERGE']:.2f} seconds"
            )

            print(
                f"   → {e}"
            )

            raise

    else:

        print("=" * 60)
        print("WAREHOUSE MERGE SKIPPED")
        print("=" * 60)
        print()


    # ========================================================
    # STEP 4
    # WRITE FINAL OUTPUT
    # ========================================================

    if RUN_WRITE_OUTPUT:

        step_start = time.time()

        print("=" * 60)
        print(
            "WRITING FINAL DATA TO GOOGLE SHEETS"
        )
        print("=" * 60)

        try:

            # ------------------------------------------------
            # Validate merged data
            # ------------------------------------------------

            if merged_df is None:

                raise ValueError(
                    "RUN_WRITE_OUTPUT=True but "
                    "merged_df is None.\n"
                    "Enable RUN_WAREHOUSE_MERGE=True "
                    "before writing the output."
                )


            # ------------------------------------------------
            # Write
            # ------------------------------------------------

            create_or_update_worksheet(
                client,
                Output_ID,
                WH_Merge,
                merged_df,
            )


            # ------------------------------------------------
            # Timing
            # ------------------------------------------------

            step_times["WRITE OUTPUT"] = (
                time.time() - step_start
            )

            print(
                f"Final data written in "
                f"{step_times['WRITE OUTPUT']:.2f} seconds"
            )

            print()

        except Exception as e:

            step_times["WRITE OUTPUT"] = (
                time.time() - step_start
            )

            print(
                f"ERROR writing output after "
                f"{step_times['WRITE OUTPUT']:.2f} seconds"
            )

            print(
                f"   → {e}"
            )

            raise

    else:

        print("=" * 60)
        print("WRITE OUTPUT SKIPPED")
        print("=" * 60)
        print()


    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    total_time = (
        time.time() - start_time
    )


    print("=" * 60)
    print("PIPELINE FINISHED")
    print("=" * 60)

    print(
        "Performance Summary:"
    )


    for step, duration in step_times.items():

        print(
            f"  → {step}: "
            f"{duration:.2f} seconds"
        )


    print(
        f"  → TOTAL TIME: "
        f"{total_time:.2f} seconds"
    )

    print("=" * 60)


    # ========================================================
    # RETURN RESULT
    # ========================================================

    if merged_df is not None:

        return merged_df

    if df_clean is not None:

        return df_clean

    if shipping_df is not None:

        return shipping_df

    return None


# ============================================================
# PIPELINE WITH RETRY
# ============================================================

def run_pipeline_with_retry(
    max_retries=MAX_RETRIES,
    retry_delay=RETRY_DELAY,
):

    last_exception = None


    for attempt in range(
        1,
        max_retries + 1
    ):

        print()

        print("=" * 60)

        print(
            f"Starting pipeline - "
            f"Attempt {attempt}/{max_retries}"
        )

        print("=" * 60)


        try:

            result = run_pipeline()


            print()

            print(
                f"Pipeline finished successfully "
                f"on attempt {attempt}."
            )


            return result


        except Exception as e:

            last_exception = e


            print()

            print(
                f"Attempt {attempt}/{max_retries} failed."
            )

            print(
                f"   → {e}"
            )


            if attempt < max_retries:

                print(
                    f"Waiting {retry_delay} seconds "
                    f"before retry..."
                )

                time.sleep(
                    retry_delay
                )

            else:

                print()

                print("=" * 60)

                print(
                    "ALL PIPELINE ATTEMPTS FAILED"
                )

                print("=" * 60)

                print(
                    f"Last error: {e}"
                )

                print("=" * 60)


    if last_exception is not None:

        raise last_exception


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_pipeline()

    # --------------------------------------------------------
    # RETRY MODE
    # --------------------------------------------------------
    #
    # If you want automatic retry:
    #
    # run_pipeline_with_retry()
    # --------------------------------------------------------
