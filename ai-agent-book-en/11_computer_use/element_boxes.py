# -*- coding: utf-8 -*-
"""Print where the key elements really are on the Stock screen (to compare with the coordinates the SHOT agent clicked).
Usage: python element_boxes.py"""
import os, sys
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("OPENAI_API_KEY", "x")
from lab import URL, W, H

with sync_playwright() as p:
    br = p.chromium.launch(channel="chrome")
    page = br.new_page(viewport={"width": W, "height": H}, locale="en-US")
    page.goto(URL)
    for sel, name in [("#sq", "Item input"), ("#sc .ddb", "Warehouse dropdown"), ("#sbtn", "Search button"),
                      ('nav button:has-text("Orders")', "Orders tab"), ('nav button:has-text("Purchase Order")', "Purchase Order tab")]:
        b = page.locator(sel).bounding_box()
        print("%-20s x %d–%d · y %d–%d" % (name, b["x"], b["x"] + b["width"], b["y"], b["y"] + b["height"]))
    br.close()
