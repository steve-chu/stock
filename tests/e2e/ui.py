"""瀏覽器測試用的小工具。"""


def is_chromium(page):
    return page.context.browser.browser_type.name == "chromium"


def touch_drag(page, x, y, dx, dy, hold_ms=0, steps=12):
    """真的手指觸控（只有 chromium 能模擬）：按住、拖、放開。"""
    cdp = page.context.new_cdp_session(page)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
    if hold_ms:
        page.wait_for_timeout(hold_ms)
    for i in range(1, steps + 1):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x + dx * i / steps, "y": y + dy * i / steps}]})
        page.wait_for_timeout(15)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})


def enter_bb(page):
    """貝貝版：照片 → Tap to continue → Loyalty Check 按 Yes → 主畫面。"""
    page.locator(".bb-photo").wait_for(timeout=8000)
    page.locator(".bb-splash").click()
    page.locator(".bb-yes").wait_for()
    page.wait_for_timeout(300)
    page.locator(".bb-yes").click()
    page.locator(".bb-splash").wait_for(state="detached", timeout=5000)
