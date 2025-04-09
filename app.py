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
completion_timestamps = {}
failed_numbers = set()
lock = threading.Lock()

LAST_PAGE_URL = None
MAX_PENDING = 2
RESULT_RETENTION_MINUTES = 20
PENDING_CLEAN_INTERVAL = 360


def is_valid_number(number):
    return number.isdigit() and len(number) == 10


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
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(2)

        driver.find_element(By.ID, "submit").click()
        time.sleep(5)

        driver.find_element(By.ID, "verify_button").click()

        LAST_PAGE_URL = driver.current_url
        with lock:
            latest_result[number] = LAST_PAGE_URL
            completion_timestamps[number] = datetime.now()

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
    with lock:
        clean_old_results()
        clean_old_pending()
        if not pending_queue.empty():
            next_number = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()


def clean_old_results():
    cutoff = datetime.now() - timedelta(minutes=RESULT_RETENTION_MINUTES)
    for num in list(completion_timestamps):
        if completion_timestamps[num] < cutoff:
            latest_result.pop(num, None)
            completion_timestamps.pop(num, None)


def clean_old_pending():
    if pending_queue.qsize() > 0:
        temp_list = list(pending_queue.queue)
        pending_queue.queue.clear()
        for i, num in enumerate(temp_list):
            if i < 10:
                pending_queue.put(num)


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not is_valid_number(number):
        return jsonify({"error": "Number must be a 10-digit number"}), 400

    with lock:
        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif number in pending_queue.queue:
                return jsonify({"status": "Already in queue", "pending_count": pending_queue.qsize()})
            elif pending_queue.qsize() >= MAX_PENDING:
                return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()}), 429
            else:
                pending_queue.put(number)
                return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    with lock:
        return jsonify({
            "status": "Active" if is_running else "Available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": LAST_PAGE_URL,
            "completion_times": {k: v.strftime('%Y-%m-%d %H:%M:%S') for k, v in completion_timestamps.items()}
        })


@app.route("/results")
def get_result():
    number = request.args.get("number")
    with lock:
        if number in latest_result:
            return jsonify({"number": number, "url": latest_result[number]})
        return jsonify({"error": "Result not found"})


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


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_numbers": list(pending_queue.queue),
            "completed_count": len(latest_result)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
