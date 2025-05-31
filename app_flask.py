from flask import Flask, render_template, jsonify, request
from flask_talisman import Talisman
import requests

app = Flask(__name__)

SELF = "'self'"
TAILWIND = "https://cdn.tailwindcss.com"
talisman_csp = {
    'default-src': [SELF],
    'script-src': [SELF, TAILWIND, "'unsafe-inline'"],
    'style-src': [SELF, "'unsafe-inline'"],
    'img-src': [SELF, "data:"]
}
Talisman(app, content_security_policy=talisman_csp)

# Color palette for Tailwind (for reference in templates):
# FCF3EA - background
# 104F6A - text
# DF7833 - accent
# 30A8A5 - secondary
# FDC399 - highlight

@app.route('/')
def home():
    # Get WhatsApp client status from Node.js app
    try:
        resp = requests.get('http://localhost:3000/status', timeout=2)
        status = resp.json()
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    return render_template('home.html', status=status, active_page='home')

@app.route('/settings')
def settings():
    try:
        resp = requests.get('http://localhost:3000/status', timeout=2)
        status = resp.json()
    except Exception as e:
        status = {'state': 'error', 'error': str(e)}
    return render_template('settings.html', status=status, active_page='settings')

if __name__ == '__main__':
    app.run(port=3002, debug=True) 