from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import json
import os
from queue import Queue
from datetime import datetime, timedelta

app = Flask(__name__)

DATA_FILE = "results.json"
PENDING_FILE = "pending.json"
RESULT_EXPIRY = timedelta(minutes=20)
PENDING_EXPIRY = timedelta(minutes=6)

lock = threading.Lock()
is_running = False
current_number = None
pending_queue = Queue()
completed_results = {}
completed_timestamps = {}

# Load stored data
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        try:
            data = json.load(f)
            completed_results = data.get("results", {})
            completed_timestamps = {
                k: datetime.fromisoformat(v) for k, v in data.get("timestamps", {}).items()
            }
        except Exception as e:
            print("Error loading completed results:", e)

if os.path.exists(PENDING_FILE):
    with open(PENDING_FILE, "r") as f:
        try:
            pending_list = json.load(f)
            for number in pending_list:
                pending_queue.put(number)
        except Exception as e:
            print("Error loading pending queue:", e)

def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump({
            "results": completed_results,
            "timestamps": {
                k: v.isoformat() for k, v in completed_timestamps.items()
            }
        }, f)

def save_pending():
    with open(PENDING_FILE, "w") as f:
        json.dump(list(pending_queue.queue), f)

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
        time.sleep(5)
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(2)

        driver.find_element(By.ID, "submit").click()
        time.sleep(3)
        driver.find_element(By.ID, "verify_button").click()
        time.sleep(2)

        final_url = driver.current_url

        with lock:
            completed_results[number] = final_url
            completed_timestamps[number] = datetime.now()
            save_data()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        time.sleep(5)  # Let CPU cool
        with lock:
            is_running = False
            current_number = None
        process_pending()

def process_pending():
    with lock:
        now = datetime.now()
        while not pending_queue.empty():
            next_number = pending_queue.get()
            save_pending()
            if len(next_number) == 10 and next_number.isdigit():
                threading.Thread(target=run_browser, args=(next_number,)).start()
                break

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")
    if not number or len(number) != 10 or not number.isdigit():
        return jsonify({"error": "Insufficient number. Must be 10-digit."}), 400

    now = datetime.now()
    with lock:
        # Already completed
        if number in completed_results:
            timestamp = completed_timestamps.get(number, now - RESULT_EXPIRY - timedelta(seconds=1))
            if now - timestamp <= RESULT_EXPIRY:
                return jsonify({"status": "Already completed", "url": completed_results[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif pending_queue.qsize() >= 2:
                return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
            elif number not in list(pending_queue.queue):
                pending_queue.put(number)
                save_pending()
                return jsonify({"status": "Added to pending list", "pending_count": pending_queue.qsize()})
            else:
                return jsonify({"status": "Already in pending"})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

@app.route("/status")
def status():
    with lock:
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": completed_results.get(current_number),
            "timestamps": {
                k: v.isoformat() for k, v in completed_timestamps.items()
            }
        })

@app.route("/results")
def results():
    number = request.args.get("number")
    with lock:
        if number in completed_results:
            return jsonify({"status": "success", "url": completed_results[number]})
        else:
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
            save_pending()
            return jsonify({"status": f"{number} removed from pending queue"})
        else:
            return jsonify({"status": f"{number} not in pending queue"})

@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "total_completed": len(completed_results)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
