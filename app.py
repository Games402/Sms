from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from queue import Queue
from collections import deque

app = Flask(__name__)

is_running = False
current_number = None
pending_queue = Queue()
latest_result = {}
result_timestamps = {}
failed_numbers = set()
recent_results = deque(maxlen=5)
lock = threading.Lock()

LAST_PAGE_URL = None
RESULT_EXPIRY = 20 * 60  # 20 minutes
PENDING_EXPIRY = 10 * 60  # 10 minutes

pending_timestamps = {}


def clean_old_results():
    now = time.time()
    to_delete = [num for num, ts in result_timestamps.items() if now - ts > RESULT_EXPIRY]
    for num in to_delete:
        del latest_result[num]
        del result_timestamps[num]


def clean_stale_pending():
    now = time.time()
    removed = 0
    max_remove = 20
    with lock:
        q_list = list(pending_queue.queue)
        pending_queue.queue.clear()
        for num in q_list:
            if removed < max_remove and (now - pending_timestamps.get(num, now)) > PENDING_EXPIRY:
                del pending_timestamps[num]
                removed += 1
            else:
                pending_queue.put(num)


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
        time.sleep(20)

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(4)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(4)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(4)

        driver.find_element(By.ID, "submit").click()
        time.sleep(30)

        driver.find_element(By.ID, "verify_button").click()
        LAST_PAGE_URL = driver.current_url

        with lock:
            latest_result[number] = LAST_PAGE_URL
            result_timestamps[number] = time.time()
            recent_results.append(LAST_PAGE_URL)
            if number in failed_numbers:
                failed_numbers.remove(number)

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            failed_numbers.add(number)
            if number not in list(pending_queue.queue):
                pending_queue.put(number)
                pending_timestamps[number] = time.time()

    finally:
        driver.quit()
        time.sleep(5)
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    clean_old_results()
    clean_stale_pending()
    if not pending_queue.empty():
        next_number = pending_queue.get()
        with lock:
            if next_number in pending_timestamps:
                del pending_timestamps[next_number]
        threading.Thread(target=run_browser, args=(next_number,)).start()


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif number not in list(pending_queue.queue):
                pending_queue.put(number)
                pending_timestamps[number] = time.time()
                return jsonify({"status": "Machine busy, added to queue"})
            else:
                return jsonify({"status": "Already in queue"})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    with lock:
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": LAST_PAGE_URL,
            "failed_numbers": list(failed_numbers)
        })


@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if number in latest_result:
            return jsonify({"result_url": latest_result[number]})
        return jsonify({"error": "Result not found"}), 404


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
            pending_timestamps.pop(number, None)
            return jsonify({"status": f"{number} removed from pending queue"})
        else:
            return jsonify({"status": f"{number} not in pending queue"})


@app.route("/clear")
def clear():
    with lock:
        pending_queue.queue.clear()
        pending_timestamps.clear()
        return jsonify({"status": "All pending numbers cleared"})


@app.route("/history")
def history():
    with lock:
        return jsonify({"last_5_results": list(recent_results)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
