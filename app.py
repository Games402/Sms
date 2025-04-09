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
lock = threading.Lock()

MAX_PENDING = 2
RESULT_EXPIRY_MINUTES = 20
PENDING_EXPIRY_SECONDS = 360  # 6 minutes

LAST_PAGE_URL = None
failed_numbers = set()


def cleanup_old_data():
    now = datetime.now()
    expired = [num for num, ts in completion_timestamps.items()
               if now - ts > timedelta(minutes=RESULT_EXPIRY_MINUTES)]
    for num in expired:
        latest_result.pop(num, None)
        completion_timestamps.pop(num, None)

    # Clean old pending entries
    if not pending_queue.empty():
        queue_list = list(pending_queue.queue)
        filtered = [(num, ts) for num, ts in queue_list if (now - ts).total_seconds() < PENDING_EXPIRY_SECONDS]
        pending_queue.queue.clear()
        for item in filtered:
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
        if not pending_queue.empty():
            next_number, _ = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Insufficient number. Provide a 10-digit number."}), 400

    with lock:
        cleanup_old_data()

        if number in latest_result:
            return jsonify({"status": "Already completed", "result_url": latest_result[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            else:
                if number not in [num for num, _ in pending_queue.queue]:
                    if pending_queue.qsize() >= MAX_PENDING:
                        return jsonify({"status": "Machine busy, pending list full", "pending_count": pending_queue.qsize()}), 429
                    pending_queue.put((number, datetime.now()))
                return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    with lock:
        cleanup_old_data()
        return jsonify({
            "is_running": is_running,
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": LAST_PAGE_URL,
            "completed_timestamps": {k: v.strftime("%Y-%m-%d %H:%M:%S") for k, v in completion_timestamps.items()}
        })


@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400
    with lock:
        if number in latest_result:
            return jsonify({"number": number, "url": latest_result[number]})
        else:
            return jsonify({"status": "No result found for this number"})


@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        for i in range(len(q_list)):
            if q_list[i][0] == number:
                q_list.pop(i)
                break
        pending_queue.queue.clear()
        for item in q_list:
            pending_queue.put(item)
        return jsonify({"status": f"{number} removed from pending queue"})


@app.route("/clear")
def clear():
    with lock:
        pending_queue.queue.clear()
        return jsonify({"status": "All pending numbers cleared"})


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_numbers": [num for num, _ in pending_queue.queue],
            "completed_count": len(latest_result)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
