import requests
import json
import datetime

# CONFIGURATION
BASE_URL = "http://localhost:8015"
USER_ID = "ADMIN"
PASSWORD = "ADMIN"
TOKEN = "FK98DL-2AAAAA-AAAAAA-AAAAAA-ABLUB5-YR6ABK-DVAC8P-F5BQ7G"

def check_stock_connection():
    print("📦 AUTOCOUNT STOCK REPORT TEST")
    print("==============================")

    # 1. Login
    print("[1] Logging in...")
    login_url = f"{BASE_URL}/api/v3/Login"
    login_payload = {"UserID": USER_ID, "Password": PASSWORD, "Token": TOKEN}
    
    try:
        r = requests.post(login_url, json=login_payload, timeout=10)
        if r.status_code == 200:
            auth_key = r.json()[0].get("JWTToken")
            print("    ✅ Logged In")
        else:
            print(f"    ❌ Login Failed: {r.text}")
            return
    except Exception as e:
        print(f"    ❌ Connection Error: {e}")
        return

    # 2. Call Stock Balance Report
    # Endpoint found in your docs: 
    target_url = f"{BASE_URL}/api/Report/Stock/StockBalance"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_key
    }
    
    # Payload based on your docs 
    # We set DateFrom to today to get current stock
    today_str = datetime.datetime.now().strftime("%Y/%m/%d")
    
    payload = {
        "DateFrom": "2023/01/01", # Set a wide range to ensure we capture data
        "IsPrintActive": True,
        "ZeroBalanceOptions": 2,  # 2 = Show All Records 
        "ShowUOMOption": 2,       # 2 = Show Smallest UOM 
        "BatchOptions": 0,
        "ItemCode": [],           # Empty = All Items
        "Location": []            # Empty = All Locations
    }
    
    print(f"[2] Fetching Stock Balance from: {target_url}")
    
    try:
        r = requests.post(target_url, json=payload, headers=headers, timeout=15)
        
        if r.status_code == 200:
            data = r.json()
            print(f"    ✅ SUCCESS! Retrieved {len(data)} stock records.")
            
            # Print the first 3 items to verify structure
            if len(data) > 0:
                print("\n--- [SAMPLE DATA] ---")
                for item in data[:3]:
                    # Extracting fields based on 
                    code = item.get('ItemCode')
                    desc = item.get('Description')
                    qty = item.get('Balance')
                    loc = item.get('Location')
                    print(f"📦 {code} | {desc} | Loc: {loc} | Qty: {qty}")
                print("---------------------\n")
            else:
                print("    ⚠️ Connection good, but no stock records returned.")
        else:
            print(f"    ❌ Failed: {r.status_code} - {r.text}")

    except Exception as e:
        print(f"    ❌ Request Error: {e}")

if __name__ == "__main__":
    check_stock_connection()