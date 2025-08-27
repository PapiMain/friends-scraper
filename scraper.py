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
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    NoSuchElementException,
)

def get_short_names():
    service_account_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT"])
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(service_account_info, scope)
    client = gspread.authorize(creds)
    

    sheet = client.open("דאטה אפשיט אופיס").worksheet("הפקות")
    short_names = sheet.col_values(2)  # for example, if "שם מקוצר" is column B
    return [name for name in short_names if name and name != "שם מקוצר"]

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

def _wait_dom_ready(driver, timeout=10):
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )

def _click_first_area_if_present(driver):
    try:
        # Wait briefly for area rows to render (if the hall uses area selection)
        WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "tr.area input.btn.btn-primary"))
        )
        areas = driver.find_elements(By.CSS_SELECTOR, "tr.area input.btn.btn-primary")
        print(f"{len(areas)} area buttons detected inside iframe")
        if areas:
            driver.execute_script("arguments[0].click();", areas[0])
            print("✅ Clicked first area button")
            time.sleep(1.5)  # let seats render after area click
            return True
    except TimeoutException:
        print("No area selection table (or not visible yet), continuing...")
    return False

def _wait_for_any_seats(driver, timeout=20):
    # Some halls render seats differently; wait for any seat anchor or obvious seat containers
    def _seats_or_container(d):
        if d.find_elements(By.CSS_SELECTOR, "a.chair"):
            return True
        if d.find_elements(By.CSS_SELECTOR, ".seatmap, #seatmap, [class*='seat-map'], [id*='seat-map']"):
            return True
        return False
    WebDriverWait(driver, timeout).until(_seats_or_container)

def _count_empty_seats(driver):
    # Try strict selector first, then a looser fallback
    empty = driver.find_elements(By.CSS_SELECTOR, "a.chair.empty[data-status='empty']")
    if not empty:
        empty = driver.find_elements(By.CSS_SELECTOR, "a.chair[data-status='empty'], a.chair.empty")
    return len(empty)

def get_empty_seats(driver, event_id):
    iframe_src = None  # keep for fallback

    # ---------- 1) Popup → iframe path ----------
    try:
        btn_locator = (By.CSS_SELECTOR, f"a.load_event_iframe[data-event_id='{event_id}']")
        btn = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(btn_locator))
        print(f"Found button for event {event_id}")
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        driver.execute_script("arguments[0].click();", btn)

        popup = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, f"pop_content_{event_id}"))
        )
        print(f"Popup found for event {event_id}")
        try:
            print("Popup HTML snippet (first 500 chars):")
            print(popup.get_attribute("innerHTML")[:500])
        except Exception:
            pass

        # Find iframes inside popup; pick the best candidate (last one with /iframe/event/)
        WebDriverWait(driver, 10).until(
            lambda d: len(popup.find_elements(By.CSS_SELECTOR, "iframe[src]")) > 0
        )
        iframes = popup.find_elements(By.CSS_SELECTOR, "iframe[src]")
        print(f"Found {len(iframes)} iframe(s) inside popup")
        candidates = [f for f in iframes if "/iframe/event/" in (f.get_attribute("src") or "")]
        iframe_el = (candidates or iframes)[-1]  # prefer event iframe, else just last

        iframe_src = iframe_el.get_attribute("src")
        print(f"iframe detected for event {event_id}: {iframe_src}")
        print(f"iframe element: id={iframe_el.get_attribute('id')}, src={iframe_src}")
        try:
            print("iframe HTML snippet (first 500 chars):")
            print(iframe_el.get_attribute("outerHTML")[:500])
        except Exception:
            pass

        # Switch using the element we just chose (avoid frame_to_be_available_and_switch_to_it confusion)
        driver.switch_to.frame(iframe_el)
        _wait_dom_ready(driver, 10)
        try:
            print("Inside iframe href:", driver.execute_script("return window.location.href"))
        except Exception:
            pass

        # If hall uses area selection, click first "אנא בחר"
        _click_first_area_if_present(driver)

        # Wait for seats (or seatmap container), then count empty
        _wait_for_any_seats(driver, timeout=20)
        count = _count_empty_seats(driver)
        print(f"✅ Found {count} empty seats via popup iframe for event {event_id}")
        try:
            print("Seatmap HTML snippet (first 500 chars):")
            print(driver.page_source[:500])
        except Exception:
            pass
        return count

    except Exception as e:
        print(f"⚠️ Popup iframe method failed for event {event_id}: {e}")
    finally:
        # always reset context
        try:
            driver.switch_to.default_content()
        except Exception:
            pass

    # ---------- 2) Direct iframe src fallback ----------
    if iframe_src:
        try:
            print(f"Trying direct iframe URL for event {event_id}")
            driver.get(iframe_src)
            _wait_dom_ready(driver, 10)

            _click_first_area_if_present(driver)
            _wait_for_any_seats(driver, timeout=20)
            count = _count_empty_seats(driver)
            print(f"✅ Found {count} empty seats via direct iframe src for event {event_id}")
            try:
                print("Seatmap HTML snippet (first 500 chars):")
                print(driver.page_source[:500])
            except Exception:
                pass
            return count

        except Exception as e:
            print(f"❌ Both popup and direct iframe methods failed for event {event_id}: {e}")

    return 0

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
