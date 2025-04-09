from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
from queue import Queue
import re

app = Flask(__name__)

is_running = False
current_number = None
pending_queue = Queue()
latest_result = {}
completed_timestamps = {}
failed_numbers = set()
lock = threading.Lock()

MAX_PENDING = 2
RESULT_EXPIRY_SECONDS = 1200  # 20 minutes

LAST_PAGE_URL = None

def clean_old_results():
    with lock:
        now = time.time()
        to_delete = [num for num, val in latest_result.items()
                     if now - val["timestamp"] > RESULT_EXPIRY_SECONDS]
        for num in to_delete:
            del latest_result[num]
            if num in completed_timestamps:
                del completed_timestamps[num]

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

        # Scroll interactions (reduced time)
        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(2)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(2)

        driver.find_element(By.ID, "submit").click()
        time.sleep(5)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(1)  # ensure page loads

        final_url = driver.current_url

        with lock:
            LAST_PAGE_URL = final_url
            latest_result[number] = {
                "url": final_url,
                "timestamp": time.time()
            }
            completed_timestamps[number] = time.time()

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
        if not pending_queue.empty():
            next_number = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")
    
    if not number or not re.fullmatch(r"\d{10}", number):
        return jsonify({"error": "Insufficient or invalid number. Must be 10 digits."}), 400

    with lock:
        clean_old_results()

        if number in latest_result:
            return jsonify({"status": "Already processed", "url": latest_result[number]["url"]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            if number not in list(pending_queue.queue):
                if pending_queue.qsize() >= MAX_PENDING:
                    return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
                pending_queue.put(number)
                return jsonify({"status": "Machine busy, added to queue", "pending_count": pending_queue.qsize()})
            return jsonify({"status": "Already in queue", "pending_count": pending_queue.qsize()})

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
            "completed_timestamps": completed_timestamps
        })

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

@app.route("/results")
def get_results():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if number in latest_result:
            return jsonify({
                "number": number,
                "url": latest_result[number]["url"],
                "timestamp": latest_result[number]["timestamp"]
            })
        return jsonify({"status": "No result found for this number"}), 404

@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "total_stored_numbers": len(latest_result)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
