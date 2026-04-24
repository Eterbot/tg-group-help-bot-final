import requests
import time
import os

URL = os.environ.get("RENDER_EXTERNAL_URL")

def ping():
    if not URL:
        print("RENDER_EXTERNAL_URL not set, skipping ping.")
        return
    try:
        response = requests.get(URL)
        print(f"Pinged {URL}, status code: {response.status_code}")
    except Exception as e:
        print(f"Error pinging {URL}: {e}")

if __name__ == "__main__":
    while True:
        ping()
        time.sleep(600) # Ping every 10 minutes
