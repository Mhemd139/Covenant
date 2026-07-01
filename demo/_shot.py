import sys

from playwright.sync_api import sync_playwright

url, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1000, "height": 760}, device_scale_factor=2)
    pg.goto(url, wait_until="networkidle")
    pg.wait_for_timeout(1500)  # let a poll tick render
    pg.screenshot(path=out, full_page=True)
    b.close()
print("wrote", out)
