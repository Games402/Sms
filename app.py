from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading
import time
from queue import Queue
from datetime import datetime, timedelta

app = Flask(__name__)

is_running = False
current_number = None
pending_queue = Queue(maxsize=2)
latest_result = {}  # Stores number -> {url, timestamp}
failed_numbers = set()
lock = threading.Lock()

RESULT_EXPIRY = timedelta(minutes=20)
PENDING_EXPIRY = timedelta(minutes=6)

completed_timestamps = {}  # number -> timestamp


def cleanup_old_results():
    now = datetime.utcnow()
    to_delete = [num for num, data in latest_result.items() if now - data['timestamp'] > RESULT_EXPIRY]
    for num in to_delete:
        del latest_result[num]
        if num in completed_timestamps:
            del completed_timestamps[num]


def cleanup_pending():
    now = datetime.utcnow()
    temp_queue = Queue(maxsize=2)
    while not pending_queue.empty():
        number, added_time = pending_queue.get()
        if now - added_time < PENDING_EXPIRY:
            temp_queue.put((number, added_time))
    while not temp_queue.empty():
        pending_queue.put(temp_queue.get())


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
    success = False
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(30)
        driver.get("https://www.thecallbomber.in")

        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "input"))).send_keys(number)
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "terms"))).click()

        driver.execute_script("window.scrollBy(0, 500);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, -200);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(1)

        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "submit"))).click()
        WebDriverWait(driver, 15).until(EC.element_to_be_clickable((By.ID, "verify_button"))).click()

        final_url = driver.current_url
        with lock:
            latest_result[number] = {
                "url": final_url,
                "timestamp": datetime.utcnow()
            }
            completed_timestamps[number] = datetime.utcnow()
            success = True

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            failed_numbers.add(number)
    finally:
        if driver:
            driver.quit()
        time.sleep(5)  # CPU cooldown
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    cleanup_old_results()
    cleanup_pending()
    with lock:
        if not pending_queue.empty():
            next_number, _ = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()


@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Invalid number. Only 10-digit numbers allowed."}), 400

    with lock:
        cleanup_old_results()

        if number in latest_result:
            return jsonify({"status": "Already processed", "url": latest_result[number]['url']})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif any(number == n for n, _ in pending_queue.queue):
                return jsonify({"status": "Already in pending queue", "pending_count": pending_queue.qsize()})
            elif pending_queue.full():
                return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()}), 429
            else:
                pending_queue.put((number, datetime.utcnow()))
                return jsonify({"status": "Added to pending list", "pending_count": pending_queue.qsize()})
        else:
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
            "last_result_url": latest_result.get(current_number, {}).get("url"),
            "completed_timestamps": {k: v.isoformat() for k, v in completed_timestamps.items()}
        })


@app.route("/results")
def results():
    number = request.args.get("number")
    with lock:
        result = latest_result.get(number)
        if result:
            return jsonify({"number": number, "url": result['url'], "timestamp": result['timestamp'].isoformat()})
        return jsonify({"status": "Result not found"}), 404


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


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "total_stored_results": len(latest_result)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
