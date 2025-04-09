from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from queue import Queue
from datetime import datetime, timedelta
import re

app = Flask(__name__)

is_running = False
current_number = None
pending_queue = Queue()
completed_results = {}  # Stores number: (url, timestamp)
completion_timestamps = {}
lock = threading.Lock()

# Configurable constants
MAX_PENDING = 2
RESULT_EXPIRY = timedelta(minutes=20)
PENDING_EXPIRY = timedelta(minutes=6)

# Helper functions
def is_valid_number(number):
    return re.fullmatch(r"\d{10}", number) is not None

def clean_expired_data():
    now = datetime.now()
    to_delete = [number for number, (_, ts) in completed_results.items() if now - ts > RESULT_EXPIRY]
    for number in to_delete:
        completed_results.pop(number, None)
        completion_timestamps.pop(number, None)

    temp_queue = list(pending_queue.queue)
    pending_queue.queue.clear()
    for number, ts in temp_queue:
        if now - ts <= PENDING_EXPIRY:
            pending_queue.put((number, ts))

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
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(1)

        driver.find_element(By.ID, "submit").click()
        time.sleep(5)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(1)

        final_url = driver.current_url

        with lock:
            completed_results[number] = (final_url, datetime.now())
            completion_timestamps[number] = datetime.now()

        time.sleep(5)  # Let CPU cool

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        with lock:
            is_running = False
            current_number = None
        process_pending()

def process_pending():
    clean_expired_data()
    if not pending_queue.empty():
        number, _ = pending_queue.get()
        threading.Thread(target=run_browser, args=(number,)).start()

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not is_valid_number(number):
        return jsonify({"error": "Invalid or missing 10-digit number"}), 400

    clean_expired_data()

    with lock:
        if number in completed_results:
            url, timestamp = completed_results[number]
            if datetime.now() - timestamp <= RESULT_EXPIRY:
                return jsonify({"status": "Already completed", "url": url})
            else:
                completed_results.pop(number)

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif (number, _) not in list(pending_queue.queue):
                if pending_queue.qsize() >= MAX_PENDING:
                    return jsonify({"status": "Machine busy, pending list full"})
                pending_queue.put((number, datetime.now()))
                return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "Number is required"}), 400

    clean_expired_data()

    with lock:
        if number in completed_results:
            url, timestamp = completed_results[number]
            return jsonify({"status": "Completed", "url": url})
        else:
            return jsonify({"status": "Result not found"})

@app.route("/status")
def status():
    clean_expired_data()
    with lock:
        return jsonify({
            "is_running": is_running,
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_completed": list(completed_results.items())[-5:],
            "completion_timestamps": {k: v.strftime("%Y-%m-%d %H:%M:%S") for k, v in completion_timestamps.items()}
        })

@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "Number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        filtered = [(n, ts) for (n, ts) in q_list if n != number]
        pending_queue.queue.clear()
        for item in filtered:
            pending_queue.put(item)
        return jsonify({"status": f"{number} removed from pending queue"})

@app.route("/change_machine")
def change_machine():
    clean_expired_data()
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "stored_results_count": len(completed_results)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
