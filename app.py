from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import psutil
from collections import deque

app = Flask(__name__)

# Configuration
CPU_LIMIT = 70.0
MEM_LIMIT_MB = 500
MAX_SESSIONS = 1
SESSION_DURATION = 85  # Total session time in seconds
RESULT_CACHE_LIMIT = 1000

# State
active_sessions = 0
lock = threading.Lock()
in_progress = {}  # number -> (start_time)
results_cache = deque()  # stores (number, url)
number_to_result = {}  # number -> url
pending_queue = deque()


def system_ok():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().available / (1024 * 1024)
    with lock:
        return cpu < CPU_LIMIT and mem > MEM_LIMIT_MB and active_sessions < MAX_SESSIONS


def trim_cache():
    while len(results_cache) > RESULT_CACHE_LIMIT:
        old_number, _ = results_cache.popleft()
        number_to_result.pop(old_number, None)


def process_pending():
    with lock:
        if pending_queue and system_ok():
            next_number = pending_queue.popleft()
            threading.Thread(target=run_browser, args=(next_number,)).start()


def run_browser(number):
    global active_sessions

    with lock:
        active_sessions += 1
        in_progress[number] = time.time()

    try:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
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
        final_url = driver.current_url

        with lock:
            results_cache.append((number, final_url))
            number_to_result[number] = final_url
            trim_cache()

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        with lock:
            active_sessions -= 1
            in_progress.pop(number, None)
        process_pending()


@app.route("/start")
def start():
    number = request.args.get("number")

    if not number:
        return jsonify({"error": "number is required"}), 400

    with lock:
        # Check if it's already processing
        if number in in_progress:
            elapsed = time.time() - in_progress[number]
            remaining = max(0, SESSION_DURATION - int(elapsed))
            return jsonify({
                "status": "Already running",
                "number": number,
                "remaining_time": remaining,
                "final_url": number_to_result.get(number)
            })

        # Return final_url if available
        if number in number_to_result:
            return jsonify({
                "status": "Already processed",
                "final_url": number_to_result[number]
            })

        # If busy, queue it
        if not system_ok():
            pending_queue.append(number)
            return jsonify({
                "status": "Pending",
                "position_in_queue": len(pending_queue)
            })

        # Start fresh session
        threading.Thread(target=run_browser, args=(number,)).start()
        return jsonify({"status": "Started", "number": number})


@app.route("/status")
def status():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory().available / (1024 * 1024)
    with lock:
        running_numbers = {
            num: max(0, SESSION_DURATION - int(time.time() - start))
            for num, start in in_progress.items()
        }

    return jsonify({
        "cpu_percent": cpu,
        "available_memory_mb": round(mem, 2),
        "active_sessions": active_sessions,
        "running_numbers": running_numbers,
        "pending_queue_length": len(pending_queue),
        "cache_size": len(results_cache)
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
