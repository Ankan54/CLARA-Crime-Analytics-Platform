#!/usr/bin/env python3
"""
generate.py - Two-route pipeline for KSP Crime Intelligence Platform synthetic dataset.

HISTORICAL ROUTE (pre-loaded):
  preflight -> reference -> entities -> historical_docs -> narratives ->
  sql_csv -> db_load -> graph_from_db -> vector_embed_docs

DEMO ROUTE (held back):
  live_docs -> evidence

VALIDATION:
  validate

Historical artifacts land in output/historical/ (docs/, sql/, db/, graph/, vector/).
Live demo artifacts land in output/live_demo/ (docs + expected.json only).
NOTHING from live_demo/ is loaded into any DB — this invariant is validated.

Flags:
  --seed N              reproducibility seed (default 42)
  --stages s1,s2,...    run only specified stages (comma-separated)
  --resume              skip already-checkpointed stages
  --force-narratives    re-generate narratives even if cached
  --strict              treat validation warnings as errors
  --skip-preflight      skip environment checks
  --skip-evidence       skip Playwright screenshot generation
  --output-dir DIR      output directory (default 'output')
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import pickle
import random
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from . import config
from . import id_registry as reg
from . import ksp_master as km
# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ]
)
log = logging.getLogger("generate")

# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------
CHECKPOINT_DIR = Path(config.CHECKPOINT_DIR)
CORPUS_ARTIFACT = "corpus.pkl"
NARRATIVE_ARTIFACT = "narrative_map.json"
PROJECTION_ARTIFACT = "fir_projections.pkl"
REGISTRY_ARTIFACT = "id_registry_state.json"
KSP_SERIAL_ARTIFACT = "ksp_serial_state.json"

def _checkpoint_path(stage: str) -> Path:
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    return CHECKPOINT_DIR / f"{stage}.done"

def _is_checkpointed(stage: str) -> bool:
    return _checkpoint_path(stage).exists()

def _write_checkpoint(stage: str, data: Any = None) -> None:
    _checkpoint_path(stage).write_text(
        json.dumps({"stage": stage, "ts": time.time(), "data": data or {}}),
        encoding="utf-8"
    )
    log.info(f"Checkpoint written: {stage}")

def _artifact_path(name: str) -> Path:
    CHECKPOINT_DIR.mkdir(exist_ok=True)
    return CHECKPOINT_DIR / name

def _save_pickle_artifact(name: str, payload: Any) -> None:
    path = _artifact_path(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("wb") as f:
        pickle.dump(payload, f)
    tmp.replace(path)

def _load_pickle_artifact(name: str) -> Any:
    path = _artifact_path(name)
    if not path.exists():
        return None
    with path.open("rb") as f:
        return pickle.load(f)

def _save_json_artifact(name: str, payload: Any) -> None:
    path = _artifact_path(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def _load_json_artifact(name: str, default: Any = None) -> Any:
    path = _artifact_path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _clear_checkpoints() -> None:
    if CHECKPOINT_DIR.exists():
        for f in CHECKPOINT_DIR.glob("*"):
            f.unlink()

# ---------------------------------------------------------------------------
# NEW STAGE ORDER (two-route pipeline)
# ---------------------------------------------------------------------------
ALL_STAGES = [
    "preflight",       # 1. environment checks
    "reference",       # 2. KSP masters, id_registry, live reservations
    "entities",        # 3. scenario + background entity generation -> Corpus
    "historical_docs", # 4. generate full FIR+IR docs for every historical case
    "narratives",      # 5. Bedrock LLM narratives (cached)
    "sql_csv",         # 6. project Corpus -> KSP-core + extension CSVs
    "db_load",         # 7. load CSVs into ksp.sqlite via schema.sql
    "graph_from_db",   # 8. build Neo4j CSVs by reading ksp.sqlite
    "vector_embed_docs",# 9. embed full docs into vector JSONL
    "live_docs",       # 10. generate held-back live demo docs + expected.json
    "evidence",        # 11. Playwright screenshots + CSV evidence artifacts
    "validate",        # 12. run all validation suites
]

# ---------------------------------------------------------------------------
# Stage 1: Preflight
# ---------------------------------------------------------------------------

def stage_preflight(args) -> None:
    if args.skip_preflight:
        log.info("Preflight skipped (--skip-preflight)")
        return
    import shutil
    free_bytes = shutil.disk_usage(".").free
    if free_bytes < 500 * 1024 * 1024:
        raise RuntimeError(f"Insufficient disk space: {free_bytes // (1024*1024)} MB free")
    log.info(f"Disk space OK: {free_bytes // (1024*1024)} MB free")
    env_path = Path(".env")
    if not env_path.exists():
        log.warning(".env not found. AWS credentials must be in environment.")
    else:
        from dotenv import load_dotenv
        load_dotenv()
        log.info(".env loaded")
    import boto3
    try:
        sts = boto3.client("sts",
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
            region_name=os.environ.get("AWS_REGION","us-east-1"),
        )
        identity = sts.get_caller_identity()
        log.info(f"AWS credentials OK: Account={identity.get('Account')}")
    except Exception as e:
        log.warning(f"AWS credentials check failed: {e}")
    _write_checkpoint("preflight")

# ---------------------------------------------------------------------------
# Stage 2: Reference + KSP master + ID registry
# ---------------------------------------------------------------------------

def stage_reference(args) -> None:
    log.info("Resetting KSP serial counters and id_registry...")
    km.reset_serials()
    reg.reset_registry()
    # Reserve live case CrimeNos FIRST (before historical assignments)
    reservations = reg.reserve_live_cases()
    log.info("Reserved live case CrimeNos:")
    for k, v in reservations.items():
        log.info(f"  {k}: CrimeNo={v['crime_no']} Station={v['station_id']}")
    _save_json_artifact(REGISTRY_ARTIFACT, reg.export_state())
    _save_json_artifact(KSP_SERIAL_ARTIFACT, km.export_serial_state())
    _write_checkpoint("reference", {"live_reservations": reservations})

# ---------------------------------------------------------------------------
# Stage 3: Entity generation
# ---------------------------------------------------------------------------

def stage_entities(args) -> Dict:
    from .models import Corpus
    from .scenario_1 import generate_scenario_1
    from .scenario_2 import generate_scenario_2
    from .scenario_3 import generate_scenario_3
    from .scenario_4 import generate_scenario_4
    from .background_generator import generate_background
    from .dimension_utils import dedup_corpus

    corpus = Corpus()

    def _merge_bundle(bundle: Dict[str, Any]) -> None:
        if not bundle:
            return
        corpus.firs.extend(bundle.get("firs", []))
        corpus.investigation_reports.extend(bundle.get("investigation_reports", []))
        corpus.persons.extend(bundle.get("persons", []))
        corpus.accounts.extend(bundle.get("accounts", []))
        corpus.transactions.extend(bundle.get("transactions", []))
        corpus.phones.extend(bundle.get("phones", []))
        corpus.devices.extend(bundle.get("devices", []))
        corpus.upis.extend(bundle.get("upis", []))
        corpus.ips.extend(bundle.get("ips", []))
        corpus.wallets.extend(bundle.get("wallets", []))
        corpus.uses_edges.extend(bundle.get("uses_edges", []))

    log.info("Generating Scenario 1 (Digital Arrest Ring)...")
    _merge_bundle(generate_scenario_1())
    log.info("Generating Scenario 2 (Many Names, One Man)...")
    _merge_bundle(generate_scenario_2())
    log.info("Generating Scenario 3 (Follow the Money)...")
    _merge_bundle(generate_scenario_3())
    log.info("Generating Scenario 4 (The Surge)...")
    _merge_bundle(generate_scenario_4())
    log.info("Generating background FIRs...")
    _merge_bundle(generate_background())

    # Dedup dimension tables (critical for link survival through SQL round-trip)
    dedup_corpus(corpus)

    log.info(f"Entities: {len(corpus.firs)} FIRs, {len(corpus.persons)} persons, "
             f"{len(corpus.accounts)} accounts (deduped), "
             f"{len(corpus.devices)} devices, {len(corpus.upis)} upis, "
             f"{len(corpus.phones)} phones, {len(corpus.ips)} IPs, "
             f"{len(corpus.wallets)} wallets, "
             f"{len(corpus.transactions)} transactions")
    _save_pickle_artifact(CORPUS_ARTIFACT, corpus)
    _save_json_artifact(REGISTRY_ARTIFACT, reg.export_state())
    _save_json_artifact(KSP_SERIAL_ARTIFACT, km.export_serial_state())
    _write_checkpoint("entities", {"fir_count": len(corpus.firs)})
    return {"corpus": corpus}

# ---------------------------------------------------------------------------
# Stage 4: Historical document generation
# ---------------------------------------------------------------------------

def stage_historical_docs(args, corpus, fir_projections: Dict,
                           narrative_map: Dict[str,str]) -> Dict[str, Dict]:
    from .document_generator import generate_all_docs
    from .export import project_fir
    from .models import Person

    if not fir_projections:
        log.info("No FIR projections available yet; projecting lightweight case shells for docs stage...")
        person_map: Dict[str, Person] = {p.person_id: p for p in corpus.persons}
        rng = random.Random(args.seed)
        for fir in corpus.firs:
            year = int(fir.date_registered[:4]) if fir.date_registered else 2026
            fir_projections[fir.fir_id] = project_fir(fir, person_map, rng, year=year)

    log.info("Generating full FIR+IR documents for all historical cases...")
    out_hist = Path(args.output_dir) / "historical"
    fir_to_crimeno = generate_all_docs(
        corpus=corpus,
        fir_projections=fir_projections,
        narrative_map=narrative_map,
        output_dir=str(out_hist),
    )
    log.info(f"Documents written for {len(fir_to_crimeno)} cases")
    _save_pickle_artifact(PROJECTION_ARTIFACT, fir_projections)
    _save_json_artifact(REGISTRY_ARTIFACT, reg.export_state())
    _save_json_artifact(KSP_SERIAL_ARTIFACT, km.export_serial_state())
    _write_checkpoint(
        "historical_docs",
        {"case_count": len(fir_to_crimeno), "projections": len(fir_projections)},
    )
    return fir_projections

# ---------------------------------------------------------------------------
# Stage 5: Narrative generation (Bedrock)
# ---------------------------------------------------------------------------

def _station_display_name(station_id: str) -> str:
    from .reference_data import STATION_MAP
    ps = STATION_MAP.get(station_id)
    return ps.name if ps else station_id


def _build_narrative_prompt(fir, person_map: Dict[str, Any]) -> tuple[str, List[str]]:
    from .narrative_generator import (
        build_decoy_prompt,
        build_tier_a_digital_arrest_prompt,
        build_tier_a_task_scam_prompt,
        build_tier_b_digital_arrest_prompt,
        build_tier_c_prompt,
    )

    victim = person_map.get(fir.complainant_person_id)
    victim_name = victim.full_name if victim else "Complainant"
    age = victim.age if victim else 35
    address = victim.address if victim else fir.district
    occupation = victim.occupation if victim else "Private Employee"
    date = fir.date_of_offence or fir.date_registered
    amount_str = f"{fir.amount_involved:,}"
    station_name = _station_display_name(fir.police_station)
    transfer_time = "10:00"
    for ev in fir.sub_events:
        if "T" in ev.timestamp:
            transfer_time = ev.timestamp.split("T", 1)[1][:5]
            break

    ids = fir.identifiers_mentioned or {}
    accounts = ids.get("accounts", [])
    upis = ids.get("upis", [])
    phones = ids.get("phones", [])
    identifiers = [v for values in ids.values() for v in values if v]
    tier = fir.narrative_tier or "B"
    ct = fir.crime_type

    if tier == "A" and ct == "digital_arrest":
        beneficiary = accounts[0] if accounts else "UNKNOWN_ACCOUNT"
        prompt = build_tier_a_digital_arrest_prompt(
            victim_name=victim_name,
            age=age,
            address=address,
            district=fir.district,
            date=date,
            time=transfer_time,
            hours=24,
            amount=amount_str,
            num_transfers=max(1, len(accounts)),
            channel="UPI",
            beneficiary_account=beneficiary,
            realisation_trigger="the callers blocked all communication",
            police_station=station_name,
        )
        return prompt, identifiers + [beneficiary]

    if tier == "A" and ct == "task_scam":
        mule_account = accounts[0] if accounts else "UNKNOWN_ACCOUNT"
        upi_list = ", ".join(upis) if upis else "unknown@upi"
        phone_list = ", ".join(phones) if phones else "9876543210"
        prompt = build_tier_a_task_scam_prompt(
            victim_name=victim_name,
            age=age,
            occupation=occupation,
            district=fir.district,
            date=date,
            telegram_handle="@tasks_support",
            group_name="Daily Earning Tasks",
            app_name="TaskMaster Pro",
            initial_deposit="5,000",
            total_amount=amount_str,
            num_deposits=max(1, len(accounts) + len(upis)),
            upi_list=upi_list,
            mule_account=mule_account,
            phone_list=phone_list,
        )
        return prompt, identifiers + [mule_account]

    if tier == "B" and ct == "digital_arrest":
        beneficiary = accounts[0] if accounts else "UNKNOWN_ACCOUNT"
        prompt = build_tier_b_digital_arrest_prompt(
            victim_name=victim_name,
            age=age,
            occupation=occupation,
            district=fir.district,
            date=date,
            amount=amount_str,
            beneficiary_account=beneficiary,
        )
        return prompt, identifiers + [beneficiary]

    if tier == "decoy":
        decoy_account = accounts[0] if accounts else "UNKNOWN_ACCOUNT"
        prompt = build_decoy_prompt(
            victim_name=victim_name,
            district=fir.district,
            amount=amount_str,
            date=date,
            decoy_account=decoy_account,
        )
        return prompt, identifiers + [decoy_account]

    prompt = build_tier_c_prompt(
        crime_type=ct,
        victim_name=victim_name,
        age=age,
        occupation=occupation,
        district=fir.district,
        date=date,
        amount=amount_str,
        identifiers_str=", ".join(identifiers) if identifiers else "none",
    )
    return prompt, identifiers


def stage_narratives(args, corpus) -> Dict[str, str]:
    from .narrative_generator import generate_narrative, record_failure
    from dotenv import load_dotenv
    load_dotenv()

    log.info("Generating narratives via Bedrock (cached)...")
    narrative_map: Dict[str, str] = {}
    person_map = {p.person_id: p for p in corpus.persons}

    for fir in corpus.firs:
        tier = fir.narrative_tier or "B"
        try:
            prompt, required_identifiers = _build_narrative_prompt(fir, person_map)
            text = generate_narrative(
                prompt=prompt,
                cache_key=fir.fir_id,
                temperature=(
                    config.NARRATIVE_TEMPERATURE_TIER_A
                    if tier == "A"
                    else config.NARRATIVE_TEMPERATURE_TIER_B
                ),
                force=args.force_narratives,
                required_identifiers=required_identifiers or None,
            )
            narrative_map[fir.fir_id] = text
        except Exception as exc:
            record_failure(fir.fir_id, str(exc))
            if args.strict:
                raise
            log.warning("Narrative generation failed for %s; continuing (%s)", fir.fir_id, exc)

    log.info(f"Narratives generated: {len(narrative_map)}")
    _save_json_artifact(NARRATIVE_ARTIFACT, narrative_map)
    _save_json_artifact(REGISTRY_ARTIFACT, reg.export_state())
    _save_json_artifact(KSP_SERIAL_ARTIFACT, km.export_serial_state())
    _write_checkpoint("narratives", {"count": len(narrative_map)})
    return narrative_map

# ---------------------------------------------------------------------------
# Stage 6: SQL-CSV projection (historical only)
# ---------------------------------------------------------------------------

def stage_sql_csv(args, corpus, narrative_map: Dict[str, str],
                  fir_projections: Optional[Dict[str, Dict]] = None) -> Dict:
    from .export import write_masters, write_ksp_core_csvs, write_extension_csvs, project_fir
    from .export import reset_asa_counter
    from .legal_layer import reset_asa_counter as _rac
    from .document_generator import generate_all_docs
    from .models import Person
    import random as _rnd

    log.info("Projecting Corpus -> KSP-core + extension CSVs (historical)...")
    out = Path(args.output_dir) / "historical"

    reset_asa_counter()
    rng = _rnd.Random(args.seed)

    # project_fir needs a person_map
    person_map: Dict[str, Person] = {p.person_id: p for p in corpus.persons}

    fir_projections = fir_projections or {}
    if not fir_projections:
        for fir in corpus.firs:
            year = int(fir.date_registered[:4]) if fir.date_registered else 2026
            proj = project_fir(fir, person_map, rng, year=year)
            fir_projections[fir.fir_id] = proj

    for fir in corpus.firs:
        proj = fir_projections.get(fir.fir_id)
        if proj:
            proj["case_master"]["BriefFacts"] = narrative_map.get(fir.fir_id, "")

    write_masters(out)
    write_ksp_core_csvs(out, fir_projections)
    write_extension_csvs(out, corpus, fir_projections)
    # Refresh historical docs now that narratives are available.
    generate_all_docs(
        corpus=corpus,
        fir_projections=fir_projections,
        narrative_map=narrative_map,
        output_dir=str(out),
    )

    log.info(f"CSVs written for {len(fir_projections)} cases")
    _save_pickle_artifact(PROJECTION_ARTIFACT, fir_projections)
    _save_json_artifact(REGISTRY_ARTIFACT, reg.export_state())
    _save_json_artifact(KSP_SERIAL_ARTIFACT, km.export_serial_state())
    _write_checkpoint("sql_csv", {"fir_count": len(fir_projections)})
    return {"fir_projections": fir_projections}

# ---------------------------------------------------------------------------
# Stage 7: Load into SQLite
# ---------------------------------------------------------------------------

def stage_db_load(args) -> None:
    from .db_loader import build_db
    from .sql_schema import emit_schema

    out = Path(args.output_dir) / "historical"
    db_dir = out / "db"
    db_dir.mkdir(parents=True, exist_ok=True)

    # Emit schema.sql
    schema_path = emit_schema(str(db_dir / "schema.sql"))

    # Load CSVs
    build_db(
        sql_dir=str(out / "sql"),
        db_path=str(db_dir / "ksp.sqlite"),
        schema_path=schema_path,
    )
    _write_checkpoint("db_load")

# ---------------------------------------------------------------------------
# Stage 8: Graph from DB
# ---------------------------------------------------------------------------

def stage_graph_from_db(args) -> None:
    from .graph_builder import build_graph

    out = Path(args.output_dir) / "historical"
    db_path  = out / "db" / "ksp.sqlite"
    graph_dir = out / "graph"

    log.info(f"Building graph from {db_path}...")
    build_graph(str(db_path), str(graph_dir))
    _write_checkpoint("graph_from_db")

# ---------------------------------------------------------------------------
# Stage 9: Vector embedding (full docs)
# ---------------------------------------------------------------------------

def stage_vector_embed_docs(args, corpus, fir_projections: Dict,
                             narrative_map: Dict[str, str]) -> None:
    from .export import write_vector_jsonl

    out = Path(args.output_dir) / "historical"
    docs_root = out / "docs"

    log.info("Embedding full documents into vector JSONL...")
    write_vector_jsonl(
        base=out,
        corpus=corpus,
        fir_projections=fir_projections,
        narrative_map=narrative_map,
        docs_root=docs_root,
    )
    _write_checkpoint("vector_embed_docs")

# ---------------------------------------------------------------------------
# Stage 10: Live demo documents (held-back; NEVER loaded into DB)
# ---------------------------------------------------------------------------

def stage_live_docs(args, corpus, fir_projections: Dict) -> None:
    from .narrative_generator import NarrativeGenerator
    from .live_demo_generator import generate_all_live_docs
    from dotenv import load_dotenv
    load_dotenv()

    log.info("Generating live demo documents (held-back)...")
    gen = NarrativeGenerator(force=args.force_narratives, seed=args.seed)

    historical_crime_nos_by_scenario: Dict[str, List[str]] = {
        "SCN1": [], "SCN2": [], "SCN3": [], "SCN4": [],
    }
    for fir in corpus.firs:
        proj = fir_projections.get(fir.fir_id, {})
        cn = proj.get("crime_no","")
        if not cn:
            continue
        fid = fir.fir_id
        if "SCN1" in fid:   historical_crime_nos_by_scenario["SCN1"].append(cn)
        elif "SCN2" in fid: historical_crime_nos_by_scenario["SCN2"].append(cn)
        elif "SCN3" in fid: historical_crime_nos_by_scenario["SCN3"].append(cn)
        elif "SCN4" in fid: historical_crime_nos_by_scenario["SCN4"].append(cn)

    generate_all_live_docs(
        gen=gen,
        output_dir=args.output_dir,
        historical_crime_nos_by_scenario=historical_crime_nos_by_scenario,
    )
    # INVARIANT: nothing from live_demo/ is loaded into ksp.sqlite
    log.info("Live docs written. Verifying no live CrimeNos in DB...")
    _verify_live_separation(args)
    _write_checkpoint("live_docs")

def _verify_live_separation(args) -> None:
    """Quick check: reserved live CrimeNos must NOT appear in ksp.sqlite CaseMaster."""
    import sqlite3
    db_path = Path(args.output_dir) / "historical" / "db" / "ksp.sqlite"
    if not db_path.exists():
        return  # DB not yet built; check runs in validate
    live_reservations = reg.get_all_live_reservations()
    live_crime_nos = {v["crime_no"] for v in live_reservations.values()}
    if not live_crime_nos:
        return
    conn = sqlite3.connect(str(db_path))
    placeholders = ",".join("?" for _ in live_crime_nos)
    rows = conn.execute(
        f"SELECT CrimeNo FROM CaseMaster WHERE CrimeNo IN ({placeholders})",
        list(live_crime_nos)
    ).fetchall()
    conn.close()
    if rows:
        raise RuntimeError(
            f"Two-route separation violated! Live CrimeNos found in ksp.sqlite: "
            f"{[r[0] for r in rows]}"
        )
    log.info("Two-route separation OK: no live CrimeNos in ksp.sqlite")

# ---------------------------------------------------------------------------
# Stage 11: Evidence
# ---------------------------------------------------------------------------

def stage_evidence(args) -> None:
    if args.skip_evidence:
        log.info("Evidence stage skipped (--skip-evidence)")
        _write_checkpoint("evidence", {"skipped": True})
        return
    from .evidence_generator import generate_all_evidence
    log.info("Generating evidence artifacts...")
    generate_all_evidence(output_dir=args.output_dir)
    _write_checkpoint("evidence")

# ---------------------------------------------------------------------------
# Stage 12: Validate
# ---------------------------------------------------------------------------

def stage_validate(args) -> None:
    from .validate import run_validation
    log.info("Running all validation suites (A-I)...")
    result = run_validation(output_dir=args.output_dir, strict=args.strict)
    print(result.summary())
    _write_checkpoint("validate", {
        "errors": len(result.errors),
        "warnings": len(result.warnings),
        "passed": len(result.passed),
    })
    if not result.is_clean():
        if args.strict:
            raise RuntimeError("Validation failed (--strict mode)")
        log.warning("Validation completed with errors.")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="KSP Crime Intelligence Platform — Synthetic Dataset Generator"
    )
    parser.add_argument("--seed", type=int, default=config.RANDOM_SEED)
    parser.add_argument("--stages", type=str, default=None)
    parser.add_argument("--resume", dest="resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--restart", action="store_true",
                        help="Clear checkpoints/artifacts and run from scratch")
    parser.add_argument("--force-narratives", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--skip-evidence", action="store_true")
    parser.add_argument("--output-dir", default=config.OUTPUT_DIR)
    args = parser.parse_args()

    requested: Set[str] = set(args.stages.split(",")) if args.stages else set(ALL_STAGES)
    stages_to_run = [s for s in ALL_STAGES if s in requested]

    if args.restart:
        _clear_checkpoints()
        args.resume = False
        log.info("Restart requested: cleared checkpoint and artifact files.")

    log.info(f"Pipeline: {stages_to_run}")
    log.info(f"Seed={args.seed}, Output={args.output_dir}, Resume={args.resume}")

    start = time.time()
    corpus = _load_pickle_artifact(CORPUS_ARTIFACT) if args.resume else None
    narrative_map: Dict[str, str] = (
        _load_json_artifact(NARRATIVE_ARTIFACT, default={}) if args.resume else {}
    )
    fir_projections: Dict = (
        _load_pickle_artifact(PROJECTION_ARTIFACT) if args.resume else {}
    ) or {}
    if args.resume:
        reg_state = _load_json_artifact(REGISTRY_ARTIFACT, default={}) or {}
        if reg_state:
            reg.import_state(reg_state)
        serial_state = _load_json_artifact(KSP_SERIAL_ARTIFACT, default={}) or {}
        if serial_state:
            km.import_serial_state(serial_state)

    for stage in stages_to_run:
        if args.resume and _is_checkpointed(stage):
            log.info(f"Stage '{stage}': checkpointed, skipping")
            if stage == "entities" and corpus is None:
                corpus = _load_pickle_artifact(CORPUS_ARTIFACT)
            elif stage == "narratives" and not narrative_map:
                narrative_map = _load_json_artifact(NARRATIVE_ARTIFACT, default={})
            elif stage in {"historical_docs", "sql_csv"} and not fir_projections:
                fir_projections = _load_pickle_artifact(PROJECTION_ARTIFACT) or {}
            reg_state = _load_json_artifact(REGISTRY_ARTIFACT, default={}) or {}
            if reg_state:
                reg.import_state(reg_state)
            serial_state = _load_json_artifact(KSP_SERIAL_ARTIFACT, default={}) or {}
            if serial_state:
                km.import_serial_state(serial_state)
            continue

        log.info(f"=== Stage: {stage} ===")
        t0 = time.time()
        try:
            if stage == "preflight":
                stage_preflight(args)
            elif stage == "reference":
                stage_reference(args)
            elif stage == "entities":
                result = stage_entities(args)
                corpus = result["corpus"]
            elif stage == "historical_docs":
                if corpus is None:
                    corpus = _load_pickle_artifact(CORPUS_ARTIFACT)
                if corpus is None:
                    raise RuntimeError("Need 'entities' before 'historical_docs'")
                fir_projections = stage_historical_docs(args, corpus, fir_projections, narrative_map)
            elif stage == "narratives":
                if corpus is None:
                    corpus = _load_pickle_artifact(CORPUS_ARTIFACT)
                if corpus is None:
                    raise RuntimeError("Need 'entities' before 'narratives'")
                narrative_map = stage_narratives(args, corpus)
            elif stage == "sql_csv":
                if corpus is None:
                    corpus = _load_pickle_artifact(CORPUS_ARTIFACT)
                if corpus is None:
                    raise RuntimeError("Need 'entities' before 'sql_csv'")
                if args.resume and not fir_projections:
                    fir_projections = _load_pickle_artifact(PROJECTION_ARTIFACT) or {}
                if args.resume and not narrative_map:
                    narrative_map = _load_json_artifact(NARRATIVE_ARTIFACT, default={})
                result = stage_sql_csv(args, corpus, narrative_map, fir_projections=fir_projections)
                fir_projections = result["fir_projections"]
            elif stage == "db_load":
                stage_db_load(args)
            elif stage == "graph_from_db":
                stage_graph_from_db(args)
            elif stage == "vector_embed_docs":
                if corpus is None:
                    corpus = _load_pickle_artifact(CORPUS_ARTIFACT)
                if corpus is None:
                    raise RuntimeError("Need 'entities' before 'vector_embed_docs'")
                if args.resume and not fir_projections:
                    fir_projections = _load_pickle_artifact(PROJECTION_ARTIFACT) or {}
                if args.resume and not narrative_map:
                    narrative_map = _load_json_artifact(NARRATIVE_ARTIFACT, default={})
                stage_vector_embed_docs(args, corpus, fir_projections, narrative_map)
            elif stage == "live_docs":
                if corpus is None:
                    corpus = _load_pickle_artifact(CORPUS_ARTIFACT)
                if corpus is None:
                    raise RuntimeError("Need 'entities' before 'live_docs'")
                if args.resume and not fir_projections:
                    fir_projections = _load_pickle_artifact(PROJECTION_ARTIFACT) or {}
                stage_live_docs(args, corpus, fir_projections)
            elif stage == "evidence":
                stage_evidence(args)
            elif stage == "validate":
                stage_validate(args)
        except Exception as exc:
            log.error(f"Stage '{stage}' FAILED: {exc}", exc_info=True)
            _record_failure(stage, str(exc), traceback.format_exc())
            raise

        log.info(f"Stage '{stage}' done in {time.time()-t0:.1f}s")

    log.info(f"Pipeline complete in {time.time()-start:.1f}s")
    _print_summary(args, stages_to_run)


def _record_failure(stage: str, error: str, trace: str = "") -> None:
    failures_file = Path(config.FAILURES_FILE)
    failures: List[Dict[str, Any]] = []
    if failures_file.exists():
        try:
            loaded = json.loads(failures_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                failures = loaded
            elif isinstance(loaded, dict):
                # Backward compatibility: narrative_generator persisted a dict map.
                for k, v in loaded.items():
                    failures.append({
                        "stage": "narrative",
                        "error": f"{k}: {v}",
                        "traceback": "",
                        "ts": time.time(),
                    })
        except Exception:
            pass
    failures.append({"stage": stage, "error": error, "traceback": trace, "ts": time.time()})
    failures_file.write_text(json.dumps(failures, indent=2), encoding="utf-8")


def _print_summary(args, stages: List[str]) -> None:
    print("\n" + "="*60)
    print("KSP SYNTHETIC DATA GENERATOR — RUN SUMMARY")
    print("="*60)
    print(f"Seed={args.seed}  Output={args.output_dir}")
    for stage in stages:
        cp = _checkpoint_path(stage)
        status = "[OK]" if cp.exists() else "[--]"
        data = ""
        if cp.exists():
            try:
                d = json.loads(cp.read_text()).get("data",{})
                data = str(d)[:60]
            except: pass
        print(f"  {status} {stage:22s}  {data}")
    print("="*60)


if __name__ == "__main__":
    main()
