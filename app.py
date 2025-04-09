from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from queue import Queue
import json
from datetime import datetime, timedelta
import os

app = Flask(__name__)

DATA_FILE = "completed_data.json"
completed_data = {}

def load_data():
    global completed_data
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            try:
                completed_data = json.load(f)
            except json.JSONDecodeError:
                completed_data = {}

def save_data():
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(completed_data, f)
        print("[✅] Data saved to file")
    except Exception as e:
        print(f"[❌ Save failed] {e}")

load_data()

is_running = False
current_number = None
pending_queue = Queue()
lock = threading.Lock()

PENDING_LIMIT = 2
RESULT_EXPIRY = timedelta(minutes=20)

def run_browser(number):
    global is_running, current_number
    with lock:
        is_running = True
        current_number = number

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    final_url = None
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
        print(f"[✔️] Final URL captured: {final_url}")

    except Exception as e:
        print(f"[❌ ERROR] {e}")
    finally:
        if final_url:
            with lock:
                completed_data[number] = {
                    "url": final_url,
                    "timestamp": datetime.now().isoformat()
                }
                save_data()
        time.sleep(5)
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
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Insufficient number"}), 400

    with lock:
        # Check if already processed within expiry
        data = completed_data.get(number)
        if data:
            ts = datetime.fromisoformat(data["timestamp"])
            if datetime.now() - ts <= RESULT_EXPIRY:
                return jsonify({"status": "Already completed", "url": data["url"]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif number not in list(pending_queue.queue):
                if pending_queue.qsize() < PENDING_LIMIT:
                    pending_queue.put(number)
                    return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})
                else:
                    return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
            else:
                return jsonify({"status": "Already in queue", "pending_count": pending_queue.qsize()})
        else:
            threading.Thread(target=run_browser, args=(number,)).start()
            return jsonify({"status": "Started", "number": number})

@app.route("/status")
def status():
    with lock:
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": completed_data.get(current_number, {}).get("url") if current_number else None,
            "timestamps": {k: v["timestamp"] for k, v in completed_data.items()}
        })

@app.route("/results")
def results():
    number = request.args.get("number", "")
    with lock:
        data = completed_data.get(number)
        if data:
            return jsonify({"status": "Found", "url": data["url"]})
        return jsonify({"status": "Result not found"})

@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

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

@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "stored_results_count": len(completed_data)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
