# Ticket Watcher Bot — Movie
# Install: pip install requests playsound
import requests, time, webbrowser

URL = "https://your-cinema-site.com/tickets"
KEYWORDS = ["Book Now", "Add to Cart", "Select Seats"]
INTERVAL = 30  # seconds between checks

def check():
    try:
        r = requests.get(URL, timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        html = r.text.lower()
        found = [k for k in KEYWORDS if k.lower() in html]
        return found
    except Exception as e:
        print(f"Error: {e}")
        return []

print(f"Watching: {URL}")
print(f"Keywords: {KEYWORDS}\n")

while True:
    print(f"Checking... ({time.strftime('%H:%M:%S')})", end=" ")
    found = check()
    if found:
        print(f"\n🎟️  TICKETS FOUND! Keywords: {found}")
        webbrowser.open(URL)
        import os; os.system("afplay /System/Library/Sounds/Glass.aiff 2>/dev/null || echo '\a'")
        break
    else:
        print("Not yet.")
    time.sleep(INTERVAL)
