from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time

app = Flask(__name__)

def setup_browser():
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.binary_location = "/usr/bin/chromium"  # Required for Render
    return webdriver.Chrome(executable_path="/usr/bin/chromedriver", options=chrome_options)

@app.route('/start')
def automate():
    number = request.args.get('number')
    if not number:
        return jsonify({"error": "Missing number parameter"}), 400

    browser = setup_browser()
    wait = WebDriverWait(browser, 20)

    try:
        browser.get("https://www.thecallbomber.in/")  # Replace with actual target site
        print("🔗 Opened website")

        # Only one input field (phone number)
        input_box = wait.until(EC.presence_of_element_located((By.TAG_NAME, "input")))
        input_box.send_keys(number)
        print("📱 Entered phone number")

        # Checkbox
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "terms")))
        checkbox.click()
        print("✅ Checkbox clicked")

        print("⏳ Waiting 40 seconds before scroll...")
        time.sleep(40)

        # Scroll actions
        browser.execute_script("window.scrollBy(0, 1000);")
        time.sleep(10)
        browser.execute_script("window.scrollBy(0, -500);")
        time.sleep(20)
        browser.execute_script("window.scrollBy(0, 100);")
        time.sleep(10)
        print("🖱️ Scrolled")

        # Click Submit
        submit = wait.until(EC.element_to_be_clickable((By.ID, "submit")))
        submit.click()
        print("🚀 Submit clicked")

        # Wait for 45s on next page
        time.sleep(45)

        verify_button = wait.until(EC.element_to_be_clickable((By.ID, "verify_button")))
        verify_button.click()
        print("✅ Verify button clicked")

        # Wait 90s for final page
        time.sleep(90)
        print("🎉 Finished automation")

        return jsonify({"status": "success", "message": "Automation complete!"})

    except Exception as e:
        print("❌ Error:", str(e))
        return jsonify({"status": "error", "message": str(e)}), 500

    finally:
        browser.quit()

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
