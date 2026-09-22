import os, json, urllib.request
from http.server import BaseHTTPRequestHandler

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
VERCEL_URL = os.environ.get("VERCEL_URL", "")

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        webhook_url = f"https://{VERCEL_URL}/api/webhook"
        api = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_url}"
        try:
            with urllib.request.urlopen(api, timeout=10) as r:
                result = r.read().decode()
        except Exception as e:
            result = f"Error: {e}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"webhook": webhook_url, "result": result}).encode())
