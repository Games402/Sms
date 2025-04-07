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
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.binary_location = "/usr/bin/chromium"
    return webdriver.Chrome(executable_path="/usr/bin/chromedriver", options=chrome_options)

@app.route('/start')
def start_automation():
    phone_number = request.args.get('number')
    if not phone_number:
        return jsonify({"error": "Missing phone number"}), 400

    url = "https://your-target-website.com"  # Replace this with the actual site

    browser = setup_browser()
    wait = WebDriverWait(browser, 20)

    try:
        browser.get(url)
        print("🌐 Website opened.")

        # Step 1: Enter number
        number_box = wait.until(EC.presence_of_element_located((By.ID, "mobileNumber")))
        number_box.send_keys(phone_number)
        print("📱 Phone number entered.")

        # Step 2: Click checkbox
        checkbox = wait.until(EC.element_to_be_clickable((By.ID, "terms")))
        checkbox.click()
        print("✅ Checkbox clicked.")

        # Step 3: Wait 40s
        print("⏳ Waiting 40 seconds...")
        time.sleep(40)

        # Step 4: Scroll simulation
        browser.execute_script("window.scrollBy(0, 1000);")
        time.sleep(10)
        browser.execute_script("window.scrollBy(0, -200);")
        time.sleep(20)
        browser.execute_script("window.scrollBy(0, 300);")
        time.sleep(10)
        print("🖱️ Scrolling done.")

        # Step 5: Click submit
        submit_btn = wait.until(EC.element_to_be_clickable((By.ID, "submit")))
        submit_btn.click()
        print("🚀 Submit clicked.")

        # Step 6: Wait 45s on next page
        print("⏳ Waiting 45 seconds for verify button...")
        time.sleep(45)

        verify_btn = wait.until(EC.element_to_be_clickable((By.ID, "verify_button")))
        verify_btn.click()
        print("✅ Verify button clicked.")

        # Step 7: Final 90s wait
        print("⏳ Waiting final 90 seconds...")
        time.sleep(90)

        print("🎉 Automation completed successfully.")
        return jsonify({"status": "success", "message": "Automation complete!"})

    except Exception as e:
        print("❌ Error:", e)
        return jsonify({"status": "error", "message": str(e)})

    finally:
        browser.quit()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
