from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import json
from datetime import datetime, timedelta
from queue import Queue
import os

app = Flask(__name__)

# Global Variables
is_running = False
current_number = None
pending_queue = Queue()
completed_data_file = "completed_data.json"
pending_file = "pending_data.json"
lock = threading.Lock()

RESULT_EXPIRY_MINUTES = 20
MAX_PENDING = 2

# Load data from JSON file if exists
def load_json_file(filename):
    if os.path.exists(filename):
        with open(filename, "r") as f:
            return json.load(f)
    return {}

# Save data to JSON file
def save_json_file(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=2)

# Load completed and pending data
completed_results = load_json_file(completed_data_file)

# Load and restore pending numbers
pending_numbers = load_json_file(pending_file).get("queue", [])
for num in pending_numbers:
    pending_queue.put(num)

# Helper to add to completed results
def store_result(number, url):
    completed_results[number] = {
        "url": url,
        "timestamp": datetime.now().isoformat()
    }
    save_json_file(completed_data_file, completed_results)

# Clean expired completed results
def cleanup_completed():
    now = datetime.now()
    expired_keys = [k for k, v in completed_results.items()
                    if datetime.fromisoformat(v["timestamp"]) + timedelta(minutes=RESULT_EXPIRY_MINUTES) < now]
    for k in expired_keys:
        del completed_results[k]
    save_json_file(completed_data_file, completed_results)

# Save current pending queue
def save_pending():
    with lock:
        data = list(pending_queue.queue)
        save_json_file(pending_file, {"queue": data})

# Main browser task
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

        input_box = driver.find_element(By.TAG_NAME, "input")
        input_box.send_keys(number)
        driver.find_element(By.ID, "terms").click()

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(1)

        driver.find_element(By.ID, "submit").click()
        time.sleep(10)
        driver.find_element(By.ID, "verify_button").click()

        time.sleep(2)  # Let the page stabilize
        last_url = driver.current_url
        store_result(number, last_url)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        try:
            driver.quit()
            time.sleep(5)
        except:
            pass
        with lock:
            is_running = False
            current_number = None
        process_pending()

# Process pending numbers
def process_pending():
    with lock:
        cleanup_completed()
        if not pending_queue.empty():
            next_number = pending_queue.get()
            save_pending()
            threading.Thread(target=run_browser, args=(next_number,)).start()

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Only 10-digit number allowed"}), 400

    cleanup_completed()

    if number in completed_results:
        result = completed_results[number]
        if datetime.fromisoformat(result["timestamp"]) + timedelta(minutes=RESULT_EXPIRY_MINUTES) > datetime.now():
            return jsonify({"status": "Already completed", "url": result["url"]})

    with lock:
        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif list(pending_queue.queue).count(number) > 0:
                return jsonify({"status": "Already in queue"})
            elif pending_queue.qsize() >= MAX_PENDING:
                return jsonify({"status": "Queue full, try later"})
            else:
                pending_queue.put(number)
                save_pending()
                return jsonify({"status": "Added to pending", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

@app.route("/status")
def status():
    cleanup_completed()
    return jsonify({
        "status": "Active" if is_running else "Available",
        "current_number": current_number,
        "pending_count": pending_queue.qsize(),
        "last_result_url": completed_results.get(current_number, {}).get("url") if current_number else None
    })

@app.route("/results")
def results():
    number = request.args.get("number")
    if number in completed_results:
        result = completed_results[number]
        return jsonify({"status": "Completed", "url": result["url"]})
    return jsonify({"status": "Result not found"})

@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"})
    with lock:
        q = list(pending_queue.queue)
        if number in q:
            q.remove(number)
            pending_queue.queue.clear()
            for item in q:
                pending_queue.put(item)
            save_pending()
            return jsonify({"status": f"{number} removed from pending queue"})
        return jsonify({"status": f"{number} not in pending queue"})

@app.route("/change_machine")
def change_machine():
    return jsonify({
        "pending_count": pending_queue.qsize(),
        "stored_count": len(completed_results)
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
