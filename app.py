from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time

app = Flask(__name__)
is_running = False

def run_browser(number):
    global is_running
    is_running = True

    # Setup lightweight browser options
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    try:
        driver = webdriver.Chrome(options=options)
        driver.get("https://www.thecallbomber.in")  # Replace with actual site

        # Interact with first page
        input_box = driver.find_element(By.TAG_NAME, "input")
        input_box.send_keys(number)

        driver.find_element(By.ID, "terms").click()
        time.sleep(40)

        driver.execute_script("window.scrollBy(0, 1000);")
        time.sleep(10)
        driver.execute_script("window.scrollBy(0, -500);")
        time.sleep(20)
        driver.execute_script("window.scrollBy(0, 100);")
        time.sleep(10)

        driver.find_element(By.ID, "submit").click()
        time.sleep(45)

        driver.find_element(By.ID, "verify_button").click()
        time.sleep(90)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        driver.quit()
        is_running = False

@app.route("/start")
def start():
    global is_running
    number = request.args.get("number")

    if not number:
        return jsonify({"error": "number is required"}), 400

    if is_running:
        return jsonify({"status": "Machine busy"}), 429

    threading.Thread(target=run_browser, args=(number,)).start()
    return jsonify({"status": "Started", "number": number})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
