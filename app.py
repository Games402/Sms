from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from datetime import datetime, timedelta
import os
import json
from queue import Queue

app = Flask(__name__)

DATA_FILE = "results.json"
RESULT_EXPIRY = timedelta(minutes=20)
PENDING_LIMIT = 2

is_running = False
current_number = None
pending_queue = Queue()
lock = threading.Lock()
completed_data = {}  # number -> {"url": ..., "timestamp": ...}

# Load from JSON file if exists
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        try:
            completed_data = json.load(f)
        except:
            completed_data = {}

# Save to JSON file
def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(completed_data, f)

def cleanup_old_results():
    now = datetime.now()
    expired = []
    for number, data in completed_data.items():
        try:
            timestamp = datetime.fromisoformat(data["timestamp"])
            if now - timestamp > RESULT_EXPIRY:
                expired.append(number)
        except:
            expired.append(number)
    for number in expired:
        del completed_data[number]
    save_data()

def run_browser(number):
    global is_running, current_number
    with lock:
        is_running = True
        current_number = number

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Chrome(options=options)
        driver.get("https://www.thecallbomber.in")

        driver.find_element(By.TAG_NAME, "input").send_keys(number)
        driver.find_element(By.ID, "terms").click()
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(1)
        driver.find_element(By.ID, "submit").click()
        time.sleep(2)
        driver.find_element(By.ID, "verify_button").click()

        final_url = driver.current_url
        with lock:
            completed_data[number] = {
                "url": final_url,
                "timestamp": datetime.now().isoformat()
            }
            save_data()
    except Exception as e:
        print(f"[ERROR] {e}")
    finally:
        time.sleep(5)  # Stabilize
        driver.quit()
        with lock:
            is_running = False
            current_number = None
        process_pending()

def process_pending():
    with lock:
        if not pending_queue.empty():
            next_number = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number", "")
    cleanup_old_results()

    if not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Invalid number. Must be 10 digits."}), 400

    with lock:
        if number in completed_data:
            return jsonify({
                "status": "Already completed",
                "url": completed_data[number]["url"]
            })

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif number in list(pending_queue.queue):
                return jsonify({"status": "Already in pending"})
            elif pending_queue.qsize() >= PENDING_LIMIT:
                return jsonify({"status": "Pending queue full", "pending_count": pending_queue.qsize()})
            else:
                pending_queue.put(number)
                return jsonify({"status": "Added to pending list", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

@app.route("/status")
def status():
    with lock:
        cleanup_old_results()
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": completed_data.get(current_number, {}).get("url") if current_number else None
        })

@app.route("/results")
def results():
    number = request.args.get("number", "")
    if number in completed_data:
        return jsonify({
            "status": "Found",
            "url": completed_data[number]["url"]
        })
    return jsonify({"status": "Result not found"})

@app.route("/cancel")
def cancel():
    number = request.args.get("number", "")
    with lock:
        q = list(pending_queue.queue)
        if number in q:
            q.remove(number)
            pending_queue.queue.clear()
            for item in q:
                pending_queue.put(item)
            return jsonify({"status": f"{number} removed from pending list"})
        else:
            return jsonify({"status": "Number not in pending list"})

@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "total_stored": len(completed_data)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
