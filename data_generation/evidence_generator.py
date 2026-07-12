"""
evidence_generator.py - Generate evidence artifacts for scenario cases.

Produces for each scenario evidence folder:
  - messaging_screenshot_{n}.png  (Playwright renders HTML template -> PNG)
  - call_log.csv
  - transaction_ledger.csv
  - NOTE: Scenario 1 intentionally OMITS bsa_63_certificate.txt (planted amber gap)

Templates are in templates/ subdirectory.
Playwright is used for screenshot rendering; gracefully degrades to skip PNGs if not installed.
"""
from __future__ import annotations
import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config
from .identifier_pool import (
    AGG_ACC_01, SCN1_COLLECT_ACCS,
    DEV_IMEI_02, UPI_02, PHONE_02,
    BRIDGE_ACC_03,
    DEV_POOL_04, IP_POOL_04,
)

TEMPLATES_DIR = Path(__file__).parent / "templates"
PLAYWRIGHT_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# HTML template for messaging screenshot
# ---------------------------------------------------------------------------

CHAT_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{ font-family: Arial, sans-serif; background: #e5ddd5; padding: 20px; max-width: 400px; }}
.chat-box {{ background: white; border-radius: 10px; padding: 10px; margin-bottom: 8px; }}
.from-them {{ background: #fff; margin-right: 20%; }}
.from-me {{ background: #dcf8c6; margin-left: 20%; }}
.timestamp {{ font-size: 10px; color: #999; text-align: right; }}
.header {{ background: #075e54; color: white; padding: 10px; border-radius: 5px; margin-bottom: 15px; }}
</style>
</head>
<body>
<div class="header">{contact_name} +{phone}</div>
{messages_html}
</body>
</html>"""

MESSAGE_TEMPLATE = """<div class="chat-box {css_class}">
<p>{text}</p>
<div class="timestamp">{time}</div>
</div>"""

def _render_screenshot(html_content: str, out_path: Path) -> bool:
    """Render HTML to PNG using Playwright. Returns True on success."""
    if not PLAYWRIGHT_AVAILABLE:
        return False
    try:
        tmp_html = out_path.parent / "_tmp_screenshot.html"
        tmp_html.write_text(html_content, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 420, "height": 800})
            page.goto(f"file:///{tmp_html.as_posix()}")
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
        tmp_html.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"[evidence] Playwright screenshot failed: {e}. Skipping PNG.")
        return False

def _write_csv(path: Path, rows: List[Dict], fieldnames: List[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

# ---------------------------------------------------------------------------
# Scenario 1 evidence  (digital_arrest ring — BSA 63 cert INTENTIONALLY OMITTED)
# ---------------------------------------------------------------------------

def generate_scn1_evidence(base: Path) -> None:
    """
    Scenario 1: 3 historical + 1 live case evidence.
    PLANTED AMBER GAP: bsa_63_certificate.txt is NOT created here.
    """
    ev = base / "scenario_1" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)

    # Messaging screenshot: victim being threatened by fake CBI officer
    messages = [
        ("from-them", "This is DCP Sharma, CBI Cybercrime Division.", "10:03"),
        ("from-them", f"Your Aadhaar 4821 5630 7192 is linked to money laundering. "
                      f"Transfer Rs 42,00,000 to account {AGG_ACC_01['account_no']} "
                      f"immediately to avoid arrest.", "10:05"),
        ("from-me",   "I am innocent. Please do not arrest me.", "10:08"),
        ("from-them", f"Wire transfer required NOW. IFSC: {AGG_ACC_01['ifsc']}.", "10:09"),
    ]
    msgs_html = "\n".join(
        MESSAGE_TEMPLATE.format(css_class=css, text=txt, time=ts)
        for css, txt, ts in messages
    )
    html = CHAT_TEMPLATE.format(contact_name="DCP Sharma (Fake CBI)", phone="9100000001",
                                messages_html=msgs_html)
    _render_screenshot(html, ev / "messaging_screenshot_1.png")
    (ev / "messaging_screenshot_1.html").write_text(html, encoding="utf-8")

    # Call log CSV
    _write_csv(ev / "call_log.csv",
        [{"timestamp": "2026-05-12T10:03:00", "from": "+919100000001",
          "to": "+91-VICTIM", "duration_sec": 2340, "type": "incoming"},
         {"timestamp": "2026-05-12T10:45:00", "from": "+91-VICTIM",
          "to": "+919100000001", "duration_sec": 120, "type": "outgoing"}],
        ["timestamp","from","to","duration_sec","type"])

    # Transaction ledger
    _write_csv(ev / "transaction_ledger.csv",
        [{"txn_id": "TXN_SCN1_E01", "from_account": "VICTIM_ACC",
          "to_account": AGG_ACC_01["account_no"],
          "amount": 4200000, "timestamp": "2026-05-12T11:15:00",
          "channel": "NEFT", "status": "completed"},
         {"txn_id": "TXN_SCN1_E02",
          "from_account": AGG_ACC_01["account_no"],
          "to_account": "CRYPTO_WALLET_OFFSHORE",
          "amount": 3800000, "timestamp": "2026-05-12T11:45:00",
          "channel": "crypto", "status": "completed"}],
        ["txn_id","from_account","to_account","amount","timestamp","channel","status"])

    # INTENTIONALLY NO bsa_63_certificate.txt (planted amber gap for legal checklist demo)
    (ev / "README_EVIDENCE_GAP.txt").write_text(
        "PLANTED GAP: BSA Section 63 certificate for messaging_screenshot_1.png is missing.\n"
        "This is intentional — the legal checklist should flag this as AMBER.\n"
        "The screenshot evidence is present but lacks the required admissibility certificate.",
        encoding="utf-8")

# ---------------------------------------------------------------------------
# Scenario 2 evidence  (entity resolution — alias accused)
# ---------------------------------------------------------------------------

def generate_scn2_evidence(base: Path) -> None:
    ev = base / "scenario_2" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)

    # Screenshot showing shared IMEI / UPI usage
    messages = [
        ("from-them", f"Hi, I am your relationship manager for premium investment plan.", "14:22"),
        ("from-them", f"Transfer to UPI {UPI_02} for guaranteed 3x returns.", "14:25"),
        ("from-me",   "How do I verify this?", "14:27"),
        ("from-them", f"Call me on {PHONE_02} anytime.", "14:28"),
    ]
    msgs_html = "\n".join(
        MESSAGE_TEMPLATE.format(css_class=css, text=txt, time=ts)
        for css, txt, ts in messages
    )
    html = CHAT_TEMPLATE.format(contact_name="Investment Manager (Imran S.)",
                                phone=PHONE_02, messages_html=msgs_html)
    _render_screenshot(html, ev / "messaging_screenshot_1.png")
    (ev / "messaging_screenshot_1.html").write_text(html, encoding="utf-8")

    # Device forensics note
    (ev / "device_forensics.txt").write_text(
        f"Device IMEI: {DEV_IMEI_02}\n"
        f"Linked UPI: {UPI_02}\n"
        f"Phone: {PHONE_02}\n"
        "Note: Same IMEI found across 3 prior cases under different accused names.\n"
        "Platform entity resolution should surface this cross-case link.",
        encoding="utf-8")

    # BSA 63 certificate present for Scn 2
    (ev / "bsa_63_certificate.txt").write_text(
        "BSA Section 63 Certificate\n"
        "Electronic record admissibility confirmed by certifying officer.\n"
        f"Artifact: messaging_screenshot_1.png\nDate: 2026-06-24",
        encoding="utf-8")

# ---------------------------------------------------------------------------
# Scenario 3 evidence  (follow the money — bridge account)
# ---------------------------------------------------------------------------

def generate_scn3_evidence(base: Path) -> None:
    ev = base / "scenario_3" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)

    # Transaction trail showing layering through bridge account
    _write_csv(ev / "transaction_ledger.csv",
        [{"txn_id": "TXN_SCN3_E01", "from_account": "VICTIM_BLG",
          "to_account": BRIDGE_ACC_03["account_no"],
          "amount": 1200000, "timestamp": "2026-03-15T14:30:00",
          "channel": "UPI", "status": "completed"},
         {"txn_id": "TXN_SCN3_E02",
          "from_account": BRIDGE_ACC_03["account_no"],
          "to_account": "MULE_ACC_OFFSHORE_1",
          "amount": 580000, "timestamp": "2026-03-15T14:45:00",
          "channel": "IMPS", "status": "completed"},
         {"txn_id": "TXN_SCN3_E03",
          "from_account": BRIDGE_ACC_03["account_no"],
          "to_account": "MULE_ACC_OFFSHORE_2",
          "amount": 580000, "timestamp": "2026-03-15T14:46:00",
          "channel": "IMPS", "status": "completed"},
         {"txn_id": "TXN_SCN3_E04",
          "from_account": BRIDGE_ACC_03["account_no"],
          "to_account": "FREEZABLE_RESIDUAL",
          "amount": 620000, "timestamp": "2026-03-15T14:50:00",
          "channel": "NEFT", "status": "pending"}],
        ["txn_id","from_account","to_account","amount","timestamp","channel","status"])

    (ev / "account_details.txt").write_text(
        f"Bridge Account: {BRIDGE_ACC_03['account_no']}\n"
        f"Bank: {BRIDGE_ACC_03['bank']}\n"
        f"IFSC: {BRIDGE_ACC_03['ifsc']}\n"
        f"Branch District: {BRIDGE_ACC_03['branch_district']}\n"
        "Status: Flagged as mule account\n"
        "Freezable amount: ~Rs 6,20,000 (TXN_SCN3_E04 pending)\n",
        encoding="utf-8")

    (ev / "bsa_63_certificate.txt").write_text(
        "BSA Section 63 Certificate\n"
        "Electronic record admissibility confirmed.\n"
        "Artifact: transaction_ledger.csv\nDate: 2026-06-25",
        encoding="utf-8")

# ---------------------------------------------------------------------------
# Scenario 4 evidence  (surge — task scam burst)
# ---------------------------------------------------------------------------

def generate_scn4_evidence(base: Path) -> None:
    ev = base / "scenario_4" / "evidence"
    ev.mkdir(parents=True, exist_ok=True)

    # Fake task app screenshot
    messages = [
        ("from-them", "Welcome to TaskEarn Pro! Complete simple tasks and earn.", "09:01"),
        ("from-them", "Task 1: Rate this product. Earn Rs 200.", "09:05"),
        ("from-me",   "Done! When will I receive payment?", "09:10"),
        ("from-them", "To unlock payout you need to deposit Rs 5000 first.", "09:12"),
        ("from-me",   "Okay, I will transfer.", "09:14"),
    ]
    msgs_html = "\n".join(
        MESSAGE_TEMPLATE.format(css_class=css, text=txt, time=ts)
        for css, txt, ts in messages
    )
    html = CHAT_TEMPLATE.format(contact_name="TaskEarn Support",
                                phone="9000000000", messages_html=msgs_html)
    _render_screenshot(html, ev / "messaging_screenshot_1.png")
    (ev / "messaging_screenshot_1.html").write_text(html, encoding="utf-8")

    # Device pool usage
    device_info = []
    for i, imei in enumerate(DEV_POOL_04[:5], 1):
        ip = IP_POOL_04[i-1] if i <= len(IP_POOL_04) else "103.21.58.99"
        device_info.append({"device_no": i, "imei": imei, "ip_address": ip,
                             "cases_linked": "multiple"})
    _write_csv(ev / "device_pool.csv", device_info,
        ["device_no","imei","ip_address","cases_linked"])

    (ev / "bsa_63_certificate.txt").write_text(
        "BSA Section 63 Certificate\n"
        "Electronic record admissibility confirmed.\n"
        "Artifact: messaging_screenshot_1.png\nDate: 2026-06-26",
        encoding="utf-8")

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_all_evidence(output_dir: str = None) -> None:
    """Generate all evidence artifacts under output/historical/evidence/."""
    base = Path(output_dir or config.OUTPUT_DIR) / "historical" / "evidence"
    if not PLAYWRIGHT_AVAILABLE:
        print("[evidence] WARNING: playwright not installed. PNGs will be skipped. "
              "HTML files will still be written.")

    TEMPLATES_DIR.mkdir(exist_ok=True)

    generate_scn1_evidence(base)
    generate_scn2_evidence(base)
    generate_scn3_evidence(base)
    generate_scn4_evidence(base)
    print(f"[evidence] Done. Output: {base}")
