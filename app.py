from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import concurrent.futures
import threading
import time
import psutil
from collections import deque

app = Flask(__name__)
executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

# Configuration
CPU_LIMIT = 70.0
MEM_LIMIT_MB = 400
COOLDOWN_SECONDS = 85
MAX_CACHE = 1000

# In-memory cache and pending queue
results = {}
pending = deque()
lock = threading.Lock()

def system_ok():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().available / (1024 * 1024)
    with lock:
        return cpu < CPU_LIMIT and mem > MEM_LIMIT_MB and len(executor._threads) < executor._max_workers

def cleanup_results():
    while len(results) > MAX_CACHE:
        results.pop(next(iter(results)))

def run_browser(number):
    start_time = time.time()

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

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
        time.sleep(3)

        final_url = driver.current_url
    except Exception as e:
        final_url = f"Error: {e}"
    finally:
        driver.quit()
        with lock:
            results[number] = (time.time(), final_url)
            cleanup_results()
        run_pending()

def run_pending():
    with lock:
        while pending and system_ok():
            number = pending.popleft()
            executor.submit(run_browser, number)

@app.route("/start")
def start():
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "Missing number"}), 400

    with lock:
        if number in results:
            start_time, url = results[number]
            elapsed = time.time() - start_time
            if elapsed < COOLDOWN_SECONDS:
                return jsonify({
                    "status": "Already running",
                    "final_url": url,
                    "time_remaining": round(COOLDOWN_SECONDS - elapsed, 2)
                })

        if system_ok():
            executor.submit(run_browser, number)
            return jsonify({"status": "Started", "number": number})
        else:
            pending.append(number)
            return jsonify({"status": "Queued", "number": number, "position": len(pending)})

@app.route("/status")
def status():
    with lock:
        cpu = psutil.cpu_percent(interval=1)
        mem = psutil.virtual_memory().available / (1024 * 1024)
        active = len(executor._threads)
        recent_results = {k: round(COOLDOWN_SECONDS - (time.time() - v[0]), 2)
                          for k, v in results.items()
                          if time.time() - v[0] < COOLDOWN_SECONDS}

    return jsonify({
        "cpu_percent": cpu,
        "available_memory_mb": round(mem, 2),
        "active_sessions": active,
        "pending_queue": len(pending),
        "cooldown_remaining": recent_results
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
