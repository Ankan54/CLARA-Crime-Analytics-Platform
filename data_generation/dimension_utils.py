"""
dimension_utils.py - De-duplicate Corpus dimension objects.

Ensures each dimension list (accounts, devices, upis, phones, ips, wallets)
contains exactly ONE row per unique natural-key value. Any duplicates are
merged (first entry wins). The USES/transactions link rows are updated to
reference the canonical dimension row by the natural key.

This guarantees that when export.py writes the CSV dimension tables, no
duplicate rows exist. graph_builder.py can then MERGE nodes on the natural
key and recover the planted cross-case convergence links.

Call:  from dimension_utils import dedup_corpus; dedup_corpus(corpus)
"""
from __future__ import annotations
import logging
from typing import Any, Dict, List

from .models import Corpus, Account, Device, UPI, Phone, IP, Wallet

log = logging.getLogger("dimension_utils")


def _dedup(items: list, key_attr: str) -> list:
    """Return deduplicated list, keeping the FIRST occurrence per key_attr value."""
    seen = {}
    out = []
    for item in items:
        key = getattr(item, key_attr, None)
        if key is None:
            out.append(item)
            continue
        if key not in seen:
            seen[key] = item
            out.append(item)
        else:
            pass  # duplicate silently dropped; first wins
    return out


def dedup_corpus(corpus: Corpus) -> Dict[str, int]:
    """
    Deduplicate all dimension lists in-place.
    Returns summary dict {dimension_name -> removed_count}.
    """
    summary = {}

    before = len(corpus.accounts)
    corpus.accounts = _dedup(corpus.accounts, "account_no")
    summary["accounts"] = before - len(corpus.accounts)

    before = len(corpus.devices)
    corpus.devices = _dedup(corpus.devices, "imei")
    summary["devices"] = before - len(corpus.devices)

    before = len(corpus.upis)
    corpus.upis = _dedup(corpus.upis, "vpa")
    summary["upis"] = before - len(corpus.upis)

    before = len(corpus.phones)
    corpus.phones = _dedup(corpus.phones, "number")
    summary["phones"] = before - len(corpus.phones)

    before = len(corpus.ips)
    corpus.ips = _dedup(corpus.ips, "ip_address")
    summary["ips"] = before - len(corpus.ips)

    before = len(corpus.wallets)
    corpus.wallets = _dedup(corpus.wallets, "address")
    summary["wallets"] = before - len(corpus.wallets)

    total_removed = sum(summary.values())
    if total_removed:
        log.info(f"Dimension dedup removed {total_removed} duplicates: {summary}")
    else:
        log.debug("Dimension dedup: no duplicates found")

    return summary


def get_dimension_counts(corpus: Corpus) -> Dict[str, int]:
    """Return {dimension -> count} for validation."""
    return {
        "accounts": len(corpus.accounts),
        "devices":  len(corpus.devices),
        "upis":     len(corpus.upis),
        "phones":   len(corpus.phones),
        "ips":      len(corpus.ips),
        "wallets":  len(corpus.wallets),
    }


def assert_no_duplicates(corpus: Corpus) -> List[str]:
    """
    Return list of violation messages (empty = pass).
    For use in validate.py Suite F.
    """
    violations = []

    def check(items: list, key_attr: str, dim_name: str):
        seen: Dict[Any, int] = {}
        for item in items:
            key = getattr(item, key_attr, None)
            if key is None:
                continue
            seen[key] = seen.get(key, 0) + 1
        dups = {k: v for k, v in seen.items() if v > 1}
        for k, cnt in dups.items():
            violations.append(f"{dim_name}: '{k}' appears {cnt} times (expected 1)")

    check(corpus.accounts, "account_no", "accounts")
    check(corpus.devices,  "imei",       "devices")
    check(corpus.upis,     "vpa",        "upis")
    check(corpus.phones,   "number",     "phones")
    check(corpus.ips,      "ip_address", "ips")
    check(corpus.wallets,  "address",    "wallets")

    return violations
