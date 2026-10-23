# -*- coding: utf-8 -*-
"""The setup image for the video: the same Purchase Order screen, left as a plain screenshot, right with the set-of-mark numbers the SOM agent sees.
Usage: python make_compare_image.py <out.png>"""
import io, os, sys
from PIL import Image
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import URL, W, H, INDEX_JS, MARK_JS

out = sys.argv[1]
with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome")
    page = br.new_page(viewport={"width": W, "height": H}, locale="en-US")
    page.goto(URL)
    page.click('nav button:has-text("Purchase Order")')
    page.wait_for_timeout(600)                 # let the notice pop up, as the agents saw it
    plain = Image.open(io.BytesIO(page.screenshot()))
    page.evaluate(INDEX_JS)
    page.evaluate(MARK_JS)
    marked = Image.open(io.BytesIO(page.screenshot()))
    br.close()
gap = 24
canvas = Image.new("RGB", (W * 2 + gap * 3, H + gap * 2), (0x1A, 0x1D, 0x26))
canvas.paste(plain, (gap, gap))
canvas.paste(marked, (W + gap * 2, gap))
os.makedirs(os.path.dirname(out), exist_ok=True)
canvas.save(out)
print(out, canvas.size)
