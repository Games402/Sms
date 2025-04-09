from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading, time, json, os
from queue import Queue
from datetime import datetime, timedelta

app = Flask(__name__)

# Constants
RESULT_FILE = "results.json"
MAX_PENDING = 2
WAIT_BEFORE_SUBMIT = 45
WAIT_BEFORE_VERIFY = 35
RESULT_EXPIRY = timedelta(minutes=20)

# Global state
lock = threading.Lock()
is_running = False
current_number = None
pending_queue = Queue()
results = {}
logs = {}
progress = {}

# Load results from JSON
if os.path.exists(RESULT_FILE):
    with open(RESULT_FILE, "r") as f:
        results = json.load(f)

# Save results to JSON
def save_results():
    with open(RESULT_FILE, "w") as f:
        json.dump(results, f)

# Run browser task
def run_browser(number):
    global is_running, current_number
    with lock:
        is_running = True
        current_number = number
        progress[number] = "Starting..."

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Chrome(options=options)
        driver.get("https://www.thecallbomber.in")

        progress[number] = "Inserting number..."
        input_box = driver.find_element(By.TAG_NAME, "input")
        input_box.send_keys(number)
        time.sleep(1)

        progress[number] = "Clicking checkbox..."
        driver.find_element(By.ID, "terms").click()
        time.sleep(3)

        progress[number] = "Scrolling..."
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(1)

        progress[number] = "Clicking submit..."
        driver.find_element(By.ID, "submit").click()
        time.sleep(WAIT_BEFORE_SUBMIT)

        progress[number] = "Clicking verify..."
        driver.find_element(By.ID, "verify_button").click()
        time.sleep(WAIT_BEFORE_VERIFY)

        final_url = driver.current_url
        with lock:
            results[number] = {"url": final_url, "timestamp": datetime.now().isoformat()}
            logs[number] = logs.get(number, []) + ["Completed successfully"]
        save_results()
    except Exception as e:
        logs[number] = logs.get(number, []) + [f"❌ Error: {e}"]
    finally:
        driver.quit()
        time.sleep(5)
        with lock:
            is_running = False
            current_number = None
            progress.pop(number, None)
        process_pending()

# Process next pending
def process_pending():
    if not pending_queue.empty():
        next_number = pending_queue.get()
        run_thread(next_number)

def run_thread(number):
    threading.Thread(target=run_browser, args=(number,)).start()

# Auto clean old results
def clean_old_results():
    now = datetime.now()
    to_delete = []
    for number, data in results.items():
        if datetime.fromisoformat(data["timestamp"]) + RESULT_EXPIRY < now:
            to_delete.append(number)
    for number in to_delete:
        del results[number]
    save_results()

# API: Start
@app.route("/start")
def start():
    global is_running, current_number

    number = request.args.get("number")
    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Invalid or insufficient number"}), 400

    with lock:
        clean_old_results()
        if number in results:
            return jsonify({"status": "Already completed", "url": results[number]["url"]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif pending_queue.qsize() >= MAX_PENDING:
                return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
            else:
                if number not in list(pending_queue.queue):
                    pending_queue.put(number)
                return jsonify({"status": "Added to pending list", "pending_count": pending_queue.qsize()})
        else:
            run_thread(number)
            return jsonify({"status": "Started", "number": number})

# API: Get results
@app.route("/results")
def get_result():
    number = request.args.get("number")
    with lock:
        data = results.get(number)
        if data:
            return jsonify({"status": "Completed", "url": data["url"]})
        return jsonify({"status": "Result not found"})

# API: Log per number
@app.route("/log")
def log():
    number = request.args.get("number")
    with lock:
        log_entries = logs.get(number, [])
        progress_stage = progress.get(number, "Idle")
        return jsonify({
            "log": log_entries,
            "progress": progress_stage
        })

# API: Machine info
@app.route("/all_info")
def all_info():
    with lock:
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": results.get(current_number, {}).get("url") if current_number else None,
            "completed": list(results.keys())
        })

# API: Cancel
@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    with lock:
        q_list = list(pending_queue.queue)
        if number in q_list:
            q_list.remove(number)
            pending_queue.queue.clear()
            for item in q_list:
                pending_queue.put(item)
            return jsonify({"status": f"{number} removed from pending queue"})
        else:
            return jsonify({"status": f"{number} not in pending queue"})

# API: Machine stats
@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "stored_count": len(results)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
