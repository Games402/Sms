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
results = {}  # Store {number: (url, timestamp)}
lock = threading.Lock()
PENDING_LIMIT = 2
RESULT_EXPIRY = timedelta(minutes=20)
PENDING_EXPIRY = timedelta(minutes=6)

completed_timestamps = {}  # Store {number: timestamp}


def cleanup_results():
    now = datetime.now()
    to_delete = [number for number, (_, ts) in results.items() if now - ts > RESULT_EXPIRY]
    for number in to_delete:
        del results[number]


def cleanup_pending():
    now = datetime.now()
    with lock:
        temp_list = list(pending_queue.queue)
        pending_queue.queue.clear()
        for number, ts in temp_list:
            if now - ts < PENDING_EXPIRY:
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

        final_url = driver.current_url

        with lock:
            results[number] = (final_url, datetime.now())
            completed_timestamps[number] = datetime.now()

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
    cleanup_pending()
    if not pending_queue.empty():
        next_number, _ = pending_queue.get()
        threading.Thread(target=run_browser, args=(next_number,)).start()


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Insufficient or invalid number"}), 400

    cleanup_results()

    with lock:
        if number in results:
            url, timestamp = results[number]
            if datetime.now() - timestamp <= RESULT_EXPIRY:
                return jsonify({"status": "Already completed", "url": url})
            else:
                del results[number]

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            else:
                queue_contents = list(pending_queue.queue)
                if len(queue_contents) >= PENDING_LIMIT:
                    return jsonify({"status": "Pending list full", "pending_count": len(queue_contents)})
                if number not in [n for n, _ in queue_contents]:
                    pending_queue.put((number, datetime.now()))
                return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    with lock:
        cleanup_results()
        return jsonify({
            "is_running": is_running,
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": results.get(current_number, (None,))[0] if current_number in results else None,
            "completed_timestamps": {n: ts.strftime('%Y-%m-%d %H:%M:%S') for n, ts in completed_timestamps.items()}
        })


@app.route("/results")
def get_results():
    number = request.args.get("number")
    if not number or not number.isdigit():
        return jsonify({"error": "Invalid number"}), 400

    with lock:
        if number in results:
            url, timestamp = results[number]
            return jsonify({"status": "Found", "url": url})
        else:
            return jsonify({"status": "Result not found"})


@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        new_list = [(n, ts) for n, ts in q_list if n != number]
        pending_queue.queue.clear()
        for item in new_list:
            pending_queue.put(item)
        return jsonify({"status": f"{number} removed from pending queue"})


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_number_count": pending_queue.qsize(),
            "total_stored_results": len(results)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
