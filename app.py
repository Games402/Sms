from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import json
import os
from collections import OrderedDict

app = Flask(__name__)

# Globals
is_running = False
pending_queue = []
results_file = "results.json"
MAX_RESULTS = 1000

# Load results from file
if os.path.exists(results_file):
    with open(results_file, "r") as f:
        saved_results = json.load(f)
    saved_results = OrderedDict(saved_results)
else:
    saved_results = OrderedDict()

lock = threading.Lock()

def save_results():
    while len(saved_results) > MAX_RESULTS:
        saved_results.popitem(last=False)
    with open(results_file, "w") as f:
        json.dump(saved_results, f)

def run_browser(number):
    global is_running
    with lock:
        is_running = True

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
        time.sleep(35)

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(3)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(3)

        driver.find_element(By.ID, "submit").click()
        time.sleep(35)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(5)

        final_url = driver.current_url

        with lock:
            saved_results[number] = final_url
            saved_results.move_to_end(number)
            save_results()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        with lock:
            is_running = False
            if pending_queue:
                next_number = pending_queue.pop(0)
                print(f"👉 Processing pending number: {next_number}")
                threading.Thread(target=run_browser, args=(next_number,)).start()

@app.route("/start")
def start():
    global is_running
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        if number in saved_results:
            return jsonify({"status": "Already done", "url": saved_results[number]}), 200

        if is_running:
            if number not in pending_queue:
                pending_queue.append(number)
            return jsonify({"status": "Queued", "pending": len(pending_queue)}), 202

        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})

@app.route("/status")
def status():
    with lock:
        return jsonify({
            "is_running": is_running,
            "pending": len(pending_queue),
            "completed": len(saved_results)
        })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
