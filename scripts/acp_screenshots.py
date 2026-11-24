"""Screenshots of the running app for the ACP slides (docs/acp/figures/*.png).

Drives a headless Chrome over the DevTools protocol: signs in with the demo account
(runs/demo_account.txt, see scripts/seed_demo_account.py), walks through the steps and saves one
picture per view. The app must be running on http://localhost:8000.

Usage: python scripts/acp_screenshots.py [--chrome PATH] [--lang en|tr]
"""
import argparse
import base64
import itertools
import json
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "acp" / "figures"
BASE = "http://localhost:8000"
CHROMES = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
           r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]


class Tab:
    def __init__(self, ws_url: str):
        self.ws = connect(ws_url, max_size=50_000_000)  # noqa: kept open for the whole run
        self.ids = itertools.count(1)

    def call(self, method: str, **params):
        i = next(self.ids)
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == i:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr: str, wait: float = 0.0):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", r["exceptionDetails"]))
        time.sleep(wait)
        return r.get("result", {}).get("value")

    def goto(self, url: str, wait: float = 2.5):
        self.call("Page.navigate", url=url)
        time.sleep(wait)

    def shot(self, name: str, full: bool = False):
        params = {"format": "png"}
        if full:
            m = self.call("Page.getLayoutMetrics")["cssContentSize"]
            params["clip"] = {"x": 0, "y": 0, "width": m["width"], "height": min(m["height"], 2400), "scale": 1}
            params["captureBeyondViewport"] = True
        data = self.call("Page.captureScreenshot", **params)["data"]
        (OUT / f"{name}.png").write_bytes(base64.b64decode(data))
        print(f"saved {name}.png")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--chrome", default=next((c for c in CHROMES if Path(c).exists()), None))
    p.add_argument("--lang", default="en")
    args = p.parse_args()
    creds = dict(line.split(":", 1) for line in (ROOT / "runs" / "demo_account.txt").read_text().splitlines() if ":" in line)
    email, password = creds["e-mail"].strip(), creds["password"].strip()
    admin_token = (ROOT / "runs" / "admin_token.txt").read_text().strip()
    OUT.mkdir(parents=True, exist_ok=True)

    profile = tempfile.mkdtemp(prefix="skilllens-shots-")
    proc = subprocess.Popen([args.chrome, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={profile}",
                             "--window-size=1440,900", "--hide-scrollbars", "--no-first-run", "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                pages = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
                break
            except OSError:
                time.sleep(0.2)
        tab = Tab(next(pg for pg in pages if pg["type"] == "page")["webSocketDebuggerUrl"])
        tab.call("Page.enable")
        tab.call("Emulation.setDeviceMetricsOverride", width=1440, height=900, deviceScaleFactor=1.5, mobile=False)

        tab.goto(BASE + "/")
        tab.js(f"localStorage.setItem('skilllens-lang', '{args.lang}'); localStorage.setItem('skilllens-mascot', 'off');"
               "localStorage.setItem('skilllens-theme', 'light'); localStorage.removeItem('skilllens-token');")
        tab.goto(BASE + "/", 3.5)
        tab.shot("home")

        # sign in with the demo account through the dialog
        tab.js(f"""(async () => {{ Account.open('login'); $('#auth-email').value = {json.dumps(email)};
                  $('#auth-password').value = {json.dumps(password)}; await Account.submit(); }})()""", 2.5)
        tab.js("Account.open('login'); $('[data-auth-tab=\"register\"]').click(); $('#auth-email').value='';"
               "$('#auth-password').value='';", 0.4)
        tab.shot("signin")
        tab.js("$('#auth-dialog').close()", 0.3)

        tab.js("(async () => { go(1); $('#cv-sample').click(); await new Promise(r => setTimeout(r, 2200)); "
               "window.scrollTo(0, 0); })()", 0.5)
        tab.shot("cv")
        tab.js("(async () => { $('#cv-confirm').click(); await new Promise(r => setTimeout(r, 2500)); "
               "$('#job-reco').scrollIntoView({block: 'start'}); window.scrollBy(0, -90); })()", 0.6)
        tab.shot("jobs")
        tab.js("(async () => { await selectJob(1); await new Promise(r => setTimeout(r, 2400)); "
               "$('#job-detail').scrollIntoView({block: 'start'}); window.scrollBy(0, -20); })()", 0.6)
        tab.shot("job")
        tab.js("(async () => { go(4); await new Promise(r => setTimeout(r, 3000)); window.scrollTo(0, 0); })()", 0.5)
        tab.shot("matches")
        tab.js("(async () => { state.roadmapJobId = 8; go(5); await new Promise(r => setTimeout(r, 3000)); "
               "$('.road-overview').scrollIntoView({block: 'start'}); window.scrollBy(0, -20); })()", 0.6)
        tab.shot("roadmap")

        tab.goto(BASE + "/docs", 4)
        tab.shot("docs")
        tab.js("(async () => { const b = [...document.querySelectorAll('.opblock-summary-path')]"
               ".find(e => e.textContent.trim() === '/jobs/{job_id}'); b?.closest('.opblock-summary')?.click(); })()", 1.2)
        tab.js("document.querySelector('#operations-tag-jobs')?.scrollIntoView({block: 'start'})", 0.6)
        tab.shot("docs_jobs")

        tab.goto(BASE + "/admin", 2)
        tab.js(f"(async () => {{ $('#adm-token').value = {json.dumps(admin_token)}; $('#adm-form').requestSubmit(); }})()", 2.5)
        tab.shot("admin")
        tab.js("sessionStorage.clear()")
        tab.goto(BASE + "/", 1.5)
        tab.js("localStorage.clear()")
    finally:
        proc.terminate()
        time.sleep(0.5)
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
