from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from queue import Queue
from datetime import datetime, timedelta

app = Flask(__name__)

is_running = False
current_number = None
pending_queue = Queue()
latest_result = {}
failed_numbers = set()
completed_timestamps = {}
lock = threading.Lock()

LAST_PAGE_URL = None
MAX_PENDING = 15
MAX_RESULTS = 60
RESULT_EXPIRY_MINUTES = 20
PENDING_CLEANUP_BATCH = 20


def run_browser(number):
    global is_running, current_number, LAST_PAGE_URL
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
        time.sleep(10)

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(3)

        driver.find_element(By.ID, "submit").click()
        time.sleep(10)

        driver.find_element(By.ID, "verify_button").click()

        LAST_PAGE_URL = driver.current_url

        with lock:
            latest_result[number] = LAST_PAGE_URL
            completed_timestamps[number] = datetime.now()
            if len(latest_result) > MAX_RESULTS:
                oldest = list(latest_result.keys())[0]
                del latest_result[oldest]
                if oldest in completed_timestamps:
                    del completed_timestamps[oldest]

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            failed_numbers.add(number)
    finally:
        driver.quit()
        time.sleep(5)
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    global is_running
    with lock:
        cleanup_pending_queue()
        if not pending_queue.empty():
            next_number = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()


def cleanup_pending_queue():
    with lock:
        for _ in range(min(PENDING_CLEANUP_BATCH, pending_queue.qsize())):
            pending_queue.get()


def cleanup_old_results():
    now = datetime.now()
    with lock:
        to_delete = [num for num, t in completed_timestamps.items() if now - t > timedelta(minutes=RESULT_EXPIRY_MINUTES)]
        for num in to_delete:
            latest_result.pop(num, None)
            completed_timestamps.pop(num, None)

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number:
        return jsonify({"error": "number is required"}), 400
    if not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Insufficient number: must be exactly 10 digits"}), 400

    with lock:
        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif number not in list(pending_queue.queue):
                if pending_queue.qsize() < MAX_PENDING:
                    pending_queue.put(number)
                    return jsonify({"status": "Machine busy, added to queue"})
                else:
                    return jsonify({"status": "Queue full"}), 429
            else:
                return jsonify({"status": "Already in queue"})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

@app.route("/status")
def status():
    cleanup_old_results()
    with lock:
        return jsonify({
            "status": "Active" if is_running else "Available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": LAST_PAGE_URL,
            "completed_timestamps": {k: v.strftime('%Y-%m-%d %H:%M:%S') for k, v in completed_timestamps.items()}
        })

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

@app.route("/clear")
def clear():
    with lock:
        pending_queue.queue.clear()
        return jsonify({"status": "All pending numbers cleared"})

@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        url = latest_result.get(number)
        if url:
            return jsonify({"number": number, "result_url": url})
        else:
            return jsonify({"status": "No result available for this number"})

@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "successful_count": len(latest_result)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
