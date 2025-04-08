from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from concurrent.futures import ThreadPoolExecutor
import threading
import time
import psutil
from collections import OrderedDict
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Config
MAX_CACHE = 1000
COOLDOWN_TIME = 85  # seconds
CPU_LIMIT = 75.0
MEM_LIMIT_MB = 400
MAX_SESSIONS = 2

# State
lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=MAX_SESSIONS)
active_sessions = 0
pending_queue = []
in_progress = {}  # number: (start_time, duration)
results = OrderedDict()  # number: final_url

def system_ok():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().available / (1024 * 1024)
    return cpu < CPU_LIMIT and mem > MEM_LIMIT_MB

def cleanup_cache():
    while len(results) > MAX_CACHE:
        results.popitem(last=False)

def run_browser(number):
    global active_sessions
    with lock:
        active_sessions += 1
        in_progress[number] = (time.time(), COOLDOWN_TIME)

    try:
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
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
            results[number] = final_url
            cleanup_cache()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        with lock:
            active_sessions -= 1
            in_progress.pop(number, None)
        check_pending()

def check_pending():
    with lock:
        if pending_queue and active_sessions < MAX_SESSIONS and system_ok():
            next_number = pending_queue.pop(0)
            executor.submit(run_browser, next_number)

@app.route("/start")
def start():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "Missing number"}), 400

    with lock:
        if number in in_progress:
            start_time, total_time = in_progress[number]
            remaining = max(0, int(start_time + total_time - time.time()))
            return jsonify({"status": "Already running", "remaining": remaining}), 202

        if number in results:
            return jsonify({"status": "Completed", "url": results[number]}), 200

        if active_sessions >= MAX_SESSIONS or not system_ok():
            if number not in pending_queue:
                pending_queue.append(number)
            return jsonify({"status": "Queued"}), 202

        executor.submit(run_browser, number)
        return jsonify({"status": "Started", "number": number}), 200

@app.route("/status")
def status():
    cpu = psutil.cpu_percent(interval=1)
    mem = round(psutil.virtual_memory().available / (1024 * 1024), 2)
    with lock:
        active = active_sessions
        pending = len(pending_queue)
        timers = {}
        now = time.time()
        for number, (start_time, total_time) in in_progress.items():
            remaining = max(0, int(start_time + total_time - now))
            timers[number] = remaining

    return jsonify({
        "cpu_percent": cpu,
        "available_memory_mb": mem,
        "active_sessions": active,
        "pending_queue_length": pending,
        "in_progress": timers
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
