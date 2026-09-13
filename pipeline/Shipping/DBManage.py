from psycopg2.extras import execute_values
import psycopg2
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import os

load_dotenv()


def clean_value(v):
    if pd.isna(v):
        return None

    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.to_pydatetime()

    if isinstance(v, np.datetime64):
        return pd.to_datetime(v).to_pydatetime()

    return v


def sync_to_supabase_shipping(
    df,
    db_url,
    conflict_column="AWB",
    table_name="shipments"
):
    """
    مزامنة DataFrame مع جدول في Postgres/Supabase.

    Parameters
    ----------
    df : pd.DataFrame
        البيانات المطلوب مزامنتها.

    db_url : str
        رابط قاعدة البيانات المطلوب الاتصال بها.

    conflict_column : str
        اسم العمود اللي هيتم عليه ON CONFLICT
        (لازم يكون UNIQUE أو PK).

    table_name : str
        اسم الجدول في قاعدة البيانات.
    """

    if df is None or df.empty:
        print("⚠ No data to sync.")
        return

    if not db_url:
        raise ValueError("Database URL is required.")

    if conflict_column not in df.columns:
        raise ValueError(
            f"Column '{conflict_column}' not found in DataFrame."
        )

    df = df.copy()

    # تنظيف عمود الـ conflict
    df[conflict_column] = (
        df[conflict_column]
        .astype(str)
        .str.strip()
        .str.replace(r"\.0$", "", regex=True)
    )

    # حذف القيم الفارغة
    df = df[df[conflict_column].notna()]
    df = df[df[conflict_column] != ""]
    df = df[df[conflict_column].str.lower() != "nan"]

    # الاحتفاظ بآخر سجل لكل قيمة
    df = df.drop_duplicates(
        subset=[conflict_column],
        keep="last"
    )

    if df.empty:
        print(
            f"⚠ No valid values found in '{conflict_column}'."
        )
        return

    columns = list(df.columns)

    values = [
        tuple(clean_value(v) for v in row)
        for row in df.to_numpy()
    ]

    cols_sql = ",".join(
        f'"{c}"' for c in columns
    )

    # UPDATE لكل الأعمدة ما عدا conflict column
    update_sql = ",".join(
        f'"{c}" = EXCLUDED."{c}"'
        for c in columns
        if c != conflict_column
    )

    # لو مفيش أعمدة غير conflict column
    conflict_action = (
        f"DO UPDATE SET {update_sql}"
        if update_sql
        else "DO NOTHING"
    )

    query = f"""
        INSERT INTO {table_name} ({cols_sql})
        VALUES %s
        ON CONFLICT ("{conflict_column}")
        {conflict_action};
    """

    try:
        with psycopg2.connect(db_url) as conn:
            with conn.cursor() as cur:

                execute_values(
                    cur,
                    query,
                    values,
                    page_size=1000
                )

        print(
            f"Synced {len(values)} rows successfully "
            f"(conflict on '{conflict_column}')."
        )

    except Exception as e:
        print(f"Sync failed: {e}")
        raise


# ============================================================
# أمثلة للاستخدام
# ============================================================

# Database Shipping
# sync_to_supabase_shipping(
#     df,
#     db_url=os.getenv("DB_URL_Shipping")
# )


# Database أخرى + conflict مختلف
# sync_to_supabase_shipping(
#     df,
#     db_url=os.getenv("DB_URL_Orders"),
#     conflict_column="OrderID",
#     table_name="orders"
# )


# Database Shipping + جدول مختلف
# sync_to_supabase_shipping(
#     df,
#     db_url=os.getenv("DB_URL_Shipping"),
#     conflict_column="AWB",
#     table_name="returns"
# )