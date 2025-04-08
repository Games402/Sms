from flask import Flask, request, jsonify
import threading
import time
import psutil
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

app = Flask(__name__)

active_sessions = 0
lock = threading.Lock()

CPU_LIMIT = 70.0
MEM_LIMIT_MB = 500

def system_ok():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().available / (1024 * 1024)
    with lock:
        return cpu < CPU_LIMIT and mem > MEM_LIMIT_MB and active_sessions < 2

def run_bot(number):
    global active_sessions
    with lock:
        active_sessions += 1
    try:
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        driver = webdriver.Chrome(options=options)

        # 🔽 Your automation script here
        driver.get("https://www.thecallbomber.in")
        # Example:
        # input_box = driver.find_element(By.ID, "mobileNumber")
        # input_box.send_keys(number)
        time.sleep(600)  # simulate 10 min wait on last page

        driver.quit()
    except Exception as e:
        print("Error:", e)
    finally:
        with lock:
            active_sessions -= 1

@app.route('/start')
def start():
    number = request.args.get('number')
    if not number:
        return jsonify({'error': 'Missing number'}), 400

    if not system_ok():
        return jsonify({'error': 'System busy, try again later'}), 429

    thread = threading.Thread(target=run_bot, args=(number,))
    thread.start()
    return jsonify({'status': 'Started', 'number': number})

@app.route('/status')
def status():
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().available / (1024 * 1024)
    return jsonify({
        'cpu_percent': cpu,
        'available_memory_mb': round(mem, 2),
        'active_sessions': active_sessions
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
