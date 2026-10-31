"""Screenshot the deployed app (desktop and phone) so the team can review the live UI.

    python scripts/screenshot_app.py --out shots
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


async def main(url: str, out: Path) -> None:
    from playwright.async_api import async_playwright
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1440, "height": 900})
        await pg.goto(url + "/#/", wait_until="networkidle", timeout=120000)
        await pg.wait_for_timeout(2500)
        await pg.screenshot(path=str(out / "1-home.png"), full_page=True)
        pol = await pg.evaluate("fetch('/api/policies').then(r=>r.json()).then(j=>(j.policies.sort((a,b)=>b.rules-a.rules)[0]||{}).id)")
        if pol:
            await pg.goto(f"{url}/#/policy/{pol}", wait_until="networkidle")
            await pg.wait_for_timeout(2000)
            await pg.screenshot(path=str(out / "2-policy.png"), full_page=True)
        await pg.goto(url + "/#/radar", wait_until="networkidle")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=str(out / "3-radar.png"), full_page=False)
        await pg.goto(url + "/#/how", wait_until="networkidle")
        await pg.wait_for_timeout(3000)
        await pg.screenshot(path=str(out / "4-how.png"), full_page=True)
        m = await b.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, device_scale_factor=2)
        await m.goto(url + (f"/#/policy/{pol}" if pol else "/#/"), wait_until="networkidle")
        await m.wait_for_timeout(2000)
        await m.screenshot(path=str(out / "5-phone.png"))
        await b.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("APP_URL", "").strip() or (ROOT / "deploy" / "app_url.txt").read_text().strip())
    ap.add_argument("--out", default="shots")
    a = ap.parse_args()
    asyncio.run(main(a.url.rstrip("/"), Path(a.out)))
