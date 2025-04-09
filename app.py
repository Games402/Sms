from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from queue import Queue
from datetime import datetime, timedelta
import re

app = Flask(__name__)

is_running = False
current_number = None
pending_queue = Queue()
completed_results = {}  # number: {url, timestamp}
failed_numbers = set()
lock = threading.Lock()

MAX_PENDING = 2
RESULT_EXPIRY_MINUTES = 20
PENDING_EXPIRY_MINUTES = 6


def cleanup():
    now = datetime.now()
    # Clean completed results older than 20 minutes
    to_delete = [num for num, data in completed_results.items()
                 if now - data['timestamp'] > timedelta(minutes=RESULT_EXPIRY_MINUTES)]
    for num in to_delete:
        del completed_results[num]

    # Clean pending queue numbers older than 6 minutes
    q_list = list(pending_queue.queue)
    new_q = []
    for item in q_list:
        if now - item['timestamp'] < timedelta(minutes=PENDING_EXPIRY_MINUTES):
            new_q.append(item)
    with lock:
        pending_queue.queue.clear()
        for item in new_q:
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

        input_box = driver.find_element(By.TAG_NAME, "input")
        input_box.send_keys(number)

        driver.find_element(By.ID, "terms").click()
        time.sleep(2)

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(1)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(1)

        driver.find_element(By.ID, "submit").click()
        time.sleep(3)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(2)

        last_url = driver.current_url

        with lock:
            completed_results[number] = {
                'url': last_url,
                'timestamp': datetime.now()
            }

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            failed_numbers.add(number)
    finally:
        driver.quit()
        time.sleep(5)  # CPU stabilization
        with lock:
            is_running = False
            current_number = None
        process_pending()


def process_pending():
    if not pending_queue.empty():
        item = pending_queue.get()
        threading.Thread(target=run_browser, args=(item['number'],)).start()


@app.route("/start")
def start():
    cleanup()
    number = request.args.get("number")

    if not number or not re.fullmatch(r"\d{10}", number):
        return jsonify({"error": "Only valid 10-digit number allowed"}), 400

    with lock:
        # Already processed
        if number in completed_results:
            return jsonify({
                "status": "Already processed",
                "url": completed_results[number]['url']
            })

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            else:
                if any(item['number'] == number for item in pending_queue.queue):
                    return jsonify({"status": "Already in pending queue", "pending_count": pending_queue.qsize()})
                if pending_queue.qsize() < MAX_PENDING:
                    pending_queue.put({"number": number, "timestamp": datetime.now()})
                    return jsonify({"status": "Added to pending queue", "pending_count": pending_queue.qsize()})
                else:
                    return jsonify({"status": "Pending list full, try later"}), 429

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/results")
def results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if number in completed_results:
            return jsonify({"number": number, "url": completed_results[number]['url']})
        return jsonify({"status": "Not found or expired"}), 404


@app.route("/status")
def status():
    with lock:
        recent = list(completed_results.items())[-5:]
        return jsonify({
            "status": "Running" if is_running else "Available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "recent_completions": [
                {"number": n, "url": d['url'], "completed_at": d['timestamp'].isoformat()} for n, d in recent
            ]
        })


@app.route("/cancel")
def cancel():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        q_list = list(pending_queue.queue)
        if any(item['number'] == number for item in q_list):
            new_q = [item for item in q_list if item['number'] != number]
            pending_queue.queue.clear()
            for item in new_q:
                pending_queue.put(item)
            return jsonify({"status": f"{number} removed from pending queue"})
        else:
            return jsonify({"status": f"{number} not in pending queue"})


@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "stored_results": len(completed_results)
        })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
