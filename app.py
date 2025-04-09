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
completion_times = {}
lock = threading.Lock()

LAST_PAGE_URL = None
MAX_PENDING = 2
RESULT_EXPIRY_MINUTES = 20
PENDING_EXPIRY_MINUTES = 6


def cleanup_old_results():
    now = datetime.now()
    to_delete = [number for number, ts in completion_times.items()
                 if now - ts > timedelta(minutes=RESULT_EXPIRY_MINUTES)]
    for number in to_delete:
        del latest_result[number]
        del completion_times[number]


def cleanup_old_pending():
    now = datetime.now()
    items = list(pending_queue.queue)
    pending_queue.queue.clear()
    for item in items:
        if now - item[1] < timedelta(minutes=PENDING_EXPIRY_MINUTES):
            pending_queue.put(item)


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
        time.sleep(5)

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
            completion_times[number] = datetime.now()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        time.sleep(5)
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    cleanup_old_pending()
    if not pending_queue.empty():
        next_number, _ = pending_queue.get()
        threading.Thread(target=run_browser, args=(next_number,)).start()


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Insufficient number. Only 10-digit numbers allowed."}), 400

    with lock:
        cleanup_old_results()

        if number in latest_result:
            return jsonify({"status": "Already processed", "url": latest_result[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            else:
                if number not in [n for n, _ in list(pending_queue.queue)]:
                    if pending_queue.qsize() < MAX_PENDING:
                        pending_queue.put((number, datetime.now()))
                        return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})
                    else:
                        return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()}), 429
                else:
                    return jsonify({"status": "Already in queue", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number, "pending_count": pending_queue.qsize()})


@app.route("/status")
def status():
    with lock:
        cleanup_old_results()
        return jsonify({
            "machine_status": "Active" if is_running else "Available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "completed": list(completion_times.items())[-5:],
            "last_result_url": LAST_PAGE_URL
        })


@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        new_q = [(n, ts) for n, ts in q_list if n != number]
        pending_queue.queue.clear()
        for item in new_q:
            pending_queue.put(item)
        return jsonify({"status": f"{number} removed from pending queue"})


@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400
    with lock:
        if number in latest_result:
            return jsonify({"url": latest_result[number]})
        else:
            return jsonify({"status": "No result found for this number"})


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "stored_results": len(latest_result)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
