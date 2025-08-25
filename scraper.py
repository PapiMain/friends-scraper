import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def get_short_names():
    service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
    client = gspread.authorize(creds)
    

    sheet = client.open("דאטה אפשיט אופיס").worksheet("הפקות")
    data = sheet.get_all_records()

    return [row["שם מקוצר"] for row in data if row["שם מקוצר"]]

def get_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # run without UI
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=chrome_options
    )
    return driver

def search_show(driver, show_name):
    driver.get("https://friends-hist.co.il/")
    time.sleep(2)  # wait for page to load

    # Find the search input
    search_box = driver.find_element(By.CSS_SELECTOR, "input.wcjapsSearchKeyword")
    
    search_box.clear()
    search_box.send_keys(show_name)
    search_box.send_keys(Keys.RETURN)  # press Enter

    time.sleep(3)  # wait for results to load
    print(f"🔎 Searched for: {show_name}")

    # Get all show links in the results
    show_links = []
    wrap_shows_divs = driver.find_elements(By.CSS_SELECTOR, "div.wrap_shows")
    for div in wrap_shows_divs:
        try:
            a_tags = div.find_elements(By.CSS_SELECTOR, "a.btn_info")  # all links now
            for a_tag in a_tags:
                href = a_tag.get_attribute("href")
                if href:
                    show_links.append(href)
        except:
            pass  # in case a div doesn't have btn_info links

    print(f"📄 Found {len(show_links)} show links")
    return show_links


def scrape_show_events(driver, show_url):
    driver.get(show_url)
    time.sleep(2)  # let page load

    events_data = []

    # get show title
    title = driver.find_element(By.CSS_SELECTOR, "h1").text

    # find all event rows
    event_rows = driver.find_elements(By.CSS_SELECTOR, "div.events_list > div.event_row")

    for row in event_rows:
        try:
            # get city
            city = row.find_element(By.CSS_SELECTOR, ".date_time_address .time_wrap span").text

            # get hall
            hall = row.find_element(By.CSS_SELECTOR, ".date_time_address .address_wrap.desktop_only span").text

            # get date and time
            date = row.find_element(By.CSS_SELECTOR, ".date-time-sec .date_wrap span").text
            time_ = row.find_element(By.CSS_SELECTOR, ".date-time-sec .time_wrap span").text

            # get event_id for pop-up
            event_id = row.find_element(By.CSS_SELECTOR, "a.load_event_iframe").get_attribute("data-event_id")
            empty_seats = get_empty_seats(driver, event_id)

            events_data.append({
                "title": title,
                "city": city,
                "hall": hall,
                "date": date,
                "time": time_,
                "event_id": event_id,
                "empty_seats": empty_seats,
            })

        except Exception as e:
            print(f"⚠️ Could not scrape event: {e}")
            continue

    return events_data

def get_empty_seats(driver, event_id):
    # Wait until the button is clickable
    btn = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, f"a.load_event_iframe[data-event_id='{event_id}']"))
    )
    print(f"Found button for event {event_id}: displayed={btn.is_displayed()}, enabled={btn.is_enabled()}")

    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
    
    # Click the button (use JS click to avoid interception issues)
    driver.execute_script("arguments[0].click();", btn)

    # Wait until popup content appears
    popup = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, f"pop_content_{event_id}"))
    )
    print(f"Popup found for event {event_id}: displayed={popup.is_displayed()}")

    # Wait for iframe inside popup
    # iframe = WebDriverWait(popup, 10).until(
    #     EC.presence_of_element_located((By.TAG_NAME, "iframe"))
    # )

    # Find all iframes inside popup
    iframes = popup.find_elements(By.TAG_NAME, "iframe")
    print(f"Number of iframes in popup {event_id}: {len(iframes)}")
    for i, frame in enumerate(iframes):
        print(f"iframe {i} id={frame.get_attribute('id')} src={frame.get_attribute('src')}")

    # Switch to iframe to access seats
    driver.switch_to.frame(iframes[0])  # or find by ids
    # OR more safely:
    # driver.switch_to.frame(popup.find_element(By.ID, "smarticket"))


    # Count empty seats inside iframe
    empty_seats = driver.find_elements(By.CSS_SELECTOR, "a.chair.empty[data-status='empty']")
    print(f"Empty seats found for event {event_id}: {len(empty_seats)}")
    empty_count = len(empty_seats)
    # Switch back to main content
    driver.switch_to.default_content()

    return empty_count


if __name__ == "__main__":
    from scraper import get_short_names, get_driver, search_show, scrape_show_events

    short_names = get_short_names()
    driver = get_driver()

    all_events = []

    for name in short_names:  
        # 1️⃣ Search the show and get all links
        show_links = search_show(driver, name)
        print(f"Found {len(show_links)} links for '{name}'")

        # 2️⃣ Go through each show link and scrape events
        for link in show_links[:1]:  # limit to first link for testing
            events = scrape_show_events(driver, link)
            all_events.extend(events)
            print(f"Scraped {len(events)} events from {link}")

    driver.quit()

    # 3️⃣ Print all scraped events (or store in DB/Sheet)
    for e in all_events:
        print(e)
