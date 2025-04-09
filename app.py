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
MAX_PENDING = 2
WAIT_1 = 45  # seconds
WAIT_2 = 35  # seconds

is_running = False
current_number = None
pending_queue = Queue()
lock = threading.Lock()

# Load stored results
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        result_data = json.load(f)
else:
    result_data = {}

def save_results():
    with open(DATA_FILE, "w") as f:
        json.dump(result_data, f, indent=2)

def is_valid_number(number):
    return number.isdigit() and len(number) == 10

def run_browser(number):
    global is_running, current_number

    with lock:
        is_running = True
        current_number = number

    url = None

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Chrome(options=options)
        driver.get("https://www.thecallbomber.in")

        driver.find_element(By.TAG_NAME, "input").send_keys(number)
        driver.find_element(By.ID, "terms").click()

        time.sleep(WAIT_1)

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(2)

        driver.find_element(By.ID, "submit").click()
        time.sleep(WAIT_2)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(5)

        url = driver.current_url
        print(f"✅ Completed for {number} with URL: {url}")

        with lock:
            result_data[number] = url
            save_results()

    except Exception as e:
        print(f"❌ Error for {number}: {e}")
        with lock:
            if number not in list(pending_queue.queue):
                if pending_queue.qsize() < MAX_PENDING:
                    pending_queue.put(number)
    finally:
        try:
            driver.quit()
        except:
            pass
        time.sleep(5)
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
    if not is_valid_number(number):
        return jsonify({"error": "Invalid or insufficient number"}), 400

    with lock:
        if number in result_data:
            return jsonify({"status": "Already completed", "url": result_data[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif number not in list(pending_queue.queue):
                if pending_queue.qsize() < MAX_PENDING:
                    pending_queue.put(number)
                    return jsonify({"status": "Machine busy, added to pending list", "pending_count": pending_queue.qsize()})
                else:
                    return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
            else:
                return jsonify({"status": "Already in pending list", "pending_count": pending_queue.qsize()})
        else:
            threading.Thread(target=run_browser, args=(number,)).start()
            return jsonify({"status": "Started", "number": number})

@app.route("/results")
def results():
    number = request.args.get("number", "")
    with lock:
        url = result_data.get(number)
        if url:
            return jsonify({"status": "Completed", "url": url})
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

@app.route("/status")
def status():
    with lock:
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": result_data.get(current_number)
        })

@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_number_count": pending_queue.qsize(),
            "total_stored": len(result_data)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
