from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import json
import os
from queue import Queue

app = Flask(__name__)

DATA_FILE = "results.json"
PENDING_LIMIT = 2
is_running = False
current_number = None
pending_queue = Queue()
lock = threading.Lock()

# Load existing data
def load_results():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

# Save results to file
def save_results(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)

results_data = load_results()

def run_browser(number):
    global is_running, current_number, results_data
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
        time.sleep(2)

        final_url = driver.current_url

        # Store URL externally
        with lock:
            results_data[number] = final_url
            save_results(results_data)

    except Exception as e:
        print(f"❌ Error: {e}")
        with lock:
            if number not in list(pending_queue.queue):
                pending_queue.put(number)
    finally:
        driver.quit()
        time.sleep(3)
        with lock:
            is_running = False
            current_number = None
        process_pending()

def process_pending():
    with lock:
        if not pending_queue.empty():
            next_number = pending_queue.get()
            threading.Thread(target=run_browser, args=(next_number,)).start()

@app.route("/start")
def start():
    global is_running, current_number
    number = request.args.get("number")

    if not number or not number.isdigit() or len(number) != 10:
        return jsonify({"error": "Please provide a valid 10-digit mobile number."}), 400

    with lock:
        if number in results_data:
            return jsonify({"status": "Already completed", "url": results_data[number]})

        if is_running:
            if number == current_number:
                return jsonify({"status": "Processing"})
            elif pending_queue.qsize() >= PENDING_LIMIT:
                return jsonify({"status": "Pending list full", "pending_count": pending_queue.qsize()})
            elif number not in list(pending_queue.queue):
                pending_queue.put(number)
                return jsonify({
                    "status": "Machine busy, number added to pending list",
                    "pending_count": pending_queue.qsize()
                })
            else:
                return jsonify({"status": "Already in pending queue"})

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

@app.route("/status")
def status():
    with lock:
        return jsonify({
            "status": "active" if is_running else "available",
            "current_number": current_number,
            "pending_count": pending_queue.qsize(),
            "last_result_url": results_data.get(current_number)
        })

@app.route("/results")
def results():
    number = request.args.get("number")
    with lock:
        url = results_data.get(number)
        if url:
            return jsonify({"status": "Success", "url": url})
        return jsonify({"status": "Result not found"})

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

@app.route("/change_machine")
def change_machine():
    with lock:
        return jsonify({
            "pending_count": pending_queue.qsize(),
            "total_stored_numbers": len(results_data)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
