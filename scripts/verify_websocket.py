import websocket
import json
import time

def on_message(ws, message):
    print(f"Received: {message[:200]}")
    ws.close()

def on_error(ws, error):
    print(f"Error: {error}")

def on_close(ws, close_status_code, close_msg):
    print("Closed")

def on_open(ws):
    print("Opened connection")
    # Subscribe to ETHUSDT
    params = ["ethusdt@bookTicker"]
    payload = {
        "method": "SUBSCRIBE",
        "params": params,
        "id": 1
    }
    ws.send(json.dumps(payload))
    print("Subscribed")

if __name__ == "__main__":
    url = "wss://fstream.binance.com/ws"
    print(f"Connecting to {url}...")
    ws = websocket.WebSocketApp(url,
                                on_open=on_open,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close)
    ws.run_forever()
