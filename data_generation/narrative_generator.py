"""
narrative_generator.py — AWS Bedrock Converse API + 3-tier prompt templates + disk cache.

Features:
- Two model IDs (BEDROCK_MODEL_ID for English, BEDROCK_MODEL_ID_KANNADA for translations)
- Disk cache: .narrative_cache/{cache_key}.json — reused on re-runs unless --force-narratives
- Adaptive retry + exponential backoff for throttling and transient errors
- Content-repair loop: if required identifiers are missing, re-prompt up to 3× with stricter instruction
- Failure collection to failures.json; caller decides whether to abort (--strict) or continue
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from .config import (
    BEDROCK_MODEL_ID, BEDROCK_MODEL_ID_KANNADA,
    NARRATIVE_CACHE_DIR, FAILURES_FILE,
    NARRATIVE_TEMPERATURE_TIER_A, NARRATIVE_TEMPERATURE_TIER_B, NARRATIVE_TEMPERATURE_TIER_C,
    NARRATIVE_MAX_TOKENS, NARRATIVE_CONTENT_REPAIR_RETRIES,
)
from .llm_client import FatalLLMError, RetryableLLMError, invoke_text

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------
CACHE_DIR = Path(NARRATIVE_CACHE_DIR)
CACHE_DIR.mkdir(exist_ok=True)

_failures: dict[str, str] = {}   # cache_key -> error message


def _cache_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.json"


def _is_content_filtered(text: str) -> bool:
    """Return True if text looks like a Bedrock content-filter stub."""
    lower = text.lower()
    markers = (
        "generated text has been blocked",
        "content filters",
        "content policy",
        "unable to fulfill this request",
        "i cannot fulfill",
        "i'm unable to generate",
    )
    return any(m in lower for m in markers)


def _read_cache(cache_key: str) -> Optional[str]:
    cp = _cache_path(cache_key)
    if cp.exists():
        try:
            text = json.loads(cp.read_text(encoding="utf-8"))["text"]
            if _is_content_filtered(text):
                logger.warning("Evicting poisoned cache entry for %s (content-filter stub)", cache_key)
                cp.unlink(missing_ok=True)
                return None
            return text
        except Exception:
            return None
    return None


def _write_cache(cache_key: str, model_id: str, text: str) -> None:
    payload = {"key": cache_key, "model": model_id, "text": text}
    tmp = _cache_path(cache_key).with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(_cache_path(cache_key))   # atomic replace


def _call_bedrock(prompt: str, model_id: str, temperature: float) -> str:
    """LangChain Bedrock call with proactive rate limiting + retry."""
    try:
        return invoke_text(
            prompt=prompt,
            model_id=model_id,
            temperature=temperature,
            max_tokens=NARRATIVE_MAX_TOKENS,
        )
    except RetryableLLMError as exc:
        raise RuntimeError(f"Bedrock retries exhausted: {exc}") from exc
    except FatalLLMError as exc:
        raise RuntimeError(f"Fatal Bedrock error: {exc}") from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_narrative(
    prompt: str,
    cache_key: str,
    model_id: str = BEDROCK_MODEL_ID,
    temperature: float = 0.7,
    force: bool = False,
    required_identifiers: Optional[list[str]] = None,
) -> str:
    """
    Generate a narrative with caching and optional content-repair loop.

    Args:
        prompt: The instruction prompt.
        cache_key: Unique key (e.g. "fir_scn1_h01_en_narrative"). Cache file is {key}.json.
        model_id: Bedrock model ID to use.
        temperature: Sampling temperature.
        force: If True, bypass cache and regenerate (--force-narratives flag).
        required_identifiers: If supplied, generated text must contain all these strings verbatim.
                              On missing identifiers, re-prompt up to NARRATIVE_CONTENT_REPAIR_RETRIES times.

    Returns:
        Generated narrative text.

    Raises:
        RuntimeError if generation fails after all retries and repair attempts.
        The caller should catch and route to _record_failure().
    """
    if not force:
        cached = _read_cache(cache_key)
        if cached is not None:
            logger.debug("Cache hit: %s", cache_key)
            return cached

    logger.info("Generating narrative for: %s (model=%s, temp=%.1f)", cache_key, model_id, temperature)
    text = _call_bedrock(prompt, model_id, temperature)

    # Content-repair loop
    if required_identifiers:
        missing = [idf for idf in required_identifiers if idf not in text]
        repair_attempt = 0
        while missing and repair_attempt < NARRATIVE_CONTENT_REPAIR_RETRIES:
            repair_attempt += 1
            repair_prompt = (
                prompt
                + "\n\n--- STRICT REQUIREMENT ---\n"
                + "The following identifiers MUST appear VERBATIM in your output. They are missing:\n"
                + "\n".join(f'  • "{idf}"' for idf in missing)
                + "\nPlease rewrite the narrative and ensure every identifier above appears exactly as shown."
            )
            logger.warning("Content repair attempt %d for %s — missing: %s", repair_attempt, cache_key, missing)
            text = _call_bedrock(repair_prompt, model_id, max(0.1, temperature - 0.1))
            missing = [idf for idf in required_identifiers if idf not in text]

        if missing:
            raise RuntimeError(
                f"Content repair exhausted for {cache_key}. "
                f"Still missing identifiers: {missing}. "
                f"To fix: add more identifier slots to the prompt template and increase skeleton coverage."
            )

    if _is_content_filtered(text):
        raise RuntimeError(
            f"Bedrock content filter blocked the response for {cache_key}. "
            f"Falling back to deterministic narrative."
        )

    _write_cache(cache_key, model_id, text)
    logger.info("Cached: %s (%d chars)", cache_key, len(text))
    return text

def record_failure(cache_key: str, error: str) -> None:
    """Record a hard-failed narrative to failures.json."""
    _failures[cache_key] = error
    failures_path = Path(FAILURES_FILE)
    failures_path.write_text(
        json.dumps(_failures, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.error("HARD FAIL [%s]: %s", cache_key, error)


def get_failures() -> dict[str, str]:
    return dict(_failures)


# ---------------------------------------------------------------------------
# Prompt builders (exact templates from the plan)
# ---------------------------------------------------------------------------

def build_tier_a_digital_arrest_prompt(
    victim_name: str, age: int, address: str, district: str,
    date: str, time: str, hours: int, amount: str,
    num_transfers: int, channel: str, beneficiary_account: str,
    realisation_trigger: str, police_station: str,
) -> str:
    return f"""Write an FIR narrative (250-350 words) for a digital arrest scam. The following MO description MUST appear almost verbatim in the output — change only the bracketed variables:

"The complainant {victim_name}, aged {age}, residing at {address}, {district}, states that on {date} at approximately {time}, they received a phone call from an unknown number. The caller identified themselves as an officer from TRAI (Telecom Regulatory Authority of India) and claimed that a SIM card registered in the complainant's name was being used for illegal activities and would be disconnected within 2 hours. The call was then transferred to a person claiming to be a CBI officer, who informed the complainant that their Aadhaar was linked to money laundering activities and that they were under 'digital arrest.' The complainant was instructed to remain on a Skype video call for continuous monitoring. Over the next {hours} hours, under threats of immediate physical arrest, the complainant was directed to transfer funds to a 'Supreme Court escrow account' for 'RBI verification.' The complainant transferred a total of Rs. {amount} in {num_transfers} transactions via {channel} to account number {beneficiary_account}. The complainant realised the fraud when {realisation_trigger} and approached {police_station} to file this complaint."

Output ONLY the FIR narrative text. Keep the MO structure intact. Do not add disclaimers. The account number {beneficiary_account} must appear verbatim in your output."""


def build_tier_a_task_scam_prompt(
    victim_name: str, age: int, occupation: str, district: str,
    date: str, telegram_handle: str, group_name: str, app_name: str,
    initial_deposit: str, total_amount: str, num_deposits: int,
    upi_list: str, mule_account: str, phone_list: str,
) -> str:
    return f"""Write an FIR narrative (200-300 words) for a task/job scam. The following MO description MUST appear almost verbatim — change only the bracketed variables:

"The complainant {victim_name}, aged {age}, a {occupation} from {district}, states that on {date} they received a message on Telegram from a user named {telegram_handle} offering a 'simple online task job' with daily earnings of Rs. 2000-5000. The complainant was added to a Telegram group named {group_name} and asked to complete simple tasks (liking videos, rating products) on an app called {app_name}. Initial small payments of Rs. 200-500 were received successfully, building trust. The complainant was then asked to 'upgrade to VIP membership' by depositing Rs. {initial_deposit}. After this, they were shown fake profits and asked to deposit increasingly larger sums to 'unlock withdrawals.' The complainant deposited a total of Rs. {total_amount} across {num_deposits} transactions to UPI IDs {upi_list} and account {mule_account}. When the complainant attempted to withdraw, the app showed an error and the group admins stopped responding. Phone numbers {phone_list} used by the operators are now unreachable."

Output ONLY the FIR narrative text. Keep the MO structure intact. UPI IDs ({upi_list}), account number ({mule_account}), and phone numbers ({phone_list}) must appear verbatim in your output."""


def build_tier_b_digital_arrest_prompt(
    victim_name: str, age: int, occupation: str, district: str,
    date: str, amount: str, beneficiary_account: str,
) -> str:
    return f"""Write an FIR narrative (250-350 words) for a digital arrest scam with the following DIFFERENT modus operandi (NOT the TRAI/CBI variant):

The scammer calls claiming to be from the "Narcotics Control Bureau" and tells the victim a parcel containing drugs was intercepted by customs with their name on it. They threaten immediate arrest and transfer the call to a fake "NCB officer" who demands the victim stay on a WhatsApp video call. The victim is told to transfer money to clear their name. Specific phrases to include: "parcel interception", "narcotic substances", "clearance certificate".

Use these details:
- Victim: {victim_name}, age {age}, {occupation}, {district}
- Date: {date}
- Amount lost: {amount}
- Beneficiary account: {beneficiary_account}

The narrative should read as a DIFFERENT playbook from the TRAI/CBI variant — same crime category but clearly a distinct operation. Account number {beneficiary_account} must appear verbatim.
Output ONLY the FIR narrative text."""


def build_tier_c_prompt(
    crime_type: str, victim_name: str, age: int, occupation: str,
    district: str, date: str, amount: str, identifiers_str: str,
) -> str:
    instructions = {
        "investment_scam": "Describe a fake stock trading app or WhatsApp investment group. Include fake profit screenshots shown to the victim and eventual blocking of withdrawals.",
        "upi_fraud": "Describe a fake UPI 'collect' request or QR code scam where the victim mistakenly pays instead of receiving money.",
        "loan_app": "Describe a predatory instant loan app that harvests contacts and sends morphed photos to family members demanding repayment of an unfair loan.",
        "otp_fraud": "Describe a caller impersonating a bank and extracting an OTP to gain access to the victim's bank account.",
        "job_scam": "Describe a fake placement agency charging registration/documentation fees for a job that does not exist.",
        "sextortion": "Describe a honey trap via social media where the victim is recorded during a video call and then blackmailed.",
        "phishing": "Describe a fake bank SMS with a link that harvests internet banking credentials.",
        "mule_account": "Describe recruitment of a victim as a money mule — offered commission to receive and forward funds in their bank account.",
    }
    type_instruction = instructions.get(crime_type, "Describe a cyber fraud case.")
    return f"""Write an FIR narrative (200-300 words) for a {crime_type} case.

{type_instruction}

Details:
- Victim: {victim_name}, age {age}, {occupation}, {district}
- Date: {date}
- Amount lost: {amount}
- Identifiers mentioned: {identifiers_str}

Output ONLY the FIR narrative text. Include the identifiers verbatim."""


def build_decoy_prompt(
    victim_name: str, district: str, amount: str, date: str, decoy_account: str,
) -> str:
    return f"""Write an FIR narrative (250-350 words) for a digital arrest scam. Use a hybrid approach that borrows some elements from the TRAI/CBI variant but mixes in different specifics:

- The caller claims to be from "TRAI" (same as typical digital arrest cases)
- BUT the threat is about "international call routing fraud" (different from money laundering)
- The victim is held on a Google Meet call (not Skype)
- They are told to transfer to a "RBI compliance account" (similar phrasing)
- The transfer goes to account {decoy_account} (this exact account number must appear verbatim)

Use these details:
- Victim: {victim_name}, {district}
- Amount: {amount}
- Date: {date}

This narrative should be similar in style and theme to TRAI/CBI digital arrest cases but MUST NOT share any account numbers, phone numbers, IMEIs, or UPIs with any other case. Account number {decoy_account} must appear verbatim.
Output ONLY the FIR narrative text."""


def build_kannada_translation_prompt(english_narrative: str) -> str:
    return f"""Translate the following FIR narrative from English to Kannada. This is a police First Information Report from Karnataka. Keep all proper nouns (names, places, account numbers, phone numbers, IMEI numbers, UPI IDs) exactly as-is in English/numerals — do not transliterate them. Use formal police/legal Kannada register. Preserve paragraph structure.

---
{english_narrative}
---

Output ONLY the Kannada translation."""


def build_back_translation_prompt(kannada_narrative: str) -> str:
    return f"""Translate the following Kannada FIR narrative back into English. Preserve all numbers, account identifiers, and proper nouns exactly. This is for verification purposes.

---
{kannada_narrative}
---

Output ONLY the English translation."""


def build_scn1_ir_prompt(
    agg_acc_number: str, bank: str, branch: str, mule_name: str, aadhaar: str,
    ctrl_imei: str, ctrl_upi: str,
    linked_fir_ids: list[str], officer_name: str, date: str, fir_number: str,
) -> str:
    fir_refs = ", ".join(linked_fir_ids)
    return f"""Write an investigation report (300-400 words) for a digital arrest case investigation. The report MUST contain ALL of the following specific identifiers as readable text:

1. Bank KYC finding: "Account {agg_acc_number} at {bank}, {branch}, is held by one {mule_name}, Aadhaar {aadhaar}. This account received funds from all four complainants' cases."
2. Device seizure: "A mobile device with IMEI {ctrl_imei} was seized from the premises. Analysis of the device revealed..."
3. Controller UPI: "UPI VPA {ctrl_upi} was found in the device's payment history, linked to transactions controlling the mule network."
4. Connection statement: "Investigation reveals that the same modus operandi was used across cases {fir_refs}, and the present case, with all victim funds routed to a common aggregation account."

Structure the report with sections: Subject, Summary of Investigation, Evidence Obtained, Key Findings, Recommendations.

IO Officer: {officer_name}
Report Date: {date}
FIR Reference: {fir_number}

Output ONLY the investigation report text. All identifiers listed above must appear verbatim."""


def build_scn2_ir_prompt(
    telecom: str, new_phone: str, dev_imei: str,
    linked_fir_ids: list[str], victim1: str, amt1: str, victim2: str, amt2: str,
    upi_02: str, officer_name: str, date: str, fir_number: str,
) -> str:
    fir_refs = ", ".join(linked_fir_ids)
    return f"""Write an investigation report (300-400 words) for an investment scam investigation. The report MUST contain:

1. CDR finding: "Call Detail Records obtained from {telecom} show a new number {new_phone} active on IMEI {dev_imei} — the same device previously linked to numbers used in cases {fir_refs}."
2. Account discovery: "A bank account received deposits from victims {victim1} (Rs. {amt1}) and {victim2} (Rs. {amt2}), indicating additional unreported victims."
3. Identity assessment: "Based on shared device IMEI {dev_imei} and UPI {upi_02}, the accused operating under aliases 'Imran S.', 'Imraan Sheikh', 'I. Shaikh' is assessed to be one individual."

Structure as: Subject, CDR Analysis, Financial Trail, Identity Assessment, Recommendations.

IO Officer: {officer_name}
Report Date: {date}
FIR Reference: {fir_number}

Output ONLY the investigation report text. All identifiers (IMEI {dev_imei}, UPI {upi_02}, phone {new_phone}) must appear verbatim."""


def build_scn3_ir_prompt(
    bridge_acc: str, belagavi_case: str, hub_acc: str,
    hub_operator: str, total_volume: str, num_transactions: int,
    time_window: str, num_mules: int, minutes: int,
    wallet_address: str, freezable_accs: list[str], freeze_date: str,
    officer_name: str, date: str, fir_number: str,
) -> str:
    freeze_acc_str = ", ".join(freezable_accs)
    return f"""Write an investigation report (300-400 words) for a UPI fraud case. The report MUST contain:

1. Bridge finding: "Account {bridge_acc} received funds from the victim's account and ALSO appears in the unrelated digital-arrest case {belagavi_case} — indicating a shared laundering network."
2. Hub identification: "Account {hub_acc} (KYC: {hub_operator}) is the highest-volume aggregation point, processing {total_volume} across {num_transactions} transactions in {time_window}."
3. Layering description: "Funds were split into sub-Rs.1-lakh tranches and distributed to {num_mules} mule accounts within {minutes} minutes."
4. Crypto endpoint: "Final cash-out traced to USDT wallet {wallet_address} via P2P exchange."
5. Freezable funds: "Approximately Rs. 6.2 lakh remains in accounts {freeze_acc_str} with no outbound movement since {freeze_date}."

Reference the attached transaction_dump.csv for the full ledger.

IO Officer: {officer_name}
Report Date: {date}
FIR Reference: {fir_number}

Output ONLY the investigation report text. All account numbers, wallet address, and case references must appear verbatim."""


def build_scn4_ir_prompt(
    num_operators: int, operator_names_with_roles: str,
    num_cases: int, controller_upi: str, controller_acc: str,
    dev_pool_value: str, fir_list: str, ip_values: str, location: str,
    officer_name: str, date: str, fir_number: str,
) -> str:
    return f"""Write an investigation report (300-400 words) for a task scam ring investigation based on a seized handler's device. The report MUST contain:

1. Operator roster: "The device contained a contact list with {num_operators} operator entries: {operator_names_with_roles} (e.g., 'Ravi V - caller', 'Suresh M - mule handler', 'Venkat R - recruiter')."
2. Script template: "A saved note titled 'Daily Script' contained the exact messaging template used across all {num_cases} reported cases: 'Hi, we have a simple online task job...'"
3. Controller accounts: "Payment records on the device show all commission payouts flowing to UPI {controller_upi} and account {controller_acc}."
4. Device identifiers: "The handler's device (IMEI {dev_pool_value}) was previously flagged in FIRs {fir_list}."
5. IP evidence: "Login records show all operators accessed the task-distribution dashboard from IPs {ip_values} — geolocated to {location}."

Reference the attached operator_roster.csv and script_template.txt.

IO Officer: {officer_name}
Report Date: {date}
FIR Reference: {fir_number}

Output ONLY the investigation report text. UPI {controller_upi}, account {controller_acc}, IMEI {dev_pool_value}, and IPs {ip_values} must appear verbatim."""


# ---------------------------------------------------------------------------
# NarrativeGenerator class  (thin wrapper for OOP usage in live_demo_generator)
# ---------------------------------------------------------------------------

class NarrativeGenerator:
    """
    Thin wrapper around generate_narrative() for use by live_demo_generator.
    Provides a .generate(fir_id, prompt, tier, crime_type, model_override) interface.
    """

    def __init__(self, force: bool = False, seed: int = 42):
        self.force = force
        self.seed = seed

    def generate(
        self,
        fir_id: str,
        prompt: str,
        tier: str = "B",
        crime_type: str = "digital_arrest",
        model_override: Optional[str] = None,
    ) -> str:
        """
        Generate a narrative for fir_id using the given prompt.
        model_override='kannada' uses BEDROCK_MODEL_ID_KANNADA.
        """
        temperature = {
            "A": NARRATIVE_TEMPERATURE_TIER_A,
            "B": NARRATIVE_TEMPERATURE_TIER_B,
            "C": NARRATIVE_TEMPERATURE_TIER_C,
        }.get(tier, NARRATIVE_TEMPERATURE_TIER_B)

        use_model = BEDROCK_MODEL_ID_KANNADA if model_override == "kannada" else BEDROCK_MODEL_ID

        try:
            return generate_narrative(
                prompt=prompt,
                cache_key=fir_id,
                temperature=temperature,
                model_id=use_model,
                force=self.force,
            )
        except Exception as exc:
            # Keep live-doc generation resilient even when Bedrock is unavailable.
            record_failure(fir_id, f"{exc} | fallback used")
            logger.warning("Narrative fallback for %s due to LLM failure: %s", fir_id, exc)
            return _fallback_narrative_from_prompt(prompt)


def _fallback_narrative_from_prompt(prompt: str) -> str:
    """
    Deterministic offline fallback when Bedrock is unavailable.

    Parses the key facts embedded in the prompt (complainant, amount, identifiers,
    crime type) and renders a concise but complete FIR/IR narrative paragraph so
    the document is human-readable and all required identifiers appear verbatim.
    """
    import re

    lines = prompt.strip().splitlines()

    # ── Extract fields from prompt text ──────────────────────────────────────
    def _find(pattern: str, default: str = "") -> str:
        for line in lines:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return default

    complainant   = _find(r"complainant is ([^,.]+)")
    age           = _find(r"age[d]?\s+(\d+)")
    occupation    = _find(r"(?:age[d]?\s+\d+,\s*)([^,.]+?)(?:\s+from|\.|,\s+He|\s+She|\s+who)")
    district      = _find(r"(?:in|from)\s+([A-Z][a-zA-Z\- ]+(?:Urban|Rural|Bengaluru|Mysuru|Hubballi|Mangaluru|Belagavi|[A-Z][a-z]+))")
    amount        = _find(r"Rs\.?\s*([\d,]+(?:\s*lakhs?|\s*crores?)?)")
    account       = _find(r"account(?:\s+number)?\s+([\w\d]+)")
    imei          = _find(r"IMEI\s+([\d]+)")
    upi           = _find(r"UPI(?:\s+VPA)?\s+([\w.@]+)")
    ip_addr       = _find(r"IP\s+(?:address\s+)?['\{\"]*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
    phone         = _find(r"phone\s+(?:number\s+)?([\d\+\- ]{10,15})")

    # ── Detect narrative type ─────────────────────────────────────────────────
    text_lower = prompt.lower()
    is_ir         = "investigation report" in text_lower
    is_kannada    = "kannada" in text_lower or "translate" in text_lower
    is_back_trans = "back" in text_lower and "translat" in text_lower

    if is_kannada and not is_back_trans:
        # Produce minimal Kannada stub — identifiers kept in Latin script
        parts = [f"ದೂರುದಾರರು ಸೈಬರ್ ವಂಚನೆಗೆ ಒಳಗಾಗಿದ್ದಾರೆ."]
        if complainant: parts.append(f"ದೂರುದಾರರ ಹೆಸರು: {complainant}.")
        if amount:      parts.append(f"ನಷ್ಟವಾದ ಮೊತ್ತ: Rs. {amount}.")
        for idf_label, idf_val in [("Bank account", account), ("IMEI", imei),
                                    ("UPI", upi), ("IP", ip_addr), ("Phone", phone)]:
            if idf_val:
                parts.append(f"{idf_label}: {idf_val}.")
        parts.append("ಪ್ರಕರಣವನ್ನು ತನಿಖೆ ನಡೆಸಲಾಗುತ್ತಿದೆ.")
        return " ".join(parts)

    if is_back_trans:
        # Return English summary of the Kannada content
        parts = ["The complainant filed a cybercrime complaint."]
        if complainant: parts.append(f"Complainant: {complainant}.")
        if amount:      parts.append(f"Amount lost: Rs. {amount}.")
        for idf_label, idf_val in [("Bank account", account), ("IMEI", imei),
                                    ("UPI", upi), ("IP", ip_addr)]:
            if idf_val:
                parts.append(f"{idf_label}: {idf_val}.")
        return " ".join(parts)

    # ── Build identifiers string ──────────────────────────────────────────────
    idf_parts = []
    if account: idf_parts.append(f"bank account {account}")
    if imei:    idf_parts.append(f"device IMEI {imei}")
    if upi:     idf_parts.append(f"UPI VPA {upi}")
    if ip_addr: idf_parts.append(f"IP address {ip_addr}")
    if phone:   idf_parts.append(f"phone number {phone}")
    idf_str = (", ".join(idf_parts[:-1]) + " and " + idf_parts[-1]) if len(idf_parts) > 1 \
              else (idf_parts[0] if idf_parts else "the above identifiers")

    # ── Detect crime type ────────────────────────────────────────────────────
    if "digital arrest" in text_lower or "cbi" in text_lower or "trai" in text_lower:
        crime_desc = (
            f"The complainant {complainant or 'the victim'}, aged {age or 'unknown'}, "
            f"{'a ' + occupation + ', ' if occupation else ''}"
            f"{'residing in ' + district + ', ' if district else ''}"
            "received a call from persons posing as government officials (TRAI/CBI). "
            "They falsely claimed the complainant's Aadhaar was linked to money laundering "
            "and coerced the complainant into making digital transfers under threat of 'digital arrest'. "
            f"The complainant lost a total of Rs. {amount or 'a substantial amount'} "
            f"which was transferred to {idf_str}. "
            "The fraud was realised after the transfers were completed. "
            "The complainant approached the police to file this complaint."
        )
    elif "task" in text_lower or "telegram" in text_lower or "rating" in text_lower:
        crime_desc = (
            f"The complainant {complainant or 'the victim'}, aged {age or 'unknown'}, "
            f"{'a ' + occupation + ', ' if occupation else ''}"
            "was contacted via Telegram with an offer of online task-based income. "
            "After completing initial tasks and receiving small payments to build trust, "
            "the complainant was asked to deposit increasingly large sums to 'unlock withdrawals'. "
            f"A total of Rs. {amount or 'a substantial amount'} was lost. "
            f"The operators used {idf_str}. "
            "When withdrawal was requested the platform became inaccessible and operators stopped responding."
        )
    elif "loan" in text_lower:
        crime_desc = (
            f"The complainant {complainant or 'the victim'}, aged {age or 'unknown'}, "
            f"{'a ' + occupation + ', ' if occupation else ''}"
            "downloaded an instant loan application and received a loan amount. "
            "Subsequently the complainant was subjected to harassment, threats, and coercion "
            "by the app operators who shared morphed images with the complainant's contacts. "
            f"A total of Rs. {amount or 'a substantial amount'} was extorted. "
            f"The accused used {idf_str} during the commission of the offence."
        )
    elif "investment" in text_lower or "stock" in text_lower or "trading" in text_lower:
        crime_desc = (
            f"The complainant {complainant or 'the victim'}, aged {age or 'unknown'}, "
            f"{'a ' + occupation + ', ' if occupation else ''}"
            "was added to a WhatsApp group promising high returns on stock market investments. "
            "After investing and seeing fake profits on a fraudulent platform, "
            "the complainant was unable to withdraw funds. "
            f"A total of Rs. {amount or 'a substantial amount'} was lost. "
            f"The accused operated through {idf_str}."
        )
    elif is_ir:
        crime_desc = (
            "Based on investigation of the reported cybercrime complaint, "
            f"the following findings are recorded. "
            f"{'Complainant: ' + complainant + '. ' if complainant else ''}"
            f"{'Amount involved: Rs. ' + amount + '. ' if amount else ''}"
            f"Digital forensics identified the following key identifiers: {idf_str}. "
            "Financial trail analysis confirms fund movement through the above accounts. "
            "Further investigation is in progress to identify and apprehend the accused."
        )
    else:
        crime_desc = (
            f"The complainant {complainant or 'the victim'}, aged {age or 'unknown'}, "
            f"{'a ' + occupation + ', ' if occupation else ''}"
            "reported a cybercrime offence. "
            f"A total of Rs. {amount or 'a substantial amount'} was lost "
            f"through transactions involving {idf_str}. "
            "The complainant approached the police to register this complaint and seek redressal."
        )

    return crime_desc
