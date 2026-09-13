import psycopg2
from psycopg2.extras import execute_values
import pandas as pd

# =========================
# GENERIC CLEAN FUNCTION
# =========================
def clean_value(v):
    if pd.isna(v):
        return None
    if isinstance(v, list):
        return ",".join(map(str, v))
    return v


# =========================
# GENERIC SYNC FUNCTION
# =========================
def sync_to_supabase(df, table_name, primary_key, db_url, page_size=500):

    if df is None or df.empty:
        print("⚠ No data to sync")
        return

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    df = df.copy()

    # =========================
    # CLEAN ALL OBJECT COLUMNS SAFELY
    # =========================
    df = df.where(pd.notnull(df), None)

    # =========================
    # ENSURE PRIMARY KEY CLEAN
    # =========================
    if primary_key in df.columns:
        df[primary_key] = df[primary_key].astype(str).str.strip()

    # =========================
    # DROP DUPLICATES BY PRIMARY KEY
    # =========================
    if primary_key in df.columns:
        df = df.drop_duplicates(subset=[primary_key])

    # =========================
    # COLUMNS
    # =========================
    columns = list(df.columns)

    # =========================
    # VALUES
    # =========================
    values = [
        tuple(clean_value(v) for v in row)
        for row in df.to_numpy()
    ]

    print(f"📦 Syncing {len(values)} rows into {table_name}...")

    # =========================
    # SAFE COLUMN SQL
    # =========================
    cols_sql = ",".join([f'"{c}"' for c in columns])

    # =========================
    # UPDATE PART (EXCLUDE PK)
    # =========================
    update_sql = ",".join([
        f'"{c}" = EXCLUDED."{c}"'
        for c in columns
        if c != primary_key
    ])

    # =========================
    # UPSERT QUERY
    # =========================
    query = f"""
        INSERT INTO {table_name} ({cols_sql})
        VALUES %s
        ON CONFLICT ("{primary_key}")
        DO UPDATE SET {update_sql}
    """

    execute_values(cur, query, values, page_size=page_size)

    conn.commit()
    cur.close()
    conn.close()

    print(f"🚀 Sync Completed → {table_name}")