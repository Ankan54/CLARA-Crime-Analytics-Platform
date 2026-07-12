"""
reference_data.py — Karnataka districts (lat/long/pincodes), banks, police stations, crime types.
All geographic data is real; police station names are plausible composites for synthetic use.
district_id and unit_id are 4-digit KSP INT PKs matching ksp_master.py.
"""
from __future__ import annotations
from .models import District, PoliceStation, Bank, CrimeType

# ---------------------------------------------------------------------------
# 31 Karnataka Districts with centroid coordinates and sample pincodes
# ---------------------------------------------------------------------------
DISTRICTS: list[District] = [
    District("Bengaluru Urban",  12.9716,  77.5946, ["560001","560002","560003","560011","560034","560070","560100"], district_id=2901),
    District("Bengaluru Rural",  13.1000,  77.5700, ["562101","562110","562112","562114","562123"], district_id=2902),
    District("Mysuru",           12.2958,  76.6394, ["570001","570002","570008","570010","570017"], district_id=2903),
    District("Mangaluru",        12.9141,  74.8560, ["575001","575002","575004","575006","575014"], district_id=2904),
    District("Hubballi-Dharwad", 15.3647,  75.1240, ["580001","580021","580024","580029","580031"], district_id=2905),
    District("Belagavi",         15.8497,  74.4977, ["590001","590006","590009","590010","590011"], district_id=2906),
    District("Kalaburagi",       17.3297,  76.8343, ["585101","585102","585103","585104","585105"], district_id=2907),
    District("Ballari",          15.1394,  76.9214, ["583101","583102","583103","583104","583105"], district_id=2908),
    District("Shivamogga",       13.9299,  75.5681, ["577201","577202","577203","577204","577205"], district_id=2909),
    District("Davanagere",       14.4644,  75.9218, ["577001","577002","577003","577004","577005"], district_id=2910),
    District("Tumakuru",         13.3409,  77.1010, ["572101","572102","572103","572104","572105"], district_id=2911),
    District("Raichur",          16.2120,  77.3439, ["584101","584102","584103","584104","584105"], district_id=2912),
    District("Vijayapura",       16.8302,  75.7100, ["586101","586102","586103","586104","586105"], district_id=2913),
    District("Hassan",           13.0033,  76.1004, ["573201","573202","573203","573204","573205"], district_id=2914),
    District("Udupi",            13.3409,  74.7421, ["576101","576102","576103","576104","576105"], district_id=2915),
    District("Kodagu",           12.3375,  75.8069, ["571201","571212","571213","571214","571215"], district_id=2916),
    District("Chikkamagaluru",   13.3161,  75.7720, ["577101","577102","577103","577104","577105"], district_id=2917),
    District("Uttara Kannada",   14.7862,  74.6949, ["581201","581330","581335","581340","581341"], district_id=2918),
    District("Dharwad",          15.4589,  75.0078, ["580001","580002","580003","580004","580007"], district_id=2919),
    District("Gadag",            15.4298,  75.6270, ["582101","582102","582103","582110","582111"], district_id=2920),
    District("Koppal",           15.3520,  76.1551, ["583231","583232","583233","583234","583235"], district_id=2921),
    District("Yadgir",           16.7730,  77.1333, ["585201","585202","585211","585212","585213"], district_id=2922),
    District("Bidar",            17.9104,  77.5199, ["585401","585402","585403","585404","585412"], district_id=2923),
    District("Chamarajanagara",  11.9266,  77.1743, ["571313","571314","571315","571316","571317"], district_id=2924),
    District("Mandya",           12.5218,  76.8951, ["571401","571402","571403","571404","571405"], district_id=2925),
    District("Chikkaballapur",   13.4355,  77.7315, ["562101","562102","562103","562104","562105"], district_id=2926),
    District("Kolar",            13.1363,  78.1294, ["563101","563102","563103","563104","563105"], district_id=2927),
    District("Ramanagara",       12.7157,  77.2817, ["562159","562160","562161","562162","562163"], district_id=2928),
    District("Chitradurga",      14.2318,  76.3979, ["577501","577502","577503","577504","577505"], district_id=2929),
    District("Bagalkot",         16.1826,  75.6966, ["587101","587102","587103","587111","587112"], district_id=2930),
    District("Vijayanagara",     15.1688,  76.4600, ["583123","583124","583125","583126","583127"], district_id=2931),
]

DISTRICT_MAP: dict[str, District] = {d.name: d for d in DISTRICTS}

# Districts that are scenario-anchored — don't use for background noise contamination
SCENARIO_DISTRICTS = {"Mysuru", "Mangaluru", "Hubballi-Dharwad", "Bengaluru Urban",
                       "Belagavi", "Dharwad", "Tumakuru"}

# ---------------------------------------------------------------------------
# Police Stations (cyber / CEN cells)
# ---------------------------------------------------------------------------
POLICE_STATIONS: list[PoliceStation] = [
    # Bengaluru Urban — Cyber & CEN stations (district_id=2901)
    PoliceStation("PS_BLR_CEN_01",   "CEN Police Station - East Division",       "Bengaluru Urban",  "CEN",   unit_id=1001, district_id=2901),
    PoliceStation("PS_BLR_CEN_02",   "CEN Police Station - West Division",       "Bengaluru Urban",  "CEN",   unit_id=1002, district_id=2901),
    PoliceStation("PS_BLR_CEN_03",   "CEN Police Station - South Division",      "Bengaluru Urban",  "CEN",   unit_id=1003, district_id=2901),
    PoliceStation("PS_BLR_CEN_04",   "CEN Police Station - North Division",      "Bengaluru Urban",  "CEN",   unit_id=1004, district_id=2901),
    PoliceStation("PS_BLR_CYBER_01", "Whitefield Cyber Crime Police Station",    "Bengaluru Urban",  "cyber", unit_id=1005, district_id=2901),
    PoliceStation("PS_BLR_CYBER_02", "Electronic City Cyber Crime Station",      "Bengaluru Urban",  "cyber", unit_id=1006, district_id=2901),
    PoliceStation("PS_BLR_CYBER_03", "Koramangala Cyber Crime Station",          "Bengaluru Urban",  "cyber", unit_id=1007, district_id=2901),
    PoliceStation("PS_BLR_CYBER_04", "HSR Layout Cyber Crime Station",           "Bengaluru Urban",  "cyber", unit_id=1008, district_id=2901),
    # Mysuru (district_id=2903)
    PoliceStation("PS_MYS_01",       "Mysuru CEN Police Station",                "Mysuru",           "CEN",   unit_id=1009, district_id=2903),
    PoliceStation("PS_MYS_02",       "Chamundipuram Police Station",             "Mysuru",           "general",unit_id=1010, district_id=2903),
    PoliceStation("PS_MYS_03",       "Devaraja Police Station",                  "Mysuru",           "general",unit_id=1011, district_id=2903),
    # Mangaluru (district_id=2904)
    PoliceStation("PS_MNG_01",       "Mangaluru Cyber Crime Police Station",     "Mangaluru",        "cyber", unit_id=1012, district_id=2904),
    PoliceStation("PS_MNG_02",       "Bunder Police Station",                    "Mangaluru",        "general",unit_id=1013, district_id=2904),
    # Hubballi-Dharwad (district_id=2905)
    PoliceStation("PS_HUB_01",       "Hubballi CEN Police Station",              "Hubballi-Dharwad", "CEN",   unit_id=1014, district_id=2905),
    PoliceStation("PS_HUB_02",       "Navanagar Police Station",                 "Hubballi-Dharwad", "general",unit_id=1015, district_id=2905),
    # Belagavi (district_id=2906)
    PoliceStation("PS_BLG_01",       "Belagavi CEN Police Station",              "Belagavi",         "CEN",   unit_id=1016, district_id=2906),
    PoliceStation("PS_BLG_02",       "Tilakwadi Police Station",                 "Belagavi",         "general",unit_id=1017, district_id=2906),
    # Dharwad (district_id=2919)
    PoliceStation("PS_DWD_01",       "Dharwad Cyber Crime Police Station",       "Dharwad",          "cyber", unit_id=1018, district_id=2919),
    # Tumakuru (district_id=2911)
    PoliceStation("PS_TUM_01",       "Tumakuru CEN Police Station",              "Tumakuru",         "CEN",   unit_id=1019, district_id=2911),
    PoliceStation("PS_TUM_02",       "SS Puram Police Station",                  "Tumakuru",         "general",unit_id=1020, district_id=2911),
    # Others
    PoliceStation("PS_KLG_01",       "Kalaburagi CEN Police Station",            "Kalaburagi",       "CEN",   unit_id=1021, district_id=2907),
    PoliceStation("PS_RCR_01",       "Raichur Cyber Crime Station",              "Raichur",          "cyber", unit_id=1022, district_id=2912),
    PoliceStation("PS_SHI_01",       "Shivamogga CEN Police Station",            "Shivamogga",       "CEN",   unit_id=1023, district_id=2909),
    PoliceStation("PS_DAV_01",       "Davanagere Cyber Crime Station",           "Davanagere",       "cyber", unit_id=1024, district_id=2910),
    PoliceStation("PS_HAS_01",       "Hassan CEN Police Station",                "Hassan",           "CEN",   unit_id=1025, district_id=2914),
    PoliceStation("PS_UDU_01",       "Udupi CEN Police Station",                 "Udupi",            "CEN",   unit_id=1026, district_id=2915),
    PoliceStation("PS_BAL_01",       "Ballari CEN Police Station",               "Ballari",          "CEN",   unit_id=1027, district_id=2908),
    PoliceStation("PS_VJP_01",       "Vijayapura CEN Police Station",            "Vijayapura",       "CEN",   unit_id=1028, district_id=2913),
    PoliceStation("PS_KOL_01",       "Kolar CEN Police Station",                 "Kolar",            "CEN",   unit_id=1029, district_id=2927),
    PoliceStation("PS_CHK_01",       "Chikkaballapur CEN Police Station",        "Chikkaballapur",   "CEN",   unit_id=1030, district_id=2926),
]

STATION_MAP: dict[str, PoliceStation] = {ps.station_id: ps for ps in POLICE_STATIONS}

STATIONS_BY_DISTRICT: dict[str, list[PoliceStation]] = {}
for _ps in POLICE_STATIONS:
    STATIONS_BY_DISTRICT.setdefault(_ps.district, []).append(_ps)

# ---------------------------------------------------------------------------
# Banks (realistic Karnataka-present banks with valid IFSC prefixes)
# ---------------------------------------------------------------------------
BANKS: list[Bank] = [
    Bank("State Bank of India",         "SBIN"),
    Bank("Canara Bank",                 "CNRB"),
    Bank("Bank of Baroda",              "BARB"),
    Bank("Union Bank of India",         "UBIN"),
    Bank("HDFC Bank",                   "HDFC"),
    Bank("ICICI Bank",                  "ICIC"),
    Bank("Axis Bank",                   "UTIB"),
    Bank("Kotak Mahindra Bank",         "KKBK"),
    Bank("Yes Bank",                    "YESB"),
    Bank("IndusInd Bank",               "INDB"),
    Bank("Karnataka Bank",              "KTKM"),
    Bank("Vijaya Bank",                 "VIJB"),    # merged into BoB but IFSC still in use
    Bank("Corporation Bank",            "CORP"),    # merged into UBI but legacy codes exist
    Bank("Syndicate Bank",              "SYNB"),    # merged into Canara
    Bank("Airtel Payments Bank",        "AIRP"),
    Bank("Paytm Payments Bank",         "PYTM"),
    Bank("India Post Payments Bank",    "IPOS"),
    Bank("Fino Payments Bank",          "FINO"),
]

BANK_MAP: dict[str, Bank] = {b.name: b for b in BANKS}

# ---------------------------------------------------------------------------
# Crime Types
# ---------------------------------------------------------------------------
CRIME_TYPES: list[CrimeType] = [
    CrimeType("digital_arrest",    "Digital Arrest / Fake Official Threat"),
    CrimeType("investment_scam",   "Fake Investment / Stock Market Fraud"),
    CrimeType("task_scam",         "Online Task / Job Scam"),
    CrimeType("upi_fraud",         "UPI Payment Fraud"),
    CrimeType("otp_fraud",         "OTP Theft / SIM Swap Fraud"),
    CrimeType("loan_app",          "Predatory Loan App Fraud"),
    CrimeType("job_scam",          "Fake Job / Placement Fraud"),
    CrimeType("sextortion",        "Sextortion / Honey Trap"),
    CrimeType("phishing",          "Phishing / Vishing / Fake Bank"),
    CrimeType("mule_account",      "Mule Account / Money Mule Recruitment"),
]

CRIME_TYPE_MAP: dict[str, CrimeType] = {ct.code: ct for ct in CRIME_TYPES}

# ---------------------------------------------------------------------------
# IO Officer names (Karnataka / South-Indian)
# ---------------------------------------------------------------------------
IO_OFFICERS = [
    "PI Venkatesh Kumar",
    "PI Priya Shankar",
    "PI Manjunath Gowda",
    "PI Savitha Nagaraj",
    "PI Ravi Krishnamurthy",
    "PI Anand Hegde",
    "PI Deepa Kamath",
    "PI Suresh Patil",
    "PI Girish Rao",
    "PI Kavitha Reddy",
    "PI Basavaraj Gudadinni",
    "PI Nirmala Shetty",
]
