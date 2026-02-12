import requests
import json
from datetime import datetime, timedelta

# CONFIGURATION
BASE_URL = "http://localhost:8015"
USER_ID = "ADMIN"
PASSWORD = "ADMIN"
TOKEN = "FK98DL-2AAAAA-AAAAAA-AAAAAA-ABLUB5-YR6ABK-DVAC8P-F5BQ7G"

def run_dashboard_probe():
    print("📊 AUTOCOUNT DASHBOARD PROBE")
    print("============================")

    # 1. Login
    print("[1] Logging in...")
    login_url = f"{BASE_URL}/api/v3/Login"
    payload = {"UserID": USER_ID, "Password": PASSWORD, "Token": TOKEN}
    
    try:
        r = requests.post(login_url, json=payload, timeout=10)
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

    # ==============================================================================
    # PROBE 1: SALES INVOICE (For "Sales Today" Dashboard)
    # We guess the endpoint is /api/Invoice/GetInvoice based on standard naming
    # ==============================================================================
    print("\n[2] Probing Sales Invoices (Today)...")
    
    # Get today's date formatted as yyyy/MM/dd (Standard AutoCount Format)
    today_str = datetime.now().strftime("%Y/%m/%d")
    
    target_url = f"{BASE_URL}/api/Invoice/GetInvoice"
    
    # Payload pattern based on 'GetSalesOrder' documentation 
    inv_payload = {
        "DateFrom": "2023/01/01", # Wide range for testing
        "DateTo": "2026/12/31",
        "RecordCount": 1 # Just get one to see the JSON structure
    }
    
    try:
        r = requests.post(target_url, json=inv_payload, headers=headers)
        if r.status_code == 200:
            print("    ✅ SUCCESS: /api/Invoice/GetInvoice exists!")
            data = r.json()
            if "ResultTable" in data and len(data["ResultTable"]) > 0:
                print("    --- [INVOICE JSON STRUCTURE] ---")
                # We need to find the 'Total' or 'NetTotal' field
                item = data["ResultTable"][0]
                print(f"    Field Check: DocNo={item.get('DocNo')} | Total={item.get('FinalTotal')} or {item.get('NetTotal')}")
                print(json.dumps(item, indent=2))
            else:
                print("    ⚠️ Endpoint works, but no invoices found in date range.")
        else:
            print(f"    ❌ Endpoint Failed ({r.status_code}). Trying SalesOrder instead...")
    except Exception as e:
        print(f"    ❌ Error: {e}")

    # ==============================================================================
    # PROBE 2: DEBTOR STATEMENT (For "Accurate Aging")
    # Based on Doc Source 
    # ==============================================================================
    print("\n[3] Probing Debtor Statement (JSON Mode)...")
    
    stmt_url = f"{BASE_URL}/api/Report2/Debtor/DebtorStatement"
    
    # We need a valid Debtor Code. Using '300-F001' from your previous chats.
    stmt_payload = {
        "FromDate": "2024/01/01",
        "ToDate": today_str,
        "DebtorCode": ["300-F001"], 
        "IsIncludeZeroAmountTransaction": False,
        "PrintPDF": False, # <--- KEY: requesting JSON [cite: 928]
        "ReportName": "Debtor Statement - 6 Months"
    }
    
    try:
        r = requests.post(stmt_url, json=stmt_payload, headers=headers)
        if r.status_code == 200:
            print("    ✅ SUCCESS: Statement Data Retrieved")
            # The response might be a direct list or wrapped in an object
            print("    --- [STATEMENT DATA SNIPPET] ---")
            print(r.text[:500]) # Print first 500 chars to check structure
        else:
            print(f"    ❌ Failed: {r.status_code} - {r.text}")
    except Exception as e:
        print(f"    ❌ Error: {e}")

if __name__ == "__main__":
    run_dashboard_probe()