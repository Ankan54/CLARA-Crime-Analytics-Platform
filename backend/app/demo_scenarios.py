"""Server-side allowlist for demo scenario mappings.

Only the four CrimeNos listed here are eligible for destructive prepare/reset.
State rows are created lazily without inserting dummy CaseMaster records.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioMapping:
    key: str
    label: str
    crime_no: str
    evidence_folder: str  # under sample_data/live_demo/evidence/


SCENARIO_ALLOWLIST: dict[str, ScenarioMapping] = {
    "digital-arrest": ScenarioMapping(
        key="digital-arrest",
        label="Digital Arrest",
        crime_no="129011001202600001",
        evidence_folder="scenario_1",
    ),
    "many-names": ScenarioMapping(
        key="many-names",
        label="Many Names, One Man",
        crime_no="129011005202600001",
        evidence_folder="scenario_2",
    ),
    "follow-money": ScenarioMapping(
        key="follow-money",
        label="Follow The Money",
        crime_no="129191018202600001",
        evidence_folder="scenario_3",
    ),
    "surge": ScenarioMapping(
        key="surge",
        label="The Surge",
        crime_no="129011002202600001",
        evidence_folder="scenario_4",
    ),
}


def is_allowed_scenario(key: str) -> bool:
    return key in SCENARIO_ALLOWLIST


def get_scenario(key: str) -> ScenarioMapping | None:
    return SCENARIO_ALLOWLIST.get(key)


def get_crime_no(key: str) -> str | None:
    mapping = SCENARIO_ALLOWLIST.get(key)
    return mapping.crime_no if mapping else None
