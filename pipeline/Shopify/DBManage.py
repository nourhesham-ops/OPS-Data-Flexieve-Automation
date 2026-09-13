from datetime import datetime, timedelta, timezone
import psycopg2
import pandas as pd
from psycopg2.extras import execute_values
from dotenv import load_dotenv
import os

load_dotenv()

DB_URL = os.getenv("DB_URL_Shopify")

def clean_value(v):
    # NULL check safe
    if v is None:
        return None

    # handle pandas NA safely
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass

    # numpy scalar fix
    if hasattr(v, "item"):
        try:
            v = v.item()
        except Exception:
            pass

    # pandas Timestamp fix
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()

    # list/array fix - تجنب استخدام np.ndarray
    if isinstance(v, (list, tuple)):
        return "|".join(map(str, v))
    
    # للتعامل مع numpy arrays بدون import numpy
    if hasattr(v, '__array__') or str(type(v)).find('numpy') != -1:
        try:
            return "|".join(map(str, v))
        except:
            pass

    return v

def sync_to_supabase_shopify(df):
    if df is None or df.empty:
        print("⚠ No data")
        return

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    df = df.copy()
    df["OrderID"] = df["OrderID"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
    df = df.drop_duplicates(subset=["OrderID"])

    columns = list(df.columns)
    values = [tuple(clean_value(v) for v in row) for row in df.to_numpy()]

    print(f"📦 Syncing {len(values)} orders (SNAPSHOT MODE)...")

    cols_sql = ",".join([f'"{c.replace("%", "%%")}"' for c in columns])
    update_sql = ",".join([f'"{c.replace("%", "%%")}" = EXCLUDED."{c.replace("%", "%%")}"' 
                           for c in columns if c != "OrderID"])

    query = f"""
        INSERT INTO shopify_orders ({cols_sql})
        VALUES %s
        ON CONFLICT ("OrderID")
        DO UPDATE SET {update_sql}
    """

    execute_values(cur, query, values, page_size=500)
    conn.commit()
    cur.close()
    conn.close()
    print("Supabase ORDER SNAPSHOT SYNC Completed Successfully")


def get_last_updated_date():
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        query = """
            SELECT "Updated At"
            FROM shopify_orders
            ORDER BY "Updated At" DESC
            LIMIT 1
        """
        cur.execute(query)
        result = cur.fetchone()
        cur.close()
        conn.close()

        if result and result[0]:
            last_dt = result[0]
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            else:
                last_dt = last_dt.astimezone(timezone.utc)
            safe_dt = last_dt - timedelta(minutes=5)
            safe_date = safe_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"Last Updated At (UTC): {last_dt}")
            return safe_date
        else:
            print("No data in DB → fallback to now")
            now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
            fallback = (now_utc - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            return fallback
    except Exception as e:
        print(f"Error fetching last date: {e}")
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        fallback = (now_utc - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return fallback

