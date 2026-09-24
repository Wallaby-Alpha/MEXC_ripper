import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env
load_dotenv()

from src.execution.weex_client import WeexClient

def main():
    print("=" * 60)
    print(" 🔑 Testing WEEX Futures API Authentication")
    print("=" * 60)
    
    api_key = os.getenv("WEEX_API_KEY", "")
    api_secret = os.getenv("WEEX_API_SECRET", "")
    passphrase = os.getenv("WEEX_PASSPHRASE", "")
    
    print(f"API Key present:    {'YES (length ' + str(len(api_key)) + ')' if api_key else 'NO (EMPTY)'}")
    print(f"API Secret present: {'YES (length ' + str(len(api_secret)) + ')' if api_secret else 'NO (EMPTY)'}")
    print(f"Passphrase present: {'YES (length ' + str(len(passphrase)) + ')' if passphrase else 'NO (EMPTY)'}")
    
    if not api_key or not api_secret or not passphrase:
        print("\n❌ Error: One or more WEEX credentials are missing in your .env file!")
        print("Please edit .env: nano .env")
        return
        
    client = WeexClient(api_key=api_key, api_secret=api_secret, passphrase=passphrase)
    
    print("\n[1] Testing connection to WEEX Contract API (/capi/v3/account/balance)...")
    res = client.get_account_assets(is_contract=True)
    
    code = str(res.get("code", ""))
    msg = res.get("msg") or res.get("errorMessage") or ""
    
    if code in ("0", "00000", "200") or "data" in res:
        data = res.get("data", res)
        print("✅ SUCCESS! WEEX API key is 100% valid and authenticated.")
        print(f"Account Response: {data}")
    else:
        print(f"❌ WEEX API Authentication FAILED!")
        print(f"Error Code: {code}")
        print(f"Error Message: {msg}")
        print("\nTroubleshooting Tips:")
        print("1. Did you delete or regenerate the API Key on WEEX? (Check WEEX -> API Management)")
        print("2. Is the Passphrase exact (case-sensitive)?")
        print("3. Are 'Futures / Contract Trading' permissions enabled on the key?")
        print("4. Is IP Whitelisting blocking your Droplet IP address?")

if __name__ == "__main__":
    main()
