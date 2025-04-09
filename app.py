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
results = {}
completed_timestamps = {}
lock = threading.Lock()

MAX_PENDING = 2
RESULT_EXPIRY_MINUTES = 20
PENDING_EXPIRY_MINUTES = 6


def clean_expired():
    now = datetime.now()
    # Clean completed results
    expired_keys = [num for num, ts in completed_timestamps.items()
                    if now - ts > timedelta(minutes=RESULT_EXPIRY_MINUTES)]
    for key in expired_keys:
        results.pop(key, None)
        completed_timestamps.pop(key, None)

    # Clean pending queue
    q_list = list(pending_queue.queue)
    cleaned_list = [(num, ts) for num, ts in q_list if now - ts <= timedelta(minutes=PENDING_EXPIRY_MINUTES)]
    if len(q_list) != len(cleaned_list):
        with lock:
            pending_queue.queue.clear()
            for item in cleaned_list:
                pending_queue.put(item)


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

        driver.find_element(By.TAG_NAME, "input").send_keys(number)
        driver.find_element(By.ID, "terms").click()

        time.sleep(3)
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(1)

        driver.find_element(By.ID, "submit").click()
        time.sleep(4)

        driver.find_element(By.ID, "verify_button").click()
        final_url = driver.current_url

        with lock:
            results[number] = final_url
            completed_timestamps[number] = datetime.now()

        time.sleep(5)  # Let CPU cool down

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            if (number, datetime.now()) not in list(pending_queue.queue):
                pending_queue.put((number, datetime.now()))
    finally:
        driver.quit()
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    if not pending_queue.empty():
        next_number, _ = pending_queue.get()
        threading.Thread(target=run_browser, args=(next_number,)).start()


@app.route("/start")
def start():
    global is_running, current_number
    clean_expired()
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Only 10-digit number allowed"}), 400

    with lock:
        if number in results:
            return jsonify({"status": "Already completed", "url": results[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})

            pending_numbers = [n for n, _ in list(pending_queue.queue)]
            if number not in pending_numbers:
                if pending_queue.qsize() >= MAX_PENDING:
                    return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
                pending_queue.put((number, datetime.now()))
            return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    clean_expired()
    with lock:
        return jsonify({
            "is_running": is_running,
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "completed_timestamps": {k: v.strftime('%Y-%m-%d %H:%M:%S') for k, v in completed_timestamps.items()},
            "last_result_url": results.get(current_number)
        })


@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        q_list = [(n, t) for n, t in q_list if n != number]
        pending_queue.queue.clear()
        for item in q_list:
            pending_queue.put(item)
        return jsonify({"status": f"{number} removed from pending queue"})


@app.route("/results")
def get_result():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if number in results:
            return jsonify({"number": number, "url": results[number],
                            "timestamp": completed_timestamps[number].strftime('%Y-%m-%d %H:%M:%S')})
        else:
            return jsonify({"status": "Not found"})


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "total_results": len(results)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
