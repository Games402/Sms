import os
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from queue import Queue

# Constants
RESULT_FILE = "results.json"
LOG_FILE = "logs.json"
WAIT_BEFORE_SUBMIT = 45
WAIT_AFTER_VERIFY = 35
EXPIRY_TIME_MINUTES = 20
MAX_PENDING = 2

app = Flask(__name__)
lock = threading.Lock()
is_running = False
current_number = None
pending_queue = Queue()

# JSON Utilities
def load_json(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

def save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

# Clean expired entries (older than 20 minutes)
def clean_old_entries():
    results = load_json(RESULT_FILE)
    logs = load_json(LOG_FILE)
    cutoff = datetime.now() - timedelta(minutes=EXPIRY_TIME_MINUTES)

    new_results = {k: v for k, v in results.items() if datetime.fromisoformat(v['timestamp']) > cutoff}
    new_logs = {k: v for k, v in logs.items() if datetime.fromisoformat(v["phases"].get("1", "2000-01-01")) > cutoff}

    save_json(RESULT_FILE, new_results)
    save_json(LOG_FILE, new_logs)

# Log phases
def update_log(number, phase, message):
    logs = load_json(LOG_FILE)
    now = datetime.now().isoformat()
    if number not in logs:
        logs[number] = {"phases": {}, "progress": []}
    logs[number]["phases"][phase] = now
    logs[number]["progress"].append({
        "phase": phase,
        "message": message,
        "timestamp": now
    })
    save_json(LOG_FILE, logs)

# Browser automation function
def run_browser(number):
    global is_running, current_number
    with lock:
        is_running = True
        current_number = number

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = None
    url = None

    try:
        driver = webdriver.Chrome(options=options)
        driver.get("https://www.thecallbomber.in")

        update_log(number, "1", "Page loaded")
        input_box = driver.find_element(By.ID, "mobileNumber")
        input_box.send_keys(number)
        update_log(number, "2", "Number inserted")

        driver.find_element(By.ID, "terms").click()
        update_log(number, "3", "Checkbox clicked")

        time.sleep(WAIT_BEFORE_SUBMIT)
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, 200);")
        time.sleep(1)

        driver.find_element(By.ID, "submit").click()
        update_log(number, "4", "Form submitted")

        time.sleep(WAIT_AFTER_VERIFY)
        driver.find_element(By.ID, "verify_button").click()
        update_log(number, "5", "Verification clicked")

        time.sleep(3)
        url = driver.current_url

        results = load_json(RESULT_FILE)
        results[number] = {"url": url, "timestamp": datetime.now().isoformat()}
        save_json(RESULT_FILE, results)

    except Exception as e:
        print("Error during automation:", e)
    finally:
        if driver:
            driver.quit()
        time.sleep(5)  # Stabilize CPU

        with lock:
            is_running = False
            current_number = None
        process_pending()

# Pending queue processor
def process_pending():
    if not pending_queue.empty():
        next_number = pending_queue.get()
        threading.Thread(target=run_browser, args=(next_number,)).start()

# ========== ROUTES ==========

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")
    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Invalid number"}), 400

    clean_old_entries()
    results = load_json(RESULT_FILE)

    if number in results:
        return jsonify({"status": "Already completed", "url": results[number]["url"]})

    with lock:
        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif number in list(pending_queue.queue):
                return jsonify({"status": "Already in pending", "pending_count": pending_queue.qsize()})
            elif pending_queue.qsize() >= MAX_PENDING:
                return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
            else:
                pending_queue.put(number)
                return jsonify({"status": "Added to pending", "pending_count": pending_queue.qsize()})
        else:
            threading.Thread(target=run_browser, args=(number,)).start()
            return jsonify({"status": "Started", "number": number})

@app.route("/results")
def results():
    number = request.args.get("number")
    results = load_json(RESULT_FILE)
    if number in results:
        return jsonify({"status": "Completed", "url": results[number]["url"]})
    return jsonify({"status": "Result not found"})

@app.route("/log")
def log():
    number = request.args.get("number")
    logs = load_json(LOG_FILE)
    return jsonify(logs.get(number, {"status": "Not found"}))

@app.route("/all_info")
def all_info():
    results = load_json(RESULT_FILE)
    logs = load_json(LOG_FILE)
    return jsonify({
        "status": "active" if is_running else "available",
        "current_number": current_number,
        "pending_count": pending_queue.qsize(),
        "stored_count": len(results),
        "completed": list(results.keys()),
        "pending": list(pending_queue.queue),
        "timestamps": logs
    })

@app.route("/change_machine")
def change_machine():
    results = load_json(RESULT_FILE)
    return jsonify({
        "pending_count": pending_queue.qsize(),
        "stored_count": len(results)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
