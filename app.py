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
completed_results = {}
completion_timestamps = {}
failed_numbers = []
lock = threading.Lock()

RESULT_TTL = 20 * 60  # 20 minutes
PENDING_CLEAN_INTERVAL = 6 * 60  # 6 minutes
MAX_PENDING = 2


def cleanup_old_results():
    now = datetime.now()
    to_delete = [num for num, ts in completion_timestamps.items()
                 if (now - ts).total_seconds() > RESULT_TTL]
    for num in to_delete:
        completed_results.pop(num, None)
        completion_timestamps.pop(num, None)


def cleanup_pending():
    with lock:
        if not pending_queue.empty():
            items = list(pending_queue.queue)
            pending_queue.queue.clear()
            for num, timestamp in items:
                if (datetime.now() - timestamp).total_seconds() <= PENDING_CLEAN_INTERVAL:
                    pending_queue.put((num, timestamp))


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
        time.sleep(2)

        driver.find_element(By.ID, "submit").click()
        time.sleep(3)
        driver.find_element(By.ID, "verify_button").click()

        result_url = driver.current_url

        with lock:
            completed_results[number] = result_url
            completion_timestamps[number] = datetime.now()

        time.sleep(5)  # Allow CPU to stabilize before quitting

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            failed_numbers.append(number)
    finally:
        driver.quit()
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    with lock:
        cleanup_old_results()
        cleanup_pending()
        if not pending_queue.empty():
            next_number, _ = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Insufficient number. Must be exactly 10 digits."}), 400

    with lock:
        if number in completed_results:
            return jsonify({"status": "Already completed", "url": completed_results[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif len(pending_queue.queue) >= MAX_PENDING:
                return jsonify({"status": "Pending list full", "pending_count": len(pending_queue.queue)})
            else:
                if number not in [num for num, _ in list(pending_queue.queue)]:
                    pending_queue.put((number, datetime.now()))
                return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    with lock:
        cleanup_old_results()
        cleanup_pending()
        return jsonify({
            "is_running": is_running,
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "completion_timestamps": {k: v.strftime("%Y-%m-%d %H:%M:%S") for k, v in completion_timestamps.items()},
            "last_result_url": completed_results.get(current_number)
        })


@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400
    with lock:
        cleanup_old_results()
        if number in completed_results:
            return jsonify({
                "number": number,
                "url": completed_results[number],
                "timestamp": completion_timestamps[number].strftime("%Y-%m-%d %H:%M:%S")
            })
        else:
            return jsonify({"status": "No result found for this number"})


@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        pending_queue.queue.clear()
        removed = False
        for item in q_list:
            if item[0] != number:
                pending_queue.put(item)
            else:
                removed = True
        return jsonify({"status": f"{number} removed from pending queue" if removed else f"{number} not in pending queue"})


@app.route("/change_machine")
def change_machine():
    with lock:
        cleanup_old_results()
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "stored_success_count": len(completed_results)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
