from flask import Flask, request, jsonify
import threading
import psutil
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

app = Flask(__name__)

# Shared state
active_sessions = 0
session_lock = threading.Lock()

# Define your CPU/memory limits
CPU_THRESHOLD = 70.0  # percent
MEM_THRESHOLD_MB = 500  # MB
MAX_SESSIONS = 2  # optional

def get_system_status():
    cpu_percent = psutil.cpu_percent(interval=1)
    memory_info = psutil.virtual_memory()
    memory_used_mb = (memory_info.used / 1024) / 1024
    return cpu_percent, memory_used_mb

def can_run_new_session():
    cpu, mem = get_system_status()
    with session_lock:
        return cpu < CPU_THRESHOLD and mem < MEM_THRESHOLD_MB and active_sessions < MAX_SESSIONS

def run_automation(number):
    global active_sessions
    with session_lock:
        active_sessions += 1

    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        driver = webdriver.Chrome(options=chrome_options)

        # 👉 Your automation goes here
        driver.get("https://www.thecallbomber.in")
        # Interact with inputs, etc...
        time.sleep(600)  # Simulating wait on last page

        driver.quit()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        with session_lock:
            active_sessions -= 1

@app.route('/start')
def start():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "Missing number"}), 400

    if not can_run_new_session():
        return jsonify({"error": "System busy, try again later"}), 429

    thread = threading.Thread(target=run_automation, args=(number,))
    thread.start()

    return jsonify({"status": "Session started", "number": number})

@app.route('/status')
def status():
    cpu, mem = get_system_status()
    return jsonify({
        "cpu_percent": cpu,
        "memory_used_mb": round(mem, 2),
        "active_sessions": active_sessions
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
        
