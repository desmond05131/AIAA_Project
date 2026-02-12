import requests
import json
import sys

# CONFIGURATION
BASE_URL = "http://localhost:8015"
# Use the credentials that we know work
USER_ID = "ADMIN"
PASSWORD = "ADMIN"
TOKEN = "FK98DL-2AAAAA-AAAAAA-AAAAAA-ABLUB5-YR6ABK-DVAC8P-F5BQ7G"

def run_strict_test():
    print("📜 AUTOCOUNT STRICT DOCUMENTATION TEST")
    print("=======================================")

    # ---------------------------------------------------------
    # STEP 1: LOGIN (To get the {{AuthorizationKey}})
    # ---------------------------------------------------------
    print("\n[STEP 1] Getting Authorization Key via Login...")
    login_url = f"{BASE_URL}/api/v3/Login"
    login_payload = {"UserID": USER_ID, "Password": PASSWORD, "Token" : TOKEN}
    auth_key = None
    
    try:
        # We use a standard POST, no special sessions yet
        r = requests.post(login_url, json=login_payload, timeout=10)
        
        if r.status_code == 200:
            data = r.json()
            # Handle the list wrapper as seen in your logs
            if isinstance(data, list) and len(data) > 0:
                auth_key = data[0].get("JWTToken")
                print(f"   ✅ Key Acquired: {auth_key[:20]}...")
            else:
                print(f"   ❌ Login Response format unexpected: {data}")
                sys.exit(1)
        else:
            print(f"   ❌ Login Failed: {r.status_code} - {r.text}")
            sys.exit(1)
            
    except Exception as e:
        print(f"   ❌ Connection Error: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # STEP 2: GET DEBTOR (Mimicking the Docs Exactly)
    # ---------------------------------------------------------
    print("\n[STEP 2] sending Request exactly as per Docs...")
    
    target_url = f"{BASE_URL}/api/Debtor/GetDebtor/"
    
    # DOCUMENTATION REPLICATION:
    # Header: "Authorization" : {{AuthorizationKey}}
    # Body: { "AccNo": ["300-F001"] }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": auth_key  # Passing the Raw Token
    }
    
    payload = {
        "AccNo": ["300-F001"]
    }
    
    print(f"   POST {target_url}")
    print(f"   Headers: {json.dumps(headers, indent=2)}")
    print(f"   Body:    {json.dumps(payload, indent=2)}")
    
    try:
        # Sending the request exactly as defined
        r = requests.post(target_url, json=payload, headers=headers, timeout=10)
        
        print("\n[RESPONSE]")
        print(f"   Status Code: {r.status_code}")
        
        if r.status_code == 200:
            print("   🎉 SUCCESS! The documentation logic worked.")
            print(f"   📄 Data: {r.text[:300]}")
        elif r.status_code == 500:
            print("   ❌ 500 Internal Server Error")
            print("   This confirms the server code is crashing despite correct syntax.")
            print(f"   Server Message: {r.text}")
        else:
            print(f"   ⚠️ Error: {r.text}")

    except Exception as e:
        print(f"   ❌ Request Error: {e}")

if __name__ == "__main__":
    run_strict_test()