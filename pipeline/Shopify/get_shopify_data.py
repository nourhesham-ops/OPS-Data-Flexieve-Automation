import requests
import pandas as pd
from dotenv import load_dotenv
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from functools import lru_cache

BRANCH_MAP = {
    "110296596755": "Green Plaza",
    "108089147667": "Nasr City Office",
    "107452596499": "City Stars",
    "103940391187": "Alexandria Gov",
    "113302110483": "We Expoo"
}

BATCH_SIZE = 500
MAX_WORKERS = 8

PAYMENT_STATUS_MAP = {
    "paid": "paid",
    "fully_paid": "paid",
    "authorized": "paid",
    "partially_paid": "partially_paid",
    "partially_refunded": "partially_paid",
    "refunded": "refunded",
    "voided": "refunded",
}

def safe(v):
    return None if v is None else v

def get_single_payment_method(payment_gateway_names):
    if not payment_gateway_names:
        return None
    return payment_gateway_names[0].strip() if payment_gateway_names[0] else None

def resolve_status(order):
    # FIRST: Check if order is refunded (highest priority)
    financial_status = order.get("displayFinancialStatus", "").lower()
    if financial_status == "refunded":
        return "cancelled"
    
    # SECOND: Check if cancelled
    if order.get("cancelledAt") is not None:
        return "cancelled"
    
    # THIRD: Check fulfillment status
    status = order.get("displayFulfillmentStatus")
    if status:
        status = status.lower().strip()
        return status if status else "unfulfilled"
    
    return "unfulfilled"

def resolve_payment_status(order):
    financial_status = order.get("displayFinancialStatus")
    if not financial_status:
        return "unpaid"
    
    financial_status = financial_status.lower().strip()
    
    if financial_status in PAYMENT_STATUS_MAP:
        return PAYMENT_STATUS_MAP[financial_status]
    elif financial_status == "pending":
        return "unpaid"
    else:
        return financial_status

@lru_cache(maxsize=128)
def get_branch_name(branch_id: Optional[str]) -> str:
    if not branch_id:
        return None
    return BRANCH_MAP.get(branch_id, branch_id)

def extract_address_field(order: Dict, field: str) -> str:
    shipping = order.get("shippingAddress")
    if shipping:
        value = shipping.get(field)
        if value:
            return value
    
    billing = order.get("billingAddress")
    if billing:
        return billing.get(field)
    
    return None

def get_discount_amount(order: Dict) -> float:
    """
    استخراج قيمة الخصم من الطلب من الحقول المتاحة
    """
    # 1. محاولة الحصول على currentTotalDiscountsSet
    current_discount_data = order.get("currentTotalDiscountsSet")
    if current_discount_data:
        shop_money = current_discount_data.get("shopMoney")
        if shop_money:
            amount = shop_money.get("amount")
            if amount is not None:
                try:
                    return float(amount)
                except (ValueError, TypeError):
                    pass
    
    # 2. محاولة الحصول على totalDiscountsSet
    total_discount_data = order.get("totalDiscountsSet")
    if total_discount_data:
        shop_money = total_discount_data.get("shopMoney")
        if shop_money:
            amount = shop_money.get("amount")
            if amount is not None:
                try:
                    return float(amount)
                except (ValueError, TypeError):
                    pass
    
    # 3. محاولة حساب الخصم من الفرق بين subtotal و total
    # (طريقة احتياطية)
    subtotal_data = order.get("subtotalPriceSet", {})
    total_data = order.get("totalPriceSet", {})
    
    subtotal_amount = subtotal_data.get("shopMoney", {}).get("amount")
    total_amount = total_data.get("shopMoney", {}).get("amount")
    
    if subtotal_amount is not None and total_amount is not None:
        try:
            subtotal = float(subtotal_amount)
            total = float(total_amount)
            # الخصم = الإجمالي الفرعي - الإجمالي الكلي
            # (مع تجاهل تكلفة الشحن إذا كانت موجودة)
            shipping_data = order.get("totalShippingPriceSet", {})
            shipping_amount = shipping_data.get("shopMoney", {}).get("amount")
            if shipping_amount is not None:
                shipping = float(shipping_amount)
                # إذا كان الإجمالي الكلي يشمل الشحن
                discount = subtotal - (total - shipping)
            else:
                discount = subtotal - total
            
            if discount > 0:
                return round(discount, 2)
        except (ValueError, TypeError):
            pass
    
    # 4. إذا لم يتم العثور على أي خصم
    return 0.0

def fetch_batch(session, url, headers, cursor, query_filter):
    query = """
    query ($cursor: String, $queryFilter: String!) {
      orders(first: 250, after: $cursor, query: $queryFilter) {
        pageInfo { hasNextPage endCursor }
        edges { node { 
          name createdAt updatedAt cancelledAt displayFulfillmentStatus
          displayFinancialStatus sourceName
          paymentGatewayNames discountCodes tags
          shippingAddress { name phone province country address1 address2 city zip }
          billingAddress { name phone province country address1 address2 city zip }
          subtotalPriceSet { shopMoney { amount } }
          totalPriceSet { shopMoney { amount } }
          totalShippingPriceSet { shopMoney { amount } }
          totalDiscountsSet { shopMoney { amount } }
          currentTotalDiscountsSet { shopMoney { amount } }
          lineItems(first: 250) {
            edges { node { name title sku quantity currentQuantity
              originalUnitPriceSet { shopMoney { amount } }
              discountedTotalSet { shopMoney { amount } }
              product { productType }
            } }
          }
          fulfillments(first: 100) { 
            createdAt 
            trackingInfo { 
              number
              company
            } 
            location { id } 
          }
        } }
      }
    }
    """
    
    variables = {"cursor": cursor, "queryFilter": query_filter}
    
    try:
        response = session.post(url, headers=headers, json={"query": query, "variables": variables}, timeout=30)
        
        if response.status_code != 200:
            print(f"Status code error: {response.status_code}")
            return [], None
        
        result = response.json()
        
        if "errors" in result:
            print(f"GraphQL errors: {result['errors']}")
            return [], None
        
        data = result.get("data", {}).get("orders", {})
        orders = [edge["node"] for edge in data.get("edges", [])]
        page_info = data.get("pageInfo", {})
        next_cursor = page_info.get("endCursor") if page_info.get("hasNextPage") else None
        
        return orders, next_cursor
    except Exception as e:
        print(f"Batch error: {e}")
        return [], None

def fetch_all_orders(start_date: str, date_field: str, include_cancelled: bool = True) -> List[Dict]:
    load_dotenv()
    store_url = os.getenv("SHOPIFY_STORE_URL")
    access_token = os.getenv("SHOPIFY_ACCESS_TOKEN")
    
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json"
    }
    url = f"https://{store_url}/admin/api/2024-10/graphql.json"
    
    query_filter = f"{date_field}:>={start_date}"
    
    print(f"Query filter: {query_filter}")
    print(f"Fetching ALL orders with {date_field} after {start_date} (including refunded, cancelled, etc.)")
    
    all_orders = []
    
    with requests.Session() as session:
        session.headers.update(headers)
        
        current_cursor = None
        batch_num = 0
        
        while True:
            batch_num += 1
            batch, next_cursor = fetch_batch(session, url, headers, current_cursor, query_filter)
            
            if not batch:
                break
            
            all_orders.extend(batch)
            print(f"Batch {batch_num}: fetched {len(batch)} orders (total: {len(all_orders)})", end="\r")
            
            if not next_cursor:
                break
            
            current_cursor = next_cursor
    
    print(f"\nTotal orders fetched: {len(all_orders)}")
    
    # Show breakdown by status for debugging
    cancelled_count = sum(1 for o in all_orders if o.get("cancelledAt"))
    refunded_count = sum(1 for o in all_orders if o.get("displayFinancialStatus", "").lower() == "refunded")
    pos_count = sum(1 for o in all_orders if o.get("sourceName") == "pos" or o.get("sourceName") == "shopify_pos")
    
    print(f"Cancelled: {cancelled_count}")
    print(f"Refunded: {refunded_count}")
    print(f"POS Orders: {pos_count}")
    print(f"Other: {len(all_orders) - cancelled_count - refunded_count}")
    
    return all_orders

def process_single_order(order: Dict) -> List[Dict]:
    """Process a single order into multiple rows (one per line item)"""
    rows = []
    
    status = resolve_status(order)
    payment_methods = order.get("paymentGatewayNames") or []
    payment_single = get_single_payment_method(payment_methods)
    
    # استخدام الدالة المحدثة للحصول على قيمة الخصم
    current_discount = get_discount_amount(order)
    
    shipping_cost = order.get("totalShippingPriceSet", {}).get("shopMoney", {}).get("amount")
    if shipping_cost is not None:
        try:
            shipping_cost = float(shipping_cost)
        except (ValueError, TypeError):
            shipping_cost = 0.0
    else:
        shipping_cost = 0.0
    
    fulfillments = order.get("fulfillments", [])
    awb_list = []
    fulfilled_dates = []
    last_branch = None
    shipping_carrier = None
    latest_fulfillment_date = None
    
    for f in fulfillments:
        f_date = f.get("createdAt")
        if f_date:
            fulfilled_dates.append(f_date)
        
        tracking_infos = f.get("trackingInfo") or []
        for t in tracking_infos:
            if t.get("number"):
                awb_list.append(t["number"])
            if t.get("company"):
                if f_date and (latest_fulfillment_date is None or f_date > latest_fulfillment_date):
                    latest_fulfillment_date = f_date
                    shipping_carrier = t["company"]
                elif not latest_fulfillment_date:
                    shipping_carrier = t["company"]
        
        loc = f.get("location") or {}
        loc_id = loc.get("id")
        if loc_id:
            branch_id = loc_id.split("/")[-1]
            last_branch = get_branch_name(branch_id)
    
    awb = ", ".join(set(awb_list)) if awb_list else None
    branch = last_branch
    fulfilled_date = max(fulfilled_dates) if fulfilled_dates else None
    
    city = extract_address_field(order, "province")
    customer_name = extract_address_field(order, "name")
    phone = extract_address_field(order, "phone")
    
    shipping = order.get("shippingAddress") or {}
    addr1 = shipping.get("address1") or ""
    addr2 = shipping.get("address2") or ""
    street = f"{addr1} {addr2}".strip()
    if not street:
        billing = order.get("billingAddress") or {}
        addr1 = billing.get("address1") or ""
        addr2 = billing.get("address2") or ""
        street = f"{addr1} {addr2}".strip()
    
    discount_codes = order.get("discountCodes")
    discount_code = discount_codes[0] if discount_codes else None
    
    # Get payment status
    payment_status = resolve_payment_status(order)
    
    common_data = {
        "OrderID": order.get("name"),
        "Created Date": order.get("createdAt"),
        "Updated At": order.get("updatedAt"),
        "Cancelled At": order.get("cancelledAt"),
        "Fulfilled Date": fulfilled_date,
        "Fulfillment Status": status,
        "Payment Status": payment_status,
        "Payment": payment_single,
        "Discount Code": discount_code,
        "Total Discount (Updated)": current_discount,
        "Shipping Cost": shipping_cost,
        "Source Name": order.get("sourceName"),
        "Ctr Name": customer_name,
        "Phone": phone,
        "Street": street,
        "City": city,
        "Tags": order.get("tags"),
        "AWB": awb,
        "Branch": branch,
        "Shipping Carrier": shipping_carrier,
    }
    
    line_items = order.get("lineItems", {}).get("edges", [])
    has_items = False
    
    for item_edge in line_items:
        item = item_edge["node"]
        current_qty = item.get("currentQuantity")
        original_qty = item.get("quantity")
        
        qty = current_qty if current_qty is not None else original_qty
        if qty == 0:
            continue
        
        original_price = item.get("originalUnitPriceSet", {}).get("shopMoney", {}).get("amount")
        if original_price is not None:
            try:
                original_price = float(original_price)
            except (ValueError, TypeError):
                original_price = 0.0
        else:
            original_price = 0.0
        
        product_data = item.get("product") or {}
        product_type = product_data.get("productType")
        
        row = {
            **common_data,
            "SKU": item.get("sku"),
            "Product": item.get("name") or item.get("title"),
            "Product Type": product_type,
            "Quantity": qty,
            "Product Price": original_price,
            "Item Fulfillment": status,
        }
        rows.append(row)
        has_items = True
    
    # Handle orders with no items (including refunded ones)
    if not has_items:
        financial_status = order.get("displayFinancialStatus", "").lower()
        order_type = "REFUNDED_ORDER" if financial_status == "refunded" else "CANCELLED_ORDER" if status == "cancelled" else "EMPTY_ORDER"
        
        row = {
            **common_data,
            "SKU": None,
            "Product": order_type,
            "Product Type": None,
            "Quantity": 0,
            "Product Price": 0.0,
            "Item Fulfillment": status,
        }
        rows.append(row)
    
    return rows

def process_orders_parallel(orders: List[Dict], max_workers: int = MAX_WORKERS) -> pd.DataFrame:
    all_rows = []
    
    chunk_size = max(1, len(orders) // max_workers)
    chunks = [orders[i:i + chunk_size] for i in range(0, len(orders), chunk_size)]
    
    def process_chunk(chunk):
        chunk_rows = []
        for order in chunk:
            chunk_rows.extend(process_single_order(order))
        return chunk_rows
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_chunk, chunk) for chunk in chunks]
        
        for future in as_completed(futures):
            all_rows.extend(future.result())
    
    if not all_rows:
        return pd.DataFrame()
    
    df = pd.DataFrame(all_rows)
    
    date_columns = [col for col in df.columns if "Date" in col or "At" in col]
    for col in date_columns:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    
    numeric_columns = ["Product Price", "Quantity", "Total Discount (Updated)", "Shipping Cost"]
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    df = df.replace(r'^\s*$', pd.NA, regex=True)
    
    return df

def fetch_shopify_orders_graphql(start_date: str, date_field: str, include_cancelled: bool = True) -> pd.DataFrame:
    print(f"Fetching ALL orders from Shopify (including refunded, cancelled, POS) based on {date_field}...")
    orders = fetch_all_orders(start_date, date_field, include_cancelled)
    
    if not orders:
        print("No orders found!")
        return pd.DataFrame()
    
    print(f"\nProcessing {len(orders)} orders in parallel with {MAX_WORKERS} workers...")
    df = process_orders_parallel(orders)
    
    print(f"Final rows: {len(df)}")
    return df

if __name__ == "__main__":
    start_time = datetime.now()
    print(f"Started at: {start_time}")
    
    Custom_date = datetime.strptime(
        "2026-08-01",
        "%Y-%m-%d"
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    # يمكنك تغيير القيمة إلى "updated_at" أو "created_at"
    date_field = "updated_at"
    
    df = fetch_shopify_orders_graphql(Custom_date, date_field, include_cancelled=True)
    
    if not df.empty:
        df.to_csv("shopify_graphql_data_all_orders.csv", 
                  index=False, 
                  encoding="utf-8-sig",
                  compression=None)
        print(f"\nExported {len(df)} rows to CSV")
        
        # Show breakdown of order types in the exported data
        if 'Fulfillment Status' in df.columns:
            print(f"\nOrder status distribution:")
            print(df['Fulfillment Status'].value_counts())
        
        if 'Payment Status' in df.columns:
            print(f"\nPayment status distribution:")
            print(df['Payment Status'].value_counts())
        
        if 'Source Name' in df.columns:
            print(f"\nSource Name distribution:")
            print(df['Source Name'].value_counts())
        
        # إضافة إحصائية عن الخصم
        if 'Total Discount (Updated)' in df.columns:
            print(f"\nDiscount statistics:")
            print(f"  Orders with discount: {(df['Total Discount (Updated)'] > 0).sum()}")
            print(f"  Total discount amount: {df['Total Discount (Updated)'].sum():.2f}")
            print(f"  Average discount: {df['Total Discount (Updated)'].mean():.2f}")
            print(f"  Max discount: {df['Total Discount (Updated)'].max():.2f}")
    
    elapsed = datetime.now() - start_time
    print(f"\nDONE in {elapsed.total_seconds():.2f} seconds")