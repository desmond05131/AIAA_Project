import requests
import json
from datetime import datetime

# ================= CONFIGURATION =================
BASE_URL = "http://localhost:8015"
USER_ID = "ADMIN"
PASSWORD = "ADMIN"
TOKEN = "FK98DL-2AAAAA-AAAAAA-AAAAAA-ABLUB5-YR6ABK-DVAC8P-F5BQ7G"
# =================================================

def scan_database():
    print("🕵️ AUTOCOUNT DATA DETECTIVE")
    print("==========================")

    # 1. Login
    print("[1] Logging in...")
    try:
        r = requests.post(f"{BASE_URL}/api/v3/Login", 
                         json={"UserID": USER_ID, "Password": PASSWORD, "Token": TOKEN}, timeout=5)
        if r.status_code == 200:
            auth_key = r.json()[0].get("JWTToken")
            print("    ✅ Logged In")
        else:
            print(f"    ❌ Login Failed: {r.text}")
            return
    except Exception as e:
        print(f"    ❌ Connection Error: {e}")
        return

    headers = {"Content-Type": "application/json", "Authorization": auth_key}
    
    # Define a wide range to catch OLD data
    payload = {"DateFrom": "2020/01/01", "DateTo": datetime.now().strftime("%Y/%m/%d")}

    # ----------------------------------------------------
    # CHECK 1: INVOICES (Revenue)
    # ----------------------------------------------------
    print("\n[2] Scanning INVOICES (2020 - Now)...")
    try:
        r = requests.post(f"{BASE_URL}/api/Invoice/GetInvoice", json=payload, headers=headers)
        if r.status_code == 200:
            items = r.json().get("ResultTable", [])
            valid_items = [i for i in items if i.get("Cancelled") != "T"]
            
            print(f"    📂 Found {len(items)} total records.")
            print(f"    ✅ Found {len(valid_items)} ACTIVE (Non-Cancelled) Invoices.")
            
            if valid_items:
                last_inv = valid_items[-1] # Get the most recent one
                date = last_inv.get("DocDate", "")[:10]
                total = last_inv.get("FinalTotal", last_inv.get("NetTotal", 0))
                print(f"    💡 HINT: Try asking for sales on: {date}")
                print(f"       (Doc: {last_inv.get('DocNo')} | Amt: {total})")
        else:
            print(f"    ❌ Error {r.status_code}")
    except Exception as e:
        print(f"    ❌ Failed: {e}")

    # ----------------------------------------------------
    # CHECK 2: SALES ORDERS (Bookings)
    # ----------------------------------------------------
    print("\n[3] Scanning SALES ORDERS (2020 - Now)...")
    try:
        r = requests.post(f"{BASE_URL}/api/SalesOrder/GetSalesOrder", json=payload, headers=headers)
        if r.status_code == 200:
            items = r.json().get("ResultTable", [])
            valid_items = [i for i in items if i.get("Cancelled") != "T"]
            
            print(f"    📂 Found {len(items)} total records.")
            print(f"    ✅ Found {len(valid_items)} ACTIVE Sales Orders.")
            
            if valid_items:
                # Print the last 3 dates found
                print("    📅 Valid Dates found in Sales Orders:")
                for item in valid_items[-3:]:
                    date = item.get("DocDate", "")[:10]
                    total = item.get("FinalTotal", item.get("NetTotal", 0))
                    print(f"       - {date} (RM {total})")
        else:
            print(f"    ⚠️ Endpoint might differ or be empty (Status: {r.status_code})")
    except Exception as e:
        print(f"    ❌ Failed: {e}")

if __name__ == "__main__":
    scan_database()