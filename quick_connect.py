import requests
import os

print("Testing Python Requests Connectivity...")
print(f"Environment HTTP_PROXY: {os.environ.get('HTTP_PROXY')}")
print(f"Environment HTTPS_PROXY: {os.environ.get('HTTPS_PROXY')}")

try:
    print("Requesting google.com...")
    resp = requests.get("https://www.google.com", timeout=5)
    print(f"Google Status: {resp.status_code}")
except Exception as e:
    print(f"Google Failed: {e}")

try:
    print("Requesting binance fapi...")
    resp = requests.get("https://fapi.binance.com/fapi/v1/time", timeout=5)
    print(f"Binance Status: {resp.status_code}")
    print(f"Binance Text: {resp.text}")
except Exception as e:
    print(f"Binance Failed: {e}")
