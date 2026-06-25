import time
import requests
from datetime import datetime

def check_time_sync():
    print(f"Local Time: {datetime.now()}")
    
    try:
        t0 = time.time()
        response = requests.get("https://fapi.binance.com/fapi/v1/time", timeout=5)
        t1 = time.time()
        
        server_time_ms = response.json()['serverTime']
        server_time_sec = server_time_ms / 1000.0
        
        # Latency adjustment (assume half rtt)
        rtt = t1 - t0
        latency = rtt / 2
        
        adjusted_server_time = server_time_sec + latency
        diff = adjusted_server_time - t1
        
        print(f"Server Time: {datetime.fromtimestamp(server_time_sec)}")
        print(f"RTT: {rtt*1000:.2f} ms")
        print(f"Time Offset: {diff:.3f} seconds")
        
        if abs(diff) > 1.0:
            print("❌ WARNING: Significant time drift detected!")
        else:
            print("✅ Time synchronization is good.")
            
    except Exception as e:
        print(f"Error checking time: {e}")

if __name__ == "__main__":
    check_time_sync()
