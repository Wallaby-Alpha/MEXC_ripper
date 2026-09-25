"""Diagnostic script to test WEEX API credentials and pinpoint [-1049] errors."""
import os
import sys
import time
import hmac
import hashlib
import base64
import json
from pathlib import Path
from dotenv import load_dotenv
import httpx

# Force load .env from the local directory with override
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
    print(f"[✓] Loaded .env from: {env_path}")
else:
    load_dotenv(override=True)
    print(f"[!] Warning: {env_path} not found, loaded from system env.")

api_key = os.getenv("WEEX_API_KEY", "")
api_secret = os.getenv("WEEX_API_SECRET", "")
passphrase = os.getenv("WEEX_PASSPHRASE", "")

print("\n--- CREDENTIAL FORMAT CHECK ---")
print(f"API Key:     Length {len(api_key):<2} | First 4: '{api_key[:4]}...' | Last 4: '...{api_key[-4:] if len(api_key)>=4 else ''}'")
print(f"API Secret:  Length {len(api_secret):<2} | First 4: '{api_secret[:4]}...' | Last 4: '...{api_secret[-4:] if len(api_secret)>=4 else ''}'")
print(f"Passphrase:  Length {len(passphrase):<2} | Raw representation: {repr(passphrase)}")

has_issues = False
if api_key != api_key.strip():
    print("⚠️ WARNING: WEEX_API_KEY has leading/trailing whitespace!")
    has_issues = True
if api_secret != api_secret.strip():
    print("⚠️ WARNING: WEEX_API_SECRET has leading/trailing whitespace!")
    has_issues = True
if passphrase != passphrase.strip():
    print("⚠️ WARNING: WEEX_PASSPHRASE has leading/trailing whitespace or newline (\\r / \\n)!")
    has_issues = True
if passphrase.startswith('"') and passphrase.endswith('"'):
    print("⚠️ WARNING: WEEX_PASSPHRASE has literal double quotes around it in .env!")
    has_issues = True
if passphrase.startswith("'") and passphrase.endswith("'"):
    print("⚠️ WARNING: WEEX_PASSPHRASE has literal single quotes around it in .env!")
    has_issues = True

clean_key = api_key.strip().strip("'\"")
clean_secret = api_secret.strip().strip("'\"")
clean_pass = passphrase.strip().strip("'\"")

if not clean_key or not clean_secret or not clean_pass:
    print("\n❌ ERROR: One or more WEEX credentials are empty in .env!")
    sys.exit(1)

def test_auth(k, s, p, label="Cleaned Credentials"):
    print(f"\n--- TESTING WEEX CONTRACT AUTH ({label}) ---")
    timestamp = str(int(time.time() * 1000))
    request_path = "/capi/v3/account/balance"
    method = "GET"
    body = ""
    
    # Signature: timestamp + METHOD + requestPath + body
    message = f"{timestamp}{method.upper()}{request_path}{body}"
    mac = hmac.new(s.encode("utf-8"), message.encode("utf-8"), hashlib.sha256)
    sign = base64.b64encode(mac.digest()).decode("utf-8")
    
    headers = {
        "ACCESS-KEY": k,
        "ACCESS-SIGN": sign,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": p,
        "Content-Type": "application/json",
        "User-Agent": "MEXC-WEEX-Momentum-Scanner/1.0",
    }
    
    url = f"https://api-contract.weex.com{request_path}"
    try:
        with httpx.Client(timeout=10.0) as client:
            res = client.get(url, headers=headers)
            print(f"HTTP Status: {res.status_code}")
            try:
                data = res.json()
                code = data.get("code")
                msg = data.get("msg")
                print(f"WEEX Response Code: {code}")
                print(f"WEEX Response Msg:  {msg}")
                
                if code in ("0", "00000", "200") or str(code) == "0":
                    print("\n🎉 SUCCESS! WEEX API authentication verified!")
                    assets = data.get("data", [])
                    usdt_balance = "0.00"
                    if isinstance(assets, list):
                        for a in assets:
                            if a.get("coinName", "").upper() == "USDT" or a.get("marginCoin", "").upper() == "USDT":
                                usdt_balance = a.get("available") or a.get("equity") or a.get("accountNormal", "0")
                    print(f"Available Futures Margin: {usdt_balance} USDT")
                    return True
                else:
                    print(f"\n❌ FAILED with code [{code}]: {msg}")
                    return False
            except Exception:
                print(f"Raw Response: {res.text}")
                return False
    except Exception as exc:
        print(f"Connection Error: {exc}")
        return False

# Test 1: Cleaned credentials
success = test_auth(clean_key, clean_secret, clean_pass, "Sanitized from .env")

# If failed, test variations (e.g. if quotes or whitespace made a difference)
if not success and (clean_pass != passphrase or clean_key != api_key):
    print("\nRetrying with raw unstripped values...")
    test_auth(api_key, api_secret, passphrase, "Raw .env values")

print("\n========================================================")
print("DIAGNOSTIC SUMMARY:")
if success:
    print("✅ Credentials are 100% valid! The bot can trade live.")
else:
    print("❌ WEEX rejected the credentials with [-1049].")
    print("Common causes for [-1049]:")
    print("1. Passphrase mismatch: WEEX API Passphrase is NOT your account login password.")
    print("   It is the custom phrase you typed when creating this specific API Key.")
    print("2. Secret Key error: If even 1 character was truncated when copying, signature fails.")
    print("3. Wrong Account: If this is a Sub-Account key, make sure you use that sub-account's passphrase.")
    print("4. Permissions: Ensure 'Futures Trading / Contract Trading' is checked on the WEEX API management page.")
print("========================================================\n")
