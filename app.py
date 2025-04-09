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
pending_queue = Queue(maxsize=2)
results_store = {}
completed_timestamps = {}
failed_numbers = set()
lock = threading.Lock()

RESULT_EXPIRY = timedelta(minutes=20)
PENDING_EXPIRY = timedelta(minutes=6)


def clean_old_data():
    now = datetime.utcnow()
    keys_to_delete = [num for num, ts in completed_timestamps.items() if now - ts > RESULT_EXPIRY]
    for num in keys_to_delete:
        results_store.pop(num, None)
        completed_timestamps.pop(num, None)

    # Clean up pending queue
    temp_list = []
    while not pending_queue.empty():
        temp_list.append(pending_queue.get())
    for num in temp_list:
        if num in completed_timestamps and now - completed_timestamps[num] <= PENDING_EXPIRY:
            pending_queue.put(num)


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
    try:
        driver = webdriver.Chrome(options=options)
        driver.get("https://www.thecallbomber.in")

        input_box = driver.find_element(By.TAG_NAME, "input")
        input_box.send_keys(number)
        driver.find_element(By.ID, "terms").click()

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(2)

        driver.find_element(By.ID, "submit").click()
        time.sleep(4)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(2)

        final_url = driver.current_url

        with lock:
            results_store[number] = final_url
            completed_timestamps[number] = datetime.utcnow()

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            failed_numbers.add(number)
    finally:
        if driver:
            driver.quit()
        time.sleep(5)  # Stabilize CPU
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
    clean_old_data()
    number = request.args.get("number")

    if not number or not re.fullmatch(r"\d{10}", number):
        return jsonify({"error": "Invalid or missing 10-digit number"}), 400

    with lock:
        if number in results_store:
            return jsonify({"status": "Already processed", "url": results_store[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            if number not in list(pending_queue.queue):
                if pending_queue.qsize() < pending_queue.maxsize:
                    pending_queue.put(number)
                    return jsonify({"status": "Machine busy, added to queue", "pending": pending_queue.qsize()})
                else:
                    return jsonify({"status": "Pending list full"}), 429
            else:
                return jsonify({"status": "Already in queue"})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    clean_old_data()
    with lock:
        return jsonify({
            "is_running": is_running,
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": results_store.get(current_number),
            "completed_timestamps": {k: v.isoformat() for k, v in completed_timestamps.items()}
        })


@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if number in results_store:
            return jsonify({"status": "success", "url": results_store[number], "completed_at": completed_timestamps[number].isoformat()})
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
            return jsonify({"status": f"{number} removed from pending queue"})
        else:
            return jsonify({"status": f"{number} not in pending queue"})


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "stored_results": len(results_store)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
