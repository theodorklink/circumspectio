"""Daily production entry point. No paid APIs or mail without --live.

State is stored on a separate GitHub branch, shared by Actions and external
workers. Never automatically retry an ambiguous SendGrid request.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Europe/Berlin")
ROOT = Path(__file__).resolve().parent


def clock():
    return dt.datetime.now(TZ)


class Ledger:
    """GitHub Contents API with optimistic locking, never an Actions cache.

    The initial create is atomic. Existing records block competing workers,
    manual reruns and backup triggers before any research or email costs.
    No retry or lease expiry: an abandoned claim needs operator inspection.
    """

    def __init__(self, repo, token, branch="circumspectio-state", session=None):
        if not repo or not token:
            raise RuntimeError("GITHUB_REPOSITORY und GITHUB_TOKEN erforderlich")
        self.base = f"https://api.github.com/repos/{repo}"
        self.branch = branch
        self.http = session or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}",
                                  "Accept": "application/vnd.github+json"})
        self.sha = None

    def request(self, method, path, **kwargs):
        r = self.http.request(method, self.base + path, timeout=30, **kwargs)
        if r.status_code not in (200, 201, 404, 409, 422):
            raise RuntimeError(f"Ledger API: HTTP {r.status_code}")
        return r

    def ensure_branch(self):
        r = self.request("GET", f"/git/ref/heads/{self.branch}")
        if r.status_code == 200:
            return
        if r.status_code != 404:
            raise RuntimeError("Ledger branch unreadable")
        repo = self.request("GET", "")
        if repo.status_code != 200:
            raise RuntimeError("Repository unreadable")
        ref = self.request("GET", f"/git/ref/heads/{repo.json()['default_branch']}")
        if ref.status_code != 200:
            raise RuntimeError("Base ref unreadable")
        r = self.request("POST", "/git/refs", json={"ref": f"refs/heads/{self.branch}",
                                                  "sha": ref.json()["object"]["sha"]})
        if r.status_code not in (201, 422):
            raise RuntimeError("Cannot create ledger branch")
        # 422 can mean a concurrent worker just created the branch.
        if self.request("GET", f"/git/ref/heads/{self.branch}").status_code != 200:
            raise RuntimeError("Ledger branch unavailable")

    def read(self, day):
        r = self.request("GET", f"/contents/delivery/{day}.json", params={"ref": self.branch})
        if r.status_code == 404:
            self.sha = None
            return None
        if r.status_code != 200:
            raise RuntimeError("Ledger read failed")
        self.sha = r.json()["sha"]
        return json.loads(base64.b64decode(r.json()["content"]))

    def write(self, day, record):
        payload = {"message": f"delivery {day}: {record['status']}", "branch": self.branch,
                   "content": base64.b64encode(json.dumps(record, indent=2).encode()).decode()}
        if self.sha:
            payload["sha"] = self.sha
        r = self.request("PUT", f"/contents/delivery/{day}.json", json=payload)
        if r.status_code not in (200, 201):
            raise RuntimeError("Ledger conflict or write failed. No send permitted.")
        self.sha = r.json()["content"]["sha"]


def target_for(now, hour=7):
    if not 0 <= hour <= 23:
        raise ValueError("SEND_HOUR muss zwischen 0 und 23 liegen")
    return now.astimezone(TZ).replace(hour=hour, minute=0, second=0, microsecond=0)


def execute(ledger, generate, send, *, now_fn=clock, hour=7, retry_failed=False, report=None):
    started = now_fn().astimezone(TZ)
    target = target_for(started, hour)
    # UTC cron pairs are only wake-ups. Eligibility depends on local wall time.
    # Also rejects next-day delayed starts before the preparation window.
    earliest = target - dt.timedelta(hours=2)
    latest = target + dt.timedelta(hours=5)
    record = {"date": started.date().isoformat(), "started_at": started.isoformat(),
              "target_at": target.isoformat(), "run_id": os.getenv("GITHUB_RUN_ID"),
              "start_late_seconds": max(0, int((started-target).total_seconds()))}
    if not earliest <= started <= latest or earliest.date() != target.date():
        record["status"] = "outside_window"
        if report:
            report(record)
        return record
    ledger.ensure_branch()
    day = record["date"]
    prior = ledger.read(day)
    if prior and not (retry_failed and prior["status"] == "failed_before_send"):
        record.update(status="duplicate_suppressed", prior_status=prior["status"])
        if report:
            report(record)
        if prior["status"] != "accepted":
            raise RuntimeError(f"Ungeklärter Tagesstatus: {prior['status']}. Vor Wiederholung prüfen.")
        return record
    record["status"] = "generating"
    ledger.write(day, record)  # Atomic daily claim before the first paid API call.
    if report:
        report(record)
    sending = False

    def before_send(receipt):
        nonlocal sending
        record.update(receipt, status="sending")
        ledger.write(day, record)
        sending = True
        if report:
            report(record)

    try:
        content = generate(started)
        receipt = send(content, started, now_fn, before_send)
        record.update(receipt, status="accepted", completed_at=now_fn().isoformat())
        ledger.write(day, record)
    except BaseException:
        # The POST may have reached SendGrid even if the response was lost.
        record.update(status="unknown" if sending else "failed_before_send",
                      completed_at=now_fn().isoformat())
        try:
            ledger.write(day, record)
        finally:
            if report:
                report(record)
        raise
    if report:
        report(record)
    return record


def generate(now):
    import briefing as b
    b.OUT.mkdir(exist_ok=True)
    data, seen = b.recherchieren(now)
    (b.OUT / "briefing.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    b.links_pruefen(data, seen)
    media = b.medien_erzeugen(data)
    mail = b.rendern(data, media, now, "cid")
    html = b.rendern(data, media, now, "data")
    (b.OUT / "circumspectio.html").write_text(html, encoding="utf-8")
    return mail, html, b.klartext(data, now), media


def send(content, now, now_fn, before_send):
    import briefing as b
    return b.senden(*content, now, clock=now_fn, before_send=before_send)


def report(record):
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "status.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n```json\n" + json.dumps(record, indent=2) + "\n```\n")
    if record.get("late_seconds", record.get("start_late_seconds", 0)) > 0:
        print("::warning::Zielzeit verfehlt. Status und SendGrid Activity prüfen.")


def check(ledger, now, hour=7):
    """Read-only deadline check. API errors and absent records fail closed."""
    target = target_for(now, hour)
    record = ledger.read(target.date().isoformat())
    if not record or record.get("status") != "accepted":
        raise RuntimeError("Heutige SendGrid-Annahme fehlt oder ist ungeklärt")
    submitted = dt.datetime.fromisoformat(record["submitted_at"])
    accepted = dt.datetime.fromisoformat(record["accepted_at"])
    if submitted > target or accepted > target or record.get("send_at") != int(target.timestamp()):
        raise RuntimeError("Ausgabe nicht rechtzeitig für die Zielzeit angenommen")
    print("SendGrid-Annahme bestätigt. Tatsächliche Zustellung separat prüfen.")
    return record


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true", help="Kostenpflichtige Recherche und echten Versand erlauben")
    mode.add_argument("--check", action="store_true", help="Nur Tagesstatus prüfen, keine Recherche oder Mail")
    ap.add_argument("--retry-failed", action="store_true", help="Nur Fehler VOR dem Versand erneut versuchen")
    args = ap.parse_args()
    hour = int(os.getenv("SEND_HOUR", "7"))
    ledger = Ledger(os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_TOKEN"))
    if args.check:
        check(ledger, clock(), hour)
    else:
        for name in ("ANTHROPIC_API_KEY", "SENDGRID_API_KEY", "MAIL_FROM", "MAIL_TO"):
            if not os.getenv(name, "").strip():
                raise RuntimeError(f"Fehlende Konfiguration: {name}")
        execute(ledger, generate, send, hour=hour, retry_failed=args.retry_failed, report=report)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"::error::Circumspectio: {type(exc).__name__}")
        raise SystemExit(f"Circumspectio fehlgeschlagen: {type(exc).__name__}. Tagesstatus prüfen.")
