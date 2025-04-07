from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import chromedriver_autoinstaller
import threading
import time

app = Flask(__name__)
is_running = False

def setup_browser():
    # Automatically install correct chromedriver
    chromedriver_autoinstaller.install()

    options = Options()
    options.add_argument("--headless=new")  # Use modern headless mode
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    return webdriver.Chrome(options=options)

def automate_browser(number):
    global is_running
    is_running = True
    browser = setup_browser()
    wait = WebDriverWait(browser, 20)

    try:
        browser.get("https://www.thecallbomber.in")  # Replace with actual URL

        # Enter number into the only textbox
        input_box = wait.until(EC.presence_of_element_located((By.TAG_NAME, "input")))
        input_box.send_keys(number)

        # Click checkbox
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "terms")))
        checkbox.click()

        time.sleep(40)

        # Scroll simulation
        browser.execute_script("window.scrollBy(0, 1000);")
        time.sleep(10)
        browser.execute_script("window.scrollBy(0, -500);")
        time.sleep(20)
        browser.execute_script("window.scrollBy(0, 100);")
        time.sleep(10)

        # Click submit button
        submit_btn = wait.until(EC.element_to_be_clickable((By.ID, "submit")))
        submit_btn.click()

        time.sleep(45)

        # Click verify button
        verify_btn = wait.until(EC.element_to_be_clickable((By.ID, "verify_button")))
        verify_btn.click()

        time.sleep(90)

    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        browser.quit()
        is_running = False

@app.route("/start")
def start():
    global is_running
    number = request.args.get("number")
    if not number:
        return jsonify({"error": "Missing number param"}), 400

    if is_running:
        return jsonify({"status": "busy"}), 429

    threading.Thread(target=automate_browser, args=(number,)).start()
    return jsonify({"status": "started", "number": number})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    
