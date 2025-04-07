from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import threading

app = Flask(__name__)

# Avoid running multiple instances at once
is_running = False
from selenium.webdriver.chrome.service import Service

def setup_browser():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.binary_location = "/usr/bin/chromium"  # Optional, only if needed

    service = Service("/usr/bin/chromedriver")
    return webdriver.Chrome(service=service, options=chrome_options)
    

def automate_browser(number):
    global is_running
    is_running = True
    browser = setup_browser()
    wait = WebDriverWait(browser, 20)

    try:
        browser.get("https://www.thecallbomber.in/")  # Replace with your real site
        print("🌐 Opened site")

        input_box = wait.until(EC.presence_of_element_located((By.TAG_NAME, "input")))
        input_box.send_keys(number)
        print("📱 Number entered")

        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "terms")))
        checkbox.click()

        time.sleep(40)
        browser.execute_script("window.scrollBy(0, 1000);")
        time.sleep(10)
        browser.execute_script("window.scrollBy(0, -500);")
        time.sleep(20)
        browser.execute_script("window.scrollBy(0, 100);")
        time.sleep(10)

        submit_btn = wait.until(EC.element_to_be_clickable((By.ID, "submit")))
        submit_btn.click()

        time.sleep(45)

        verify_btn = wait.until(EC.element_to_be_clickable((By.ID, "verify_button")))
        verify_btn.click()

        time.sleep(90)
        print("✅ Automation completed")

    except Exception as e:
        print("❌ Error during automation:", str(e))

    finally:
        browser.quit()
        is_running = False

@app.route('/start')
def start():
    global is_running
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "Missing phone number"}), 400

    if is_running:
        return jsonify({"status": "busy", "message": "Machine is already running"}), 429

    thread = threading.Thread(target=automate_browser, args=(number,))
    thread.start()

    return jsonify({"status": "started", "number": number})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
