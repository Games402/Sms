from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from queue import Queue

app = Flask(__name__)

is_running = False
current_number = None
pending_queue = Queue()
latest_result = {}
result_timestamps = {}
lock = threading.Lock()

LAST_PAGE_URL = None
MAX_RESULTS = 60
MAX_PENDING_TIME = 600  # 10 minutes


def cleanup_old_results():
    current_time = time.time()
    expired = [num for num, ts in result_timestamps.items() if current_time - ts > MAX_PENDING_TIME]
    for num in expired:
        latest_result.pop(num, None)
        result_timestamps.pop(num, None)

    # Limit results to MAX_RESULTS
    if len(latest_result) > MAX_RESULTS:
        sorted_nums = sorted(result_timestamps, key=result_timestamps.get)
        for num in sorted_nums[:-MAX_RESULTS]:
            latest_result.pop(num, None)
            result_timestamps.pop(num, None)


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
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(3)

        driver.find_element(By.ID, "submit").click()
        time.sleep(45)

        driver.find_element(By.ID, "verify_button").click()

        LAST_PAGE_URL = driver.current_url
        latest_result[number] = LAST_PAGE_URL
        result_timestamps[number] = time.time()
        cleanup_old_results()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        time.sleep(5)  # cooldown
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    global is_running
    if not pending_queue.empty():
        next_number, timestamp = pending_queue.get()
        if time.time() - timestamp <= MAX_PENDING_TIME:
            threading.Thread(target=run_browser, args=(next_number,)).start()
        else:
            process_pending()  # Skip expired and check next


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if number in latest_result:
            return jsonify({"status": "Already completed", "url": latest_result[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            if number not in [n for n, _ in list(pending_queue.queue)]:
                pending_queue.put((number, time.time()))
            return jsonify({"status": "Machine busy, added to queue"})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    with lock:
        return jsonify({
            "is_running": is_running,
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": LAST_PAGE_URL,
            "results_stored": len(latest_result)
        })


@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400
    with lock:
        if number in latest_result:
            return jsonify({"status": "done", "url": latest_result[number]})
        else:
            return jsonify({"status": "not found"})


@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        new_queue = Queue()
        removed = False
        for n, t in q_list:
            if n != number:
                new_queue.put((n, t))
            else:
                removed = True
        pending_queue.queue.clear()
        while not new_queue.empty():
            pending_queue.put(new_queue.get())
        return jsonify({"status": f"{number} removed" if removed else f"{number} not in queue"})


@app.route("/clear")
def clear():
    with lock:
        pending_queue.queue.clear()
        return jsonify({"status": "All pending numbers cleared"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
