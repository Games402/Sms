from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from threading import Lock, Thread
from queue import Queue
import time
import json
import os

app = Flask(__name__)

# Constants
RESULT_FILE = "results.json"
LOG_FILE = "logs.json"
MAX_PENDING = 2
WAIT_BEFORE_SUBMIT = 35
WAIT_BEFORE_VERIFY = 45

# Shared state
lock = Lock()
is_running = False
current_number = None
pending_queue = Queue()
results = {}
logs = {}

# Load stored data
def load_data():
    global results, logs
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, "r") as f:
            results = json.load(f)
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)

# Save result
def save_result(number, url):
    global results
    results[number] = url
    with open(RESULT_FILE, "w") as f:
        json.dump(results, f, indent=2)

# Save logs
def add_log(number, message):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    logs.setdefault(number, []).append(f"[{timestamp}] {message}")
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

# Main automation
def run_browser(number):
    global is_running, current_number
    with lock:
        is_running = True
        current_number = number
    add_log(number, "Started processing")

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

        time.sleep(WAIT_BEFORE_SUBMIT)
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(5)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(5)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(5)

        driver.find_element(By.ID, "submit").click()
        time.sleep(WAIT_BEFORE_VERIFY)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(5)

        final_url = driver.current_url
        save_result(number, final_url)
        add_log(number, f"Successfully stored URL: {final_url}")

    except Exception as e:
        add_log(number, f"Error: {str(e)}")
    finally:
        driver.quit()
        time.sleep(5)  # Cooldown
        with lock:
            is_running = False
            current_number = None
        process_pending()

# Process pending queue
def process_pending():
    if not pending_queue.empty():
        next_number = pending_queue.get()
        add_log(next_number, "Picked from queue")
        Thread(target=run_browser, args=(next_number,)).start()

# API: /start?number=
@app.route("/start")
def start():
    global is_running, current_number

    number = request.args.get("number", "").strip()
    if not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Only 10-digit number allowed"}), 400

    if number in results:
        add_log(number, "Already completed - result returned")
        return jsonify({"status": "Already completed", "url": results[number]})

    with lock:
        if is_running:
            if number == current_number:
                return jsonify({"status": "Already in progress"})
            elif number not in list(pending_queue.queue):
                if pending_queue.qsize() >= MAX_PENDING:
                    return jsonify({"status": "Pending queue full"})
                pending_queue.put(number)
                add_log(number, "Added to pending queue")
                return jsonify({
                    "status": "Machine busy, added to pending list",
                    "pending_count": pending_queue.qsize()
                })
            else:
                return jsonify({"status": "Already in queue"})

        Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

# API: /results?number=
@app.route("/results")
def get_result():
    number = request.args.get("number", "")
    url = results.get(number)
    if url:
        return jsonify({"status": "success", "url": url})
    return jsonify({"status": "Result not found"})

# API: /all_info
@app.route("/all_info")
def all_info():
    with lock:
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "pending_numbers": list(pending_queue.queue),
            "stored_numbers": list(results.keys())
        })

# API: /log?number=
@app.route("/log")
def get_log():
    number = request.args.get("number", "")
    return jsonify({"logs": logs.get(number, [])})

# Load previous session data on startup
load_data()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
