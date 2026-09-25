import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import gradio as gr
import pandas as pd
import plotly.graph_objects as go
import requests


# ============================================================
# SAMRAKSHA KENDRA
# Digital Disease Surveillance & Early Warning System
# ============================================================

API_URL = "http://127.0.0.1:8000"
PORT = 7860

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GEOJSON_FILE = DATA_DIR / "india_states.geojson"
COMMUNITY_REPORTS_FILE = DATA_DIR / "community_reports.json"
COMMUNITY_EVIDENCE_DIR = DATA_DIR / "community_evidence"
COMMUNITY_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# Community reports are persisted locally for this prototype so they survive
# dashboard restarts without requiring a PostgreSQL schema change yet.
COMMUNITY_REPORT_FIELDS = [
    "report_id",
    "submitted_at",
    "reporter_name",
    "contact",
    "state",
    "district",
    "report_type",
    "disease_or_symptoms",
    "people_affected",
    "severity",
    "description",
    "evidence",
    "status",
    "source",
]


# Real India state/UT boundary GeoJSON used for the map.
GEOJSON_URL = (
    "https://raw.githubusercontent.com/"
    "india-in-data/india-states-2019/"
    "master/india_states.geojson"
)

# Official WHO Disease Outbreak News API.
WHO_DON_API = "https://www.who.int/api/news/diseaseoutbreaknews"
WHO_DON_PAGE = "https://www.who.int/emergencies/disease-outbreak-news"


# ============================================================
# STATE NAME NORMALIZATION
# ============================================================

STATE_ALIASES = {
    "Jammu & Kashmir": "Jammu and Kashmir",
    "Jammu and Kashmir": "Jammu and Kashmir",
    "Orissa": "Odisha",
    "Uttaranchal": "Uttarakhand",
    "Pondicherry": "Puducherry",
    "NCT of Delhi": "Delhi",
}


def normalize_state(name):
    if name is None:
        return ""

    value = str(name).strip()
    return STATE_ALIASES.get(value, value)


# ============================================================
# API HELPERS
# ============================================================

def api_get(endpoint, params=None):
    try:
        response = requests.get(
            f"{API_URL}{endpoint}",
            params=params,
            timeout=15,
        )

        if response.status_code != 200:
            print(
                f"[API ERROR {response.status_code}] {endpoint}"
            )
            return None

        return response.json()

    except requests.RequestException as error:
        print(f"[API CONNECTION ERROR] {endpoint}: {error}")
        return None

    except Exception as error:
        print(f"[API ERROR] {endpoint}: {error}")
        return None


def safe_int(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def format_number(value):
    return f"{safe_int(value):,}"


# ============================================================
# BACKEND DATA
# ============================================================

def get_stats():
    hospitals_data = api_get("/hospitals/count")
    diseases_data = api_get("/diseases/count")
    records_data = api_get("/idsp/count")
    cases_data = api_get("/idsp/cases")
    deaths_data = api_get("/idsp/deaths")
    idsp_diseases_data = api_get("/idsp/disease-count")

    hospitals = (
        safe_int(hospitals_data.get("count"))
        if hospitals_data else 0
    )

    if diseases_data:
        diseases = safe_int(diseases_data.get("count"))
    elif idsp_diseases_data:
        diseases = safe_int(idsp_diseases_data.get("count"))
    else:
        diseases = 0

    records = (
        safe_int(records_data.get("count"))
        if records_data else 0
    )

    cases = (
        safe_int(cases_data.get("total_cases"))
        if cases_data else 0
    )

    deaths = (
        safe_int(deaths_data.get("total_deaths"))
        if deaths_data else 0
    )

    return {
        "hospitals": hospitals,
        "diseases": diseases,
        "records": records,
        "cases": cases,
        "deaths": deaths,
    }


def get_all_records():
    data = api_get(
        "/idsp/records",
        params={"limit": 500},
    )

    return data if isinstance(data, list) else []


def get_latest():
    data = api_get("/idsp/latest")

    if not isinstance(data, list):
        return []

    return [
        [
            item.get("date"),
            item.get("disease"),
            item.get("state"),
            item.get("district"),
            safe_int(item.get("cases")),
            safe_int(item.get("deaths")),
            item.get("status"),
        ]
        for item in data
    ]


def get_disease_summary():
    data = api_get("/idsp/summary")

    if not isinstance(data, list):
        return []

    return [
        [
            item.get("disease"),
            safe_int(item.get("cases")),
            safe_int(item.get("deaths")),
            safe_int(item.get("records")),
        ]
        for item in data
    ]


def get_state_summary():
    data = api_get("/idsp/state-summary")

    if not isinstance(data, list):
        return []

    return [
        [
            item.get("state"),
            safe_int(item.get("cases")),
            safe_int(item.get("deaths")),
            safe_int(item.get("records")),
        ]
        for item in data
    ]


# ============================================================
# COMMUNITY REPORTS
# ============================================================

def load_community_reports():
    try:
        if not COMMUNITY_REPORTS_FILE.exists():
            return []
        data = json.loads(COMMUNITY_REPORTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as error:
        print(f"[COMMUNITY REPORTS LOAD ERROR] {error}")
        return []


def save_community_reports(reports):
    COMMUNITY_REPORTS_FILE.write_text(
        json.dumps(reports, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def community_report_rows():
    reports = load_community_reports()
    return [
        [
            r.get("report_id", ""),
            r.get("submitted_at", ""),
            r.get("reporter_name", "Anonymous"),
            r.get("state", ""),
            r.get("district", ""),
            r.get("report_type", ""),
            r.get("disease_or_symptoms", ""),
            safe_int(r.get("people_affected")),
            r.get("severity", ""),
            f"{len(r.get('evidence', []))} image(s)" if r.get("evidence") else "No image",
            r.get("status", "Pending Review"),
        ]
        for r in reversed(reports)
    ]


def community_evidence_gallery():
    reports = load_community_reports()
    items = []

    for report in reversed(reports):
        report_id = report.get("report_id", "Community Report")
        for evidence in report.get("evidence", []):
            saved_path = evidence.get("saved_path", "") if isinstance(evidence, dict) else str(evidence)
            original_name = evidence.get("original_name", "Evidence") if isinstance(evidence, dict) else Path(saved_path).name
            path = Path(saved_path)
            if path.exists():
                items.append((str(path), f"{report_id} — {original_name}"))

    return items[:30]


def save_community_evidence(report_id, evidence_files):
    saved = []

    if not evidence_files:
        return saved

    if not isinstance(evidence_files, (list, tuple)):
        evidence_files = [evidence_files]

    allowed_extensions = {".jpg", ".jpeg", ".png", ".webp"}

    for source in list(evidence_files)[:5]:
        try:
            source_path = Path(str(source))
            if not source_path.exists():
                continue

            extension = source_path.suffix.lower()
            if extension not in allowed_extensions:
                continue

            unique_name = f"{report_id}_{uuid.uuid4().hex[:8]}{extension}"
            destination = COMMUNITY_EVIDENCE_DIR / unique_name
            shutil.copy2(source_path, destination)

            saved.append({
                "original_name": source_path.name,
                "saved_path": str(destination),
            })
        except Exception as error:
            print(f"[COMMUNITY EVIDENCE ERROR] {error}")

    return saved


def submit_community_report(
    reporter_name,
    contact,
    state,
    district,
    report_type,
    disease_or_symptoms,
    people_affected,
    severity,
    description,
    evidence_files,
    anonymous,
):
    state = str(state or "").strip()
    district = str(district or "").strip()
    report_type = str(report_type or "").strip()
    disease_or_symptoms = str(disease_or_symptoms or "").strip()
    description = str(description or "").strip()
    contact = str(contact or "").strip()

    if not state or not district or not report_type or not disease_or_symptoms or not description:
        return (
            "❌ Please fill State, District, Report Type, Disease/Symptoms and Description.",
            community_report_rows(),
            community_evidence_gallery(),
        )

    affected = safe_int(people_affected)
    if affected < 1:
        affected = 1

    reports = load_community_reports()

    # Avoid reusing an existing ID if reports were manually deleted.
    existing_numbers = []
    for report in reports:
        report_id = str(report.get("report_id", ""))
        if report_id.startswith("CR-"):
            try:
                existing_numbers.append(int(report_id.split("-", 1)[1]))
            except (IndexError, ValueError):
                pass

    report_number = max(existing_numbers, default=0) + 1
    report_id = f"CR-{report_number:04d}"

    submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    evidence = save_community_evidence(report_id, evidence_files)

    report = {
        "report_id": report_id,
        "submitted_at": submitted_at,
        "reporter_name": "Anonymous" if anonymous else (str(reporter_name or "").strip() or "Community User"),
        "contact": contact,
        "state": state,
        "district": district,
        "report_type": report_type,
        "disease_or_symptoms": disease_or_symptoms,
        "people_affected": affected,
        "severity": str(severity or "Moderate").strip(),
        "description": description,
        "evidence": evidence,
        "status": "Pending Review",
        "source": "Community",
    }

    reports.append(report)
    save_community_reports(reports)

    print(f"Community report submitted: {report_id} | evidence={len(evidence)}")

    evidence_message = (
        f" {len(evidence)} evidence image(s) attached."
        if evidence else
        " No evidence image attached."
    )

    return (
        f"✅ Community report **{report_id}** submitted successfully. Status: **Pending Review**.{evidence_message}",
        community_report_rows(),
        community_evidence_gallery(),
    )


def clear_community_form():
    return ("", "", "", "", "", "", 1, "Moderate", "", None, False, "")


# ============================================================
# SEARCH
# ============================================================

def search_records(
    disease="",
    state="",
    district="",
    week=None,
    year=None,
    limit=100,
):
    params = {}

    if disease:
        params["disease"] = str(disease).strip()

    if state:
        params["state"] = str(state).strip()

    if district:
        params["district"] = str(district).strip()

    if week not in (None, ""):
        try:
            params["week"] = int(float(week))
        except (TypeError, ValueError):
            pass

    if year not in (None, ""):
        try:
            params["year"] = int(float(year))
        except (TypeError, ValueError):
            pass

    try:
        params["limit"] = max(1, min(500, int(float(limit))))
    except (TypeError, ValueError):
        params["limit"] = 100

    data = api_get(
        "/idsp/records",
        params=params,
    )

    if not isinstance(data, list):
        return []

    return [
        [
            item.get("record_id"),
            item.get("year"),
            item.get("week"),
            item.get("reporting_start_date"),
            item.get("reporting_end_date"),
            item.get("state"),
            item.get("district"),
            item.get("disease"),
            safe_int(item.get("cases")),
            safe_int(item.get("deaths")),
            item.get("outbreak_status"),
            item.get("source"),
            item.get("source_url"),
        ]
        for item in data
    ]


# ============================================================
# EARLY WARNING
# ============================================================

def calculate_risk(cases, deaths):
    cases = safe_int(cases)
    deaths = safe_int(deaths)

    # These thresholds are project-defined demonstrations.
    # They are NOT official IDSP thresholds.
    if deaths >= 2:
        return (
            "HIGH",
            f"Deaths reported ({deaths})",
            "Immediate attention recommended",
        )

    if cases >= 100:
        return (
            "HIGH",
            f"High reported cases ({cases})",
            "Immediate attention recommended",
        )

    if cases >= 50:
        return (
            "MODERATE",
            f"Elevated reported cases ({cases})",
            "Increased surveillance recommended",
        )

    if cases >= 10:
        return (
            "WATCH",
            f"Cases require monitoring ({cases})",
            "Continue monitoring",
        )

    return (
        "LOW",
        f"Low reported activity ({cases})",
        "Routine surveillance",
    )


def get_alerts():
    records = get_all_records()
    alerts = []

    for record in records:
        cases = safe_int(record.get("cases"))
        deaths = safe_int(record.get("deaths"))

        risk, reason, action = calculate_risk(
            cases,
            deaths,
        )

        if risk == "LOW":
            continue

        alerts.append(
            [
                record.get("reporting_end_date"),
                record.get("disease"),
                record.get("state"),
                record.get("district"),
                cases,
                deaths,
                risk,
                reason,
                action,
            ]
        )

    priority = {
        "HIGH": 0,
        "MODERATE": 1,
        "WATCH": 2,
    }

    alerts.sort(
        key=lambda row: (
            priority.get(row[6], 99),
            -safe_int(row[4]),
            -safe_int(row[5]),
        )
    )

    return alerts


# ============================================================
# REAL INDIA GEOJSON
# ============================================================

def load_india_geojson():
    # Try a fresh download first. This avoids reusing a malformed
    # map file from an earlier version of the application.
    try:
        response = requests.get(
            GEOJSON_URL,
            timeout=60,
        )
        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):
            raise ValueError("GeoJSON root is not an object.")

        features = data.get("features", [])

        if not features:
            raise ValueError("GeoJSON contains no features.")

        with open(
            GEOJSON_FILE,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(data, file)

        print(
            f"Downloaded India GeoJSON: {len(features)} features"
        )

        return data

    except Exception as download_error:
        print(
            "Could not download India GeoJSON:",
            download_error,
        )

    # If download fails, use a previously cached valid file.
    if GEOJSON_FILE.exists():
        try:
            with open(
                GEOJSON_FILE,
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)

            if (
                isinstance(data, dict)
                and data.get("features")
            ):
                print("Using cached India GeoJSON.")
                return data

        except Exception as cache_error:
            print(
                "Cached GeoJSON is invalid:",
                cache_error,
            )

    return None


def prepare_geojson(geojson):
    if not geojson:
        return None

    for feature in geojson.get("features", []):
        properties = feature.setdefault(
            "properties",
            {},
        )

        state_name = (
            properties.get("ST_NM")
            or properties.get("State_Name")
            or properties.get("NAME_1")
            or properties.get("name")
        )

        if state_name:
            properties["map_name"] = normalize_state(
                state_name
            )

    return geojson


# ============================================================
# REAL INDIA CHOROPLETH MAP
# ============================================================

def create_real_india_map():
    geojson = load_india_geojson()

    if not geojson:
        return map_message(
            "India boundary map could not be loaded."
        )

    geojson = prepare_geojson(geojson)

    states = get_state_summary()

    if not states:
        return map_message(
            "State surveillance data is unavailable."
        )

    rows = []

    for row in states:
        rows.append(
            {
                "state": normalize_state(row[0]),
                "cases": safe_int(row[1]),
                "deaths": safe_int(row[2]),
                "records": safe_int(row[3]),
            }
        )

    risk_priority = {
        "LOW": 0,
        "WATCH": 1,
        "MODERATE": 2,
        "HIGH": 3,
    }

    for row in rows:
        risk, reason, action = calculate_risk(
            row["cases"],
            row["deaths"],
        )

        row["risk"] = risk
        row["reason"] = reason
        row["action"] = action
        row["risk_code"] = risk_priority[risk]

    # Add normalized map_name properties to every geometry.
    geo_names = set()

    for feature in geojson.get("features", []):
        name = feature.get(
            "properties",
            {},
        ).get("map_name")

        if name:
            geo_names.add(name)

    matched_rows = [
        row
        for row in rows
        if row["state"] in geo_names
    ]

    print(
        f"Map: {len(matched_rows)} surveillance states matched "
        f"to {len(geo_names)} GeoJSON states"
    )

    if not matched_rows:
        return map_message(
            "The surveillance state names did not match the map boundaries."
        )

    map_df = pd.DataFrame(matched_rows)

    map_df["hover"] = map_df.apply(
        lambda row: (
            f"<b>{row['state']}</b>"
            f"<br>Reported cases: {row['cases']:,}"
            f"<br>Deaths: {row['deaths']:,}"
            f"<br>Surveillance records: {row['records']:,}"
            f"<br>Risk level: <b>{row['risk']}</b>"
            f"<br>Signal: {row['reason']}"
        ),
        axis=1,
    )

    fig = go.Figure(
        go.Choropleth(
            geojson=geojson,
            featureidkey="properties.map_name",
            locations=map_df["state"],
            z=map_df["risk_code"],
            text=map_df["hover"],
            hovertemplate="%{text}<extra></extra>",
            zmin=0,
            zmax=3,
            colorscale=[
                [0.00, "#22c55e"],
                [0.249, "#22c55e"],
                [0.25, "#facc15"],
                [0.499, "#facc15"],
                [0.50, "#f97316"],
                [0.749, "#f97316"],
                [0.75, "#ef4444"],
                [1.00, "#ef4444"],
            ],
            showscale=False,
            marker_line_color="#ffffff",
            marker_line_width=1.2,
        )
    )

    # Add a small legend as annotations so it is always visible.
    fig.add_annotation(
        x=0.02,
        y=0.035,
        xref="paper",
        yref="paper",
        text=(
            "🔴 HIGH &nbsp;&nbsp; "
            "🟠 MODERATE &nbsp;&nbsp; "
            "🟡 WATCH &nbsp;&nbsp; "
            "🟢 LOW"
        ),
        showarrow=False,
        bgcolor="white",
        bordercolor="#d1d5db",
        borderwidth=1,
        borderpad=8,
        font=dict(
            size=11,
            color="#334155",
        ),
    )

    fig.update_geos(
        visible=False,
        fitbounds="geojson",
        projection_type="mercator",
        showland=True,
        landcolor="#edf4e8",
        showocean=True,
        oceancolor="#dceef8",
        showcountries=True,
        countrycolor="#64748b",
        countrywidth=0.8,
        showcoastlines=True,
        coastlinecolor="#64748b",
        coastlinewidth=0.8,
        bgcolor="white",
    )

    fig.update_layout(
        title=dict(
            text="India Disease Surveillance Map",
            x=0.02,
            xanchor="left",
            font=dict(
                size=20,
                color="#173a62",
            ),
        ),
        height=600,
        margin=dict(
            l=0,
            r=0,
            t=55,
            b=0,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        dragmode="pan",
    )

    return fig


def map_message(message):
    fig = go.Figure()

    fig.add_annotation(
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        text=(
            "<b>🗺️ Disease Surveillance Map</b>"
            f"<br><br>{message}"
        ),
        showarrow=False,
        font=dict(
            size=16,
            color="#475569",
        ),
        align="center",
    )

    fig.update_layout(
        height=600,
        margin=dict(
            l=0,
            r=0,
            t=20,
            b=0,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis=dict(
            visible=False,
        ),
        yaxis=dict(
            visible=False,
        ),
    )

    return fig


# ============================================================
# ANALYTICS CHARTS
# ============================================================

def create_disease_chart():
    data = get_disease_summary()

    if not data:
        return None

    df = pd.DataFrame(
        data,
        columns=[
            "disease",
            "cases",
            "deaths",
            "records",
        ],
    )

    df = df.sort_values(
        "cases",
        ascending=False,
    ).head(10)

    fig = go.Figure(
        go.Bar(
            x=df["cases"],
            y=df["disease"],
            orientation="h",
            text=df["cases"],
            textposition="outside",
            hovertemplate=(
                "<b>%{y}</b>"
                "<br>Cases: %{x:,}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title="Top Diseases by Reported Cases",
        height=420,
        margin=dict(
            l=15,
            r=35,
            t=55,
            b=35,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis_title="Reported Cases",
        yaxis_title="",
    )

    return fig


def create_state_chart():
    data = get_state_summary()

    if not data:
        return None

    df = pd.DataFrame(
        data,
        columns=[
            "state",
            "cases",
            "deaths",
            "records",
        ],
    )

    df = df.sort_values(
        "cases",
        ascending=False,
    ).head(10)

    fig = go.Figure(
        go.Bar(
            x=df["state"],
            y=df["cases"],
            text=df["cases"],
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b>"
                "<br>Cases: %{y:,}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title="Top States by Reported Cases",
        height=420,
        margin=dict(
            l=20,
            r=20,
            t=55,
            b=110,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis_title="State",
        yaxis_title="Reported Cases",
    )

    fig.update_xaxes(
        tickangle=-40
    )

    return fig


def create_disease_donut():
    data = get_disease_summary()

    if not data:
        return None

    df = pd.DataFrame(
        data,
        columns=[
            "disease",
            "cases",
            "deaths",
            "records",
        ],
    )

    df = df.sort_values(
        "cases",
        ascending=False,
    )

    top = df.head(5).copy()
    others = df.iloc[5:]["cases"].sum()

    if others > 0:
        top = pd.concat(
            [
                top,
                pd.DataFrame(
                    [
                        {
                            "disease": "Others",
                            "cases": others,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    fig = go.Figure(
        go.Pie(
            labels=top["disease"],
            values=top["cases"],
            hole=0.55,
            hovertemplate=(
                "<b>%{label}</b>"
                "<br>Cases: %{value:,}"
                "<br>%{percent}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title="Cases by Disease",
        height=420,
        margin=dict(
            l=5,
            r=5,
            t=55,
            b=5,
        ),
        paper_bgcolor="white",
    )

    return fig


def create_disease_trend():
    records = get_all_records()

    if not records:
        return None

    rows = []

    for record in records:
        date = record.get(
            "reporting_end_date"
        )
        disease = record.get(
            "disease"
        )
        cases = safe_int(
            record.get("cases")
        )

        if date and disease:
            rows.append(
                {
                    "date": date,
                    "disease": disease,
                    "cases": cases,
                }
            )

    if not rows:
        return None

    df = pd.DataFrame(rows)

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce",
    )

    df = df.dropna(
        subset=["date"]
    )

    if df.empty:
        return None

    top_diseases = (
        df.groupby("disease")["cases"]
        .sum()
        .sort_values(ascending=False)
        .head(4)
        .index
        .tolist()
    )

    df = df[
        df["disease"].isin(top_diseases)
    ]

    grouped = (
        df.groupby(
            ["date", "disease"]
        )["cases"]
        .sum()
        .reset_index()
    )

    fig = go.Figure()

    for disease_name in top_diseases:
        subset = grouped[
            grouped["disease"] == disease_name
        ].sort_values("date")

        fig.add_trace(
            go.Scatter(
                x=subset["date"],
                y=subset["cases"],
                mode="lines+markers",
                name=disease_name,
                hovertemplate=(
                    "<b>"
                    + disease_name
                    + "</b>"
                    + "<br>%{x|%d %b %Y}"
                    + "<br>Cases: %{y:,}"
                    + "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        title="Disease Trend",
        height=420,
        margin=dict(
            l=35,
            r=20,
            t=55,
            b=35,
        ),
        paper_bgcolor="white",
        plot_bgcolor="white",
        xaxis_title="Reporting End Date",
        yaxis_title="Reported Cases",
        legend=dict(
            orientation="h",
            y=1.10,
        ),
    )

    return fig


# ============================================================
# DASHBOARD LOAD
# ============================================================

def load_dashboard():
    print()
    print("Loading Samraksha Kendra dashboard...")

    stats = get_stats()
    alerts = get_alerts()
    latest = get_latest()
    diseases = get_disease_summary()
    states = get_state_summary()

    disease_donut_fig = create_disease_donut()
    disease_trend_fig = create_disease_trend()
    state_fig = create_state_chart()
    map_fig = create_real_india_map()

    print(
        f"Hospitals: {stats['hospitals']:,}"
    )
    print(
        f"Diseases: {stats['diseases']:,}"
    )
    print(
        f"IDSP records: {stats['records']:,}"
    )
    print(
        f"Cases: {stats['cases']:,}"
    )
    print(
        f"Deaths: {stats['deaths']:,}"
    )
    print(
        f"Alerts: {len(alerts):,}"
    )

    return (
        f"""
        <div class="metric-card blue">
            <div class="metric-title">🏥 Total Hospitals</div>
            <div class="metric-number">
                {format_number(stats['hospitals'])}
            </div>
            <div class="metric-note">
                Imported hospital data
            </div>
        </div>
        """,
        f"""
        <div class="metric-card green">
            <div class="metric-title">🦠 Total Diseases</div>
            <div class="metric-number">
                {format_number(stats['diseases'])}
            </div>
            <div class="metric-note">
                Disease database
            </div>
        </div>
        """,
        f"""
        <div class="metric-card orange">
            <div class="metric-title">📋 Surveillance Records</div>
            <div class="metric-number">
                {format_number(stats['records'])}
            </div>
            <div class="metric-note">
                Official IDSP records
            </div>
        </div>
        """,
        f"""
        <div class="metric-card red">
            <div class="metric-title">🚨 Active Alerts</div>
            <div class="metric-number">
                {format_number(len(alerts))}
            </div>
            <div class="metric-note">
                Requires attention
            </div>
        </div>
        """,
        f"""
        <div class="small-stat">
            <span>Total Reported Cases</span>
            <strong>{format_number(stats['cases'])}</strong>
        </div>
        """,
        f"""
        <div class="small-stat">
            <span>Total Reported Deaths</span>
            <strong>{format_number(stats['deaths'])}</strong>
        </div>
        """,
        alerts,
        disease_donut_fig,
        disease_trend_fig,
        state_fig,
        map_fig,
        latest,
        diseases,
        states,
    )


# ============================================================
# WHO DISEASE OUTBREAK NEWS
# ============================================================

def clean_html_text(value):
    """Convert simple HTML returned by WHO into readable plain text."""
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_who_publication_date(value):
    """Parse a WHO publication date safely without pandas datetime parsing."""
    if value is None:
        return "-", datetime(1900, 1, 1, tzinfo=timezone.utc)

    raw = str(value).strip()
    if not raw:
        return "-", datetime(1900, 1, 1, tzinfo=timezone.utc)

    # Most WHO responses begin with an ISO date (YYYY-MM-DD).
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        try:
            year, month, day = map(int, match.groups())
            parsed = datetime(year, month, day, tzinfo=timezone.utc)
            return parsed.strftime("%d %b %Y"), parsed
        except ValueError:
            pass

    # Handle common slash/dot date forms as a fallback.
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(raw[:10], fmt).replace(tzinfo=timezone.utc)
            return parsed.strftime("%d %b %Y"), parsed
        except (ValueError, TypeError):
            continue

    return "-", datetime(1900, 1, 1, tzinfo=timezone.utc)


def fetch_who_disease_outbreak_news(limit=12):
    """Fetch recent WHO Disease Outbreak News records.

    WHO exposes the collection in pages of records and provides an
    @odata.nextLink value for pagination. The collection is not ordered
    newest-first, so the function follows the pagination links, then sorts
    the retrieved records by publication date before showing the newest
    notices. This avoids treating the first API page as the latest news.
    """
    try:
        next_url = WHO_DON_API
        all_items = []
        seen_next_urls = set()
        page_count = 0
        max_pages = 25

        while next_url and page_count < max_pages:
            if next_url in seen_next_urls:
                break
            seen_next_urls.add(next_url)
            page_count += 1

            response = requests.get(
                next_url,
                timeout=20,
                headers={
                    "User-Agent": "Samraksha-Kendra/1.0",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()

            payload = response.json()

            if not isinstance(payload, dict):
                break

            page_items = payload.get("value", [])
            if isinstance(page_items, list):
                all_items.extend(page_items)

            next_url = payload.get("@odata.nextLink") or payload.get("odata.nextLink")

            if next_url and next_url.startswith("http://"):
                next_url = "https://" + next_url[len("http://"):]

        # Keep records distinct by WHO item ID / DON ID.
        unique_items = {}
        for item in all_items:
            item_id = (
                item.get("Id")
                or item.get("DonId")
                or item.get("UrlName")
                or str(item)
            )
            unique_items[str(item_id)] = item

        rows = []

        for item in unique_items.values():
            title = (
                item.get("Title")
                or item.get("OverrideTitle")
                or "WHO Disease Outbreak News"
            )

            publication = (
                item.get("PublicationDateAndTime")
                or item.get("PublicationDate")
                or ""
            )

            overview = clean_html_text(
                item.get("Summary")
                or item.get("Overview")
                or item.get("Assessment")
                or ""
            )

            if len(overview) > 320:
                overview = overview[:317] + "..."

            don_id = item.get("DonId") or "-"
            url_name = str(item.get("UrlName") or "").strip()

            # WHO may return different date representations.  Avoid
            # pandas datetime parsing here because malformed/very large
            # values from an API response can be unexpectedly expensive.
            date_text, sort_value = parse_who_publication_date(publication)

            if url_name:
                source = (
                    "https://www.who.int/emergencies/"
                    f"disease-outbreak-news/item/{url_name}"
                )
            else:
                source = WHO_DON_PAGE

            rows.append({
                "sort": sort_value,
                "Date": date_text,
                "WHO Outbreak Notice": str(title).strip(),
                "DON ID": str(don_id).strip(),
                "Summary": (
                    overview
                    if overview
                    else "No summary available in the WHO API response."
                ),
                "Source": source,
            })

        rows.sort(
            key=lambda row: row["sort"],
            reverse=True,
        )

        result = [
            [
                row["Date"],
                row["WHO Outbreak Notice"],
                row["DON ID"],
                row["Summary"],
                row["Source"],
            ]
            for row in rows[:limit]
        ]

        print(
            f"WHO Disease Outbreak News loaded: {len(result)} recent records "
            f"from {len(all_items)} API records across {page_count} page(s)."
        )

        if result:
            return result

        return [[
            "-",
            "No WHO Disease Outbreak News records found",
            "-",
            "The WHO API returned no outbreak notices.",
            WHO_DON_PAGE,
        ]]

    except requests.RequestException as exc:
        print(
            "WHO Disease Outbreak News request error:",
            exc,
        )
        return [[
            "-",
            "Unable to retrieve WHO Disease Outbreak News",
            "-",
            f"Request error: {exc}",
            WHO_DON_PAGE,
        ]]

    except Exception as exc:
        print(
            "WHO Disease Outbreak News processing error:",
            exc,
        )
        return [[
            "-",
            "Unable to process WHO Disease Outbreak News",
            "-",
            f"{type(exc).__name__}: {exc}",
            WHO_DON_PAGE,
        ]]


# ============================================================
# HTML HEADER / SIDEBAR
# ============================================================

HEADER_BRAND_HTML = """
<div class="brand-link-wrap">
    <a class="brand-link" href="#dashboard-section">
        <div class="logo-box">🛡️</div>
        <div>
            <div class="brand-name">Samraksha Kendra</div>
            <div class="brand-subtitle">Disease Surveillance & Early Warning System</div>
        </div>
    </a>
</div>
"""


SIDEBAR_HTML = """
<div class="sidebar">

    <div class="sidebar-title">
        🛡️ Samraksha Kendra
    </div>

    <a class="sidebar-item active" href="#dashboard-section">🏠 Dashboard</a>
    <a class="sidebar-item" href="#hospitals-section">🏥 Hospitals</a>
    <a class="sidebar-item" href="#diseases-section">🦠 Diseases</a>
    <a class="sidebar-item" href="#records-section">📋 Surveillance Records</a>
    <a class="sidebar-item" href="#alerts-section">🚨 Alerts</a>
    <a class="sidebar-item" href="#map-section">🗺️ Map View</a>
    <a class="sidebar-item" href="#analytics-section">📊 Analytics</a>
    <a class="sidebar-item" href="#reports-section">📄 Reports</a>
    <a class="sidebar-item" href="#community-reports-section">🧑‍🤝‍🧑 Community Reports</a>
    <a class="sidebar-item" href="#who-section">🌍 Global Outbreak Intelligence</a>
    <a class="sidebar-item" href="#settings-section">⚙️ Settings</a>

    <div class="sidebar-footer">
        🛡️ <b>Samraksha Kendra</b>
        <br><br>
        Healthier Communities
        <br>
        Safer Tomorrow
    </div>

</div>
"""


# Demo/local authentication used by this dashboard prototype.
AUTH_USERNAME = "admin"
AUTH_PASSWORD = "admin123"


def authenticate(username, password):
    username = str(username or "").strip()
    password = str(password or "")

    if username == AUTH_USERNAME and password == AUTH_PASSWORD:
        return (
            gr.update(visible=False),
            gr.update(visible=True),
            "",
        )

    return (
        gr.update(visible=True),
        gr.update(visible=False),
        "Invalid username or password.",
    )


def logout_user():
    return (
        gr.update(visible=True),
        gr.update(visible=False),
        "You have been logged out.",
        False,
        gr.update(visible=False),
    )


# ============================================================
# CSS
# ============================================================

CUSTOM_CSS = """
/* ============================================================
   GLOBAL PAGE
   ============================================================ */

:root {
    --body-text-color: #dbeafe !important;
    --body-text-color-subdued: #b9c9da !important;
    --block-label-text-color: #475569 !important;
    --block-title-text-color: #102a43 !important;
    --block-description-text-color: #64748b !important;
    --input-text-color: #102a43 !important;
}

body {
    background: #07111f !important;
    color: #dbeafe !important;
}

.gradio-container {
    max-width: 1500px !important;
    margin: 0 auto !important;
    padding: 0 18px 30px !important;
    color: #dbeafe !important;
}

/* ============================================================
   NORMAL PAGE MARKDOWN
   The main dashboard sits on a dark background, so normal
   Markdown must use light text.
   ============================================================ */

.gradio-container .prose,
.gradio-container .gr-markdown,
.gradio-container .markdown {
    opacity: 1 !important;
}

.gradio-container .prose h1,
.gradio-container .prose h2,
.gradio-container .prose h3,
.gradio-container .prose h4,
.gradio-container .prose h5,
.gradio-container .prose h6,
.gradio-container .gr-markdown h1,
.gradio-container .gr-markdown h2,
.gradio-container .gr-markdown h3,
.gradio-container .gr-markdown h4,
.gradio-container .gr-markdown h5,
.gradio-container .gr-markdown h6 {
    color: #e8f1fb !important;
    opacity: 1 !important;
}

.gradio-container .prose p,
.gradio-container .prose li,
.gradio-container .prose span,
.gradio-container .prose strong,
.gradio-container .gr-markdown p,
.gradio-container .gr-markdown li,
.gradio-container .gr-markdown span,
.gradio-container .gr-markdown strong {
    color: #b9c9da !important;
    opacity: 1 !important;
}

/* ============================================================
   WHITE SECTION CARDS
   Markdown inside white cards must be dark.
   ============================================================ */

.section-card {
    background: white !important;
    border: 1px solid #dce6f0;
    border-radius: 14px;
    padding: 13px;
    box-shadow: 0 3px 12px rgba(15,35,60,.06);
    color: #102a43 !important;
}

.section-card .prose,
.section-card .gr-markdown,
.section-card .markdown,
.section-card .prose * ,
.section-card .gr-markdown * ,
.section-card .markdown * {
    color: #102a43 !important;
    opacity: 1 !important;
}

.section-card .prose p,
.section-card .prose li,
.section-card .prose span,
.section-card .prose strong,
.section-card .gr-markdown p,
.section-card .gr-markdown li,
.section-card .gr-markdown span,
.section-card .gr-markdown strong {
    color: #334e68 !important;
}

.section-card .prose h1,
.section-card .prose h2,
.section-card .prose h3,
.section-card .prose h4,
.section-card .prose h5,
.section-card .prose h6,
.section-card .gr-markdown h1,
.section-card .gr-markdown h2,
.section-card .gr-markdown h3,
.section-card .gr-markdown h4,
.section-card .gr-markdown h5,
.section-card .gr-markdown h6 {
    color: #102a43 !important;
}

/* ============================================================
   DATA SOURCE / DARK BACKGROUND INFO
   ============================================================ */

.data-source-section {
    color: #dbeafe !important;
    padding: 8px 4px 20px !important;
    opacity: 1 !important;
}

.data-source-section .prose,
.data-source-section .gr-markdown,
.data-source-section .markdown,
.data-source-section * {
    color: #dbeafe !important;
    opacity: 1 !important;
}

.data-source-section p,
.data-source-section li,
.data-source-section span {
    color: #b9c9da !important;
}

.data-source-section strong {
    color: #e8f1fb !important;
}

.data-source-section h1,
.data-source-section h2,
.data-source-section h3 {
    color: #e8f1fb !important;
}

/* ============================================================
   HEADER
   ============================================================ */

.top-header {
    background: linear-gradient(100deg, #09294d, #174f88);
    color: white !important;
    padding: 16px 24px;
    border-radius: 0 0 15px 15px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 18px;
    box-shadow: 0 5px 18px rgba(7,39,74,.20);
}

.top-header * {
    color: white !important;
}

.brand-row {
    display: flex;
    align-items: center;
    gap: 13px;
}

.logo-box {
    width: 48px;
    height: 48px;
    border-radius: 13px;
    background: #1976d2;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 25px;
}

.brand-name {
    font-size: 24px;
    font-weight: 800;
}

.brand-subtitle {
    color: #d8e7f7 !important;
    font-size: 11px;
}

.top-user {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 13px;
}

.notification {
    background: #ef4444;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
}

.avatar {
    width: 35px;
    height: 35px;
    border-radius: 50%;
    background: #2382eb;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-weight: 800;
}

/* ============================================================
   SIDEBAR
   ============================================================ */

.sidebar {
    min-height: 980px;
    border-radius: 14px;
    background: linear-gradient(180deg, #071f3a, #07182c);
    color: #d9e6f2 !important;
    padding: 15px 11px;
    position: relative;
}

.sidebar * {
    color: #d9e6f2 !important;
}

.sidebar-title {
    color: white !important;
    font-size: 16px;
    font-weight: 800;
    padding: 10px 9px 19px;
}

.sidebar-item {
    display: block;
    box-sizing: border-box;
    padding: 11px 10px;
    border-radius: 8px;
    margin: 4px 0;
    font-size: 13px;
    color: #d9e6f2 !important;
    text-decoration: none !important;
    cursor: pointer;
    transition: background .18s ease, color .18s ease;
}

.sidebar-item:hover {
    background: rgba(20,95,196,.35);
    color: white !important;
}

.sidebar-item.active {
    background: #145fc4;
    color: white !important;
}

.sidebar-item.active * {
    color: white !important;
}

.sidebar-footer {
    position: absolute;
    bottom: 20px;
    left: 15px;
    right: 15px;
    color: #9eb5cc !important;
    font-size: 10px;
    line-height: 1.45;
}

/* ============================================================
   KPI CARDS
   ============================================================ */

.metric-card {
    background: white !important;
    min-height: 110px;
    border-radius: 14px;
    padding: 17px;
    border: 1px solid #dce6f0;
    box-shadow: 0 4px 14px rgba(15,35,60,.07);
    border-top: 4px solid;
    color: #102a43 !important;
}

.metric-card * {
    color: inherit !important;
}

.metric-card.blue {
    border-top-color: #2563eb;
}

.metric-card.green {
    border-top-color: #16a34a;
}

.metric-card.orange {
    border-top-color: #f59e0b;
}

.metric-card.red {
    border-top-color: #ef4444;
}

.metric-title {
    color: #64748b !important;
    font-size: 13px;
    font-weight: 700;
}

.metric-number {
    color: #102a43 !important;
    font-size: 29px;
    font-weight: 800;
    margin-top: 6px;
}

.metric-note {
    color: #94a3b8 !important;
    font-size: 10px;
    margin-top: 4px;
}

.small-stat {
    background: white !important;
    border: 1px solid #dce6f0;
    border-radius: 12px;
    padding: 12px 16px;
    box-shadow: 0 3px 10px rgba(15,35,60,.06);
}

.small-stat span {
    display: block;
    color: #64748b !important;
    font-size: 12px;
}

.small-stat strong {
    display: block;
    color: #102a43 !important;
    font-size: 22px;
    margin-top: 4px;
}

/* ============================================================
   PLOTLY
   ============================================================ */

.gradio-container .plot-container {
    background: white !important;
}

/* ============================================================
   DATAFRAMES
   ============================================================ */

.gradio-container .dataframe {
    color: #102a43 !important;
}

.gradio-container .dataframe table {
    color: #102a43 !important;
}

.gradio-container .dataframe th {
    color: #102a43 !important;
    background: #eef4fa !important;
}

.gradio-container .dataframe td {
    color: #102a43 !important;
    background: white !important;
}

/* ============================================================
   BUTTONS / DIVIDERS / FOOTER
   ============================================================ */

button.primary {
    border-radius: 9px !important;
}

.gradio-container hr {
    border-color: #334155 !important;
}

.nav-anchor {
    height: 1px !important;
    width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
}

html {
    scroll-behavior: smooth;
}

/* ============================================================
   CLICKABLE HEADER / PROFILE MENU
   ============================================================ */

.header-row {
    position: relative !important;
    background: linear-gradient(100deg, #09294d, #174f88) !important;
    border-radius: 0 0 15px 15px !important;
    margin-bottom: 18px !important;
    padding: 0 14px 0 20px !important;
    min-height: 78px !important;
    box-shadow: 0 5px 18px rgba(7,39,74,.20);
}

.header-brand {
    min-width: 0 !important;
}

.brand-link-wrap {
    display: flex;
    align-items: center;
    height: 78px;
}

.brand-link {
    display: flex;
    align-items: center;
    gap: 13px;
    text-decoration: none !important;
}

.brand-link * {
    text-decoration: none !important;
}

.header-actions {
    justify-content: flex-end !important;
    align-items: center !important;
    gap: 7px !important;
}

.header-actions button {
    border: 0 !important;
    box-shadow: none !important;
}

.header-notify-btn {
    min-width: 48px !important;
    width: 48px !important;
    padding: 0 !important;
    background: transparent !important;
    color: white !important;
}

.header-admin-btn {
    min-width: 130px !important;
    background: rgba(255,255,255,.10) !important;
    color: white !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
}

.header-admin-btn:hover,
.header-notify-btn:hover {
    background: rgba(255,255,255,.18) !important;
}

.profile-menu {
    position: absolute !important;
    z-index: 1000 !important;
    top: 70px !important;
    right: 18px !important;
    width: 230px !important;
    background: white !important;
    border: 1px solid #dbe5ef !important;
    border-radius: 12px !important;
    padding: 14px !important;
    box-shadow: 0 12px 30px rgba(2, 24, 48, .20) !important;
}

.profile-menu .prose,
.profile-menu .gr-markdown,
.profile-menu .prose *,
.profile-menu .gr-markdown * {
    color: #102a43 !important;
}

.profile-menu button {
    background: #ef4444 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
}

/* ============================================================
   COMMUNITY REPORTS
   ============================================================ */

.community-card {
    background: white !important;
    border: 1px solid #dce6f0 !important;
    border-radius: 14px !important;
    padding: 16px !important;
    box-shadow: 0 3px 12px rgba(15,35,60,.06) !important;
    color: #102a43 !important;
}

.community-card .prose,
.community-card .gr-markdown,
.community-card .prose *,
.community-card .gr-markdown * {
    color: #102a43 !important;
    opacity: 1 !important;
}

.community-help {
    background: #eef6ff !important;
    border-left: 4px solid #2563eb !important;
    border-radius: 8px !important;
    padding: 10px 12px !important;
    color: #334e68 !important;
    font-size: 12px !important;
}

.community-success {
    color: #166534 !important;
    font-weight: 700 !important;
}

.evidence-note {
    color: #64748b !important;
    font-size: 12px !important;
}

.community-card .gallery-item {
    border-radius: 10px !important;
    border: 1px solid #dce6f0 !important;
}

/* ============================================================
   WHO OUTBREAK NEWS
   ============================================================ */

.who-card {
    background: white !important;
    border: 1px solid #dce6f0 !important;
    border-radius: 14px !important;
    padding: 16px !important;
    box-shadow: 0 3px 12px rgba(15,35,60,.06) !important;
    color: #102a43 !important;
}

.who-card .prose,
.who-card .gr-markdown,
.who-card .prose *,
.who-card .gr-markdown * {
    color: #102a43 !important;
    opacity: 1 !important;
}

.who-source-note {
    color: #64748b !important;
    font-size: 12px !important;
    line-height: 1.5 !important;
}

.who-source-note a {
    color: #1769d1 !important;
    font-weight: 700 !important;
}

/* ============================================================
   AUTHENTICATION PAGE
   ============================================================ */

.auth-page {
    min-height: 88vh !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 30px !important;
}

.auth-card {
    max-width: 430px !important;
    width: 100% !important;
    background: white !important;
    border: 1px solid #dbe5ef !important;
    border-radius: 18px !important;
    padding: 28px !important;
    box-shadow: 0 15px 45px rgba(2,24,48,.18) !important;
}

.auth-card .prose,
.auth-card .gr-markdown,
.auth-card .prose *,
.auth-card .gr-markdown * {
    color: #102a43 !important;
}

.auth-title {
    text-align: center !important;
}

.auth-message {
    color: #dc2626 !important;
    font-size: 13px !important;
}

.auth-hint {
    text-align: center !important;
    color: #64748b !important;
    font-size: 12px !important;
}

footer {
    display: none !important;
}
"""


# ============================================================
# UI
# ============================================================

with gr.Blocks(
    title="Samraksha Kendra"
) as demo:

    # ========================================================
    # AUTHENTICATION PAGE
    # ========================================================

    with gr.Column(visible=False, elem_classes=["auth-page"]) as login_panel:
        with gr.Column(elem_classes=["auth-card"]):
            gr.Markdown(
                "## 🛡️ Samraksha Kendra",
                elem_classes=["auth-title"],
            )

            gr.Markdown(
                "### Administrator Login",
                elem_classes=["auth-title"],
            )

            login_username = gr.Textbox(
                label="Username",
                placeholder="Enter username",
            )

            login_password = gr.Textbox(
                label="Password",
                type="password",
                placeholder="Enter password",
            )

            login_button = gr.Button(
                "🔐 Login",
                variant="primary",
            )

            login_message = gr.Markdown(
                "",
                elem_classes=["auth-message"],
            )

            gr.Markdown(
                "Prototype login: admin / admin123",
                elem_classes=["auth-hint"],
            )

    # Dashboard is visible on first launch; Logout returns to the auth page.
    with gr.Column(visible=True, elem_classes=["dashboard-shell"]) as dashboard_panel:

        # ----------------------------------------------------
        # CLICKABLE HEADER
        # ----------------------------------------------------

        with gr.Row(elem_classes=["header-row"]):
            with gr.Column(scale=7, elem_classes=["header-brand"]):
                gr.HTML(HEADER_BRAND_HTML)

            with gr.Row(scale=3, elem_classes=["header-actions"]):
                header_notification = gr.Button(
                    "🔔 3",
                    elem_classes=["header-notify-btn"],
                )

                admin_button = gr.Button(
                    "👤 AK  Admin ▾",
                    elem_classes=["header-admin-btn"],
                )

        with gr.Column(visible=False, elem_classes=["profile-menu"]) as profile_menu:
            gr.Markdown(
                "### 👤 Admin\n\nAdministrator account\n\nSamraksha Kendra"
            )
            logout_button = gr.Button(
                "🚪 Logout",
                variant="stop",
            )

        with gr.Row():

            # ====================================================
            # SIDEBAR
            # ====================================================

            with gr.Column(
                scale=1,
                min_width=185
            ):

                gr.HTML(
                    SIDEBAR_HTML
                )

            # ====================================================
            # MAIN
            # ====================================================

            with gr.Column(
                scale=6
            ):

                gr.HTML('<div id="dashboard-section" class="nav-anchor"></div>')

                gr.Markdown(
                    """
                    # Welcome, Admin

                    Here's what's happening with disease surveillance
                    across India.
                    """
                )

                # ------------------------------------------------
                # KPI ROW
                # ------------------------------------------------

                gr.HTML('<div id="hospitals-section" class="nav-anchor"></div>')

                with gr.Row():

                    total_hospitals = gr.HTML(
                        """
                        <div class="metric-card blue">
                            <div class="metric-title">🏥 Total Hospitals</div>
                            <div class="metric-number">Loading...</div>
                            <div class="metric-note">Imported hospital data</div>
                        </div>
                        """
                    )

                    total_diseases = gr.HTML(
                        """
                        <div class="metric-card green">
                            <div class="metric-title">🦠 Total Diseases</div>
                            <div class="metric-number">Loading...</div>
                            <div class="metric-note">Disease database</div>
                        </div>
                        """
                    )

                    total_records = gr.HTML(
                        """
                        <div class="metric-card orange">
                            <div class="metric-title">📋 Surveillance Records</div>
                            <div class="metric-number">Loading...</div>
                            <div class="metric-note">Official IDSP records</div>
                        </div>
                        """
                    )

                    total_alerts = gr.HTML(
                        """
                        <div class="metric-card red">
                            <div class="metric-title">🚨 Active Alerts</div>
                            <div class="metric-number">Loading...</div>
                            <div class="metric-note">Requires attention</div>
                        </div>
                        """
                    )

                # ------------------------------------------------
                # CASE / DEATH MINI CARDS
                # ------------------------------------------------

                with gr.Row():

                    total_cases = gr.HTML(
                        """
                        <div class="small-stat">
                            <span>Total Reported Cases</span>
                            <strong>Loading...</strong>
                        </div>
                        """
                    )

                    total_deaths = gr.HTML(
                        """
                        <div class="small-stat">
                            <span>Total Reported Deaths</span>
                            <strong>Loading...</strong>
                        </div>
                        """
                    )

                refresh_dashboard = gr.Button(
                    "🔄 Refresh Complete Dashboard",
                    variant="primary"
                )

                # ------------------------------------------------
                # REAL MAP + ANALYTICS
                # ------------------------------------------------

                gr.HTML('<div id="map-section" class="nav-anchor"></div>')
                gr.HTML('<div id="diseases-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                with gr.Row():

                    with gr.Column(
                        scale=6,
                        elem_classes=["section-card"]
                    ):

                        gr.Markdown(
                            """
                            ## 🗺️ Disease Hotspots Map

                            Real India state and Union Territory boundaries
                            with IDSP surveillance data overlaid.

                            **🔴 HIGH &nbsp;&nbsp; 🟠 MODERATE &nbsp;&nbsp;
                            🟡 WATCH &nbsp;&nbsp; 🟢 LOW**

                            Hover over a state to view cases, deaths,
                            surveillance records and risk level.
                            """
                        )

                        map_plot = gr.Plot(
                            value=create_real_india_map(),
                            show_label=False,
                        )

                    with gr.Column(
                        scale=4
                    ):

                        with gr.Column(
                            elem_classes=["section-card"]
                        ):

                            gr.Markdown(
                                "## 📈 Disease Trend"
                            )

                            disease_trend_plot = gr.Plot(
                                value=create_disease_trend(),
                                show_label=False,
                            )

                        with gr.Column(
                            elem_classes=["section-card"]
                        ):

                            gr.Markdown(
                                "## 🥧 Cases by Disease"
                            )

                            disease_donut_plot = gr.Plot(
                                value=create_disease_donut(),
                                show_label=False,
                            )

                # ------------------------------------------------
                # ALERTS
                # ------------------------------------------------

                gr.HTML('<div id="alerts-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                gr.Markdown(
                    """
                    ## 🚨 Early Warning System

                    Alerts are generated using **project-defined
                    demonstration thresholds** based on reported cases
                    and deaths. These are not official IDSP thresholds.
                    """
                )

                alert_table = gr.Dataframe(
                    headers=[
                        "Date",
                        "Disease",
                        "State",
                        "District",
                        "Cases",
                        "Deaths",
                        "Risk Level",
                        "Alert Reason",
                        "Recommended Action",
                    ],
                    datatype=[
                        "str",
                        "str",
                        "str",
                        "str",
                        "number",
                        "number",
                        "str",
                        "str",
                        "str",
                    ],
                    interactive=False,
                    wrap=True,
                )

                # ------------------------------------------------
                # STATE ANALYTICS
                # ------------------------------------------------

                gr.HTML('<div id="analytics-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                gr.Markdown(
                    """
                    ## 🗺️ State Analytics

                    States with the highest reported surveillance cases.
                    """
                )

                state_plot = gr.Plot(
                    value=create_state_chart(),
                    show_label=False,
                )

                # ------------------------------------------------
                # LATEST ACTIVITY
                # ------------------------------------------------

                gr.HTML('<div id="reports-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                gr.Markdown(
                    """
                    ## 📰 Latest Disease Activity

                    Most recent surveillance records reported by district.
                    """
                )

                latest_table = gr.Dataframe(
                    headers=[
                        "Date",
                        "Disease",
                        "State",
                        "District",
                        "Cases",
                        "Deaths",
                        "Status",
                    ],
                    datatype=[
                        "str",
                        "str",
                        "str",
                        "str",
                        "number",
                        "number",
                        "str",
                    ],
                    interactive=False,
                    wrap=True,
                )

                # ------------------------------------------------
                # SEARCH
                # ------------------------------------------------

                gr.HTML('<div id="records-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                gr.Markdown(
                    """
                    ## 🔎 Surveillance Record Search

                    Search official IDSP records by disease, state,
                    district, week or year.
                    """
                )

                with gr.Row():

                    search_disease = gr.Textbox(
                        label="Disease",
                        placeholder="Example: Dengue"
                    )

                    search_state = gr.Textbox(
                        label="State",
                        placeholder="Example: Karnataka"
                    )

                    search_district = gr.Textbox(
                        label="District",
                        placeholder="Example: Koppal"
                    )

                with gr.Row():

                    search_week = gr.Number(
                        label="Week",
                        precision=0
                    )

                    search_year = gr.Number(
                        label="Year",
                        precision=0
                    )

                    search_limit = gr.Number(
                        label="Maximum Records",
                        value=100,
                        minimum=1,
                        maximum=500,
                        precision=0
                    )

                search_button = gr.Button(
                    "🔍 Search Surveillance Records",
                    variant="primary"
                )

                records_table = gr.Dataframe(
                    headers=[
                        "Record ID",
                        "Year",
                        "Week",
                        "Reporting Start",
                        "Reporting End",
                        "State",
                        "District",
                        "Disease",
                        "Cases",
                        "Deaths",
                        "Outbreak Status",
                        "Source",
                        "Source URL",
                    ],
                    interactive=False,
                    wrap=True,
                )

                search_button.click(
                    fn=search_records,
                    inputs=[
                        search_disease,
                        search_state,
                        search_district,
                        search_week,
                        search_year,
                        search_limit,
                    ],
                    outputs=[records_table],
                )

                # ------------------------------------------------
                # SUMMARIES
                # ------------------------------------------------

                gr.Markdown("---")

                with gr.Row():

                    with gr.Column(
                        elem_classes=["section-card"]
                    ):

                        gr.Markdown(
                            "## 🦠 Disease Summary"
                        )

                        disease_summary = gr.Dataframe(
                            headers=[
                                "Disease",
                                "Cases",
                                "Deaths",
                                "Records",
                            ],
                            datatype=[
                                "str",
                                "number",
                                "number",
                                "number",
                            ],
                            interactive=False,
                            wrap=True,
                        )

                    with gr.Column(
                        elem_classes=["section-card"]
                    ):

                        gr.Markdown(
                            "## 🗺️ State Summary"
                        )

                        state_summary = gr.Dataframe(
                            headers=[
                                "State",
                                "Cases",
                                "Deaths",
                                "Records",
                            ],
                            datatype=[
                                "str",
                                "number",
                                "number",
                                "number",
                            ],
                            interactive=False,
                            wrap=True,
                        )

                # ------------------------------------------------
                # COMMUNITY REPORTS
                # ------------------------------------------------

                gr.HTML('<div id="community-reports-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                with gr.Column(elem_classes=["community-card"]):

                    gr.Markdown(
                        """
                        ## 🧑‍🤝‍🧑 Community Health Reports

                        Community members can report unusual illness, suspected disease
                        clusters, or other public-health observations for review.
                        """
                    )

                    gr.Markdown(
                        """
                        <div class="community-help">
                        This prototype collects reports for review and does not diagnose
                        disease. Avoid entering unnecessary personal or confidential
                        medical information. Reports are stored locally in the dashboard
                        data folder and marked <b>Pending Review</b> until reviewed by an
                        authorized user.
                        </div>
                        """
                    )

                    with gr.Row():
                        community_reporter = gr.Textbox(
                            label="Reporter Name (optional)",
                            placeholder="Example: Community Member",
                        )

                        community_contact = gr.Textbox(
                            label="Contact (optional)",
                            placeholder="Phone or email",
                        )

                        community_anonymous = gr.Checkbox(
                            label="Submit Anonymously",
                            value=False,
                        )

                    with gr.Row():
                        community_state = gr.Textbox(
                            label="State *",
                            placeholder="Example: Karnataka",
                        )

                        community_district = gr.Textbox(
                            label="District *",
                            placeholder="Example: Bengaluru Urban",
                        )

                    with gr.Row():
                        community_type = gr.Dropdown(
                            label="Report Type *",
                            choices=[
                                "Unusual illness",
                                "Suspected disease case",
                                "Possible cluster",
                                "Food or water-related concern",
                                "Environmental health concern",
                                "Other public-health observation",
                            ],
                            value="Unusual illness",
                        )

                        community_disease = gr.Textbox(
                            label="Disease / Symptoms *",
                            placeholder="Example: Fever with rash, vomiting, diarrhoea",
                        )

                    with gr.Row():
                        community_affected = gr.Number(
                            label="People Affected *",
                            value=1,
                            minimum=1,
                            precision=0,
                        )

                        community_severity = gr.Dropdown(
                            label="Observed Severity",
                            choices=["Low", "Moderate", "High", "Emergency"],
                            value="Moderate",
                        )

                    community_description = gr.Textbox(
                        label="Description *",
                        placeholder="Describe what was observed, when it started, and any relevant non-sensitive details.",
                        lines=5,
                    )

                    community_evidence = gr.File(
                        label="Evidence Images (optional)",
                        file_count="multiple",
                        file_types=["image"],
                        type="filepath",
                    )

                    gr.Markdown(
                        "📷 You can attach up to 5 JPG, JPEG, PNG, or WEBP images as evidence. "
                        "Avoid faces, medical records, phone numbers, addresses, or other unnecessary personal information.",
                        elem_classes=["evidence-note"],
                    )

                    with gr.Row():
                        submit_community = gr.Button(
                            "📨 Submit Community Report",
                            variant="primary",
                        )
                        clear_community = gr.Button(
                            "🧹 Clear Form",
                            variant="secondary",
                        )

                    community_message = gr.Markdown(
                        "",
                        elem_classes=["community-success"],
                    )

                    gr.Markdown("### Recent Community Reports")

                    community_table = gr.Dataframe(
                        headers=[
                            "Report ID",
                            "Submitted",
                            "Reporter",
                            "State",
                            "District",
                            "Type",
                            "Disease / Symptoms",
                            "People Affected",
                            "Severity",
                            "Evidence",
                            "Status",
                        ],
                        datatype=[
                            "str",
                            "str",
                            "str",
                            "str",
                            "str",
                            "str",
                            "str",
                            "number",
                            "str",
                            "str",
                            "str",
                        ],
                        value=community_report_rows(),
                        interactive=False,
                        wrap=True,
                    )

                    gr.Markdown("### Submitted Evidence Images")

                    community_evidence_gallery_component = gr.Gallery(
                        label="Community Evidence",
                        value=community_evidence_gallery(),
                        columns=4,
                        height="auto",
                        object_fit="contain",
                    )

                    submit_community.click(
                        fn=submit_community_report,
                        inputs=[
                            community_reporter,
                            community_contact,
                            community_state,
                            community_district,
                            community_type,
                            community_disease,
                            community_affected,
                            community_severity,
                            community_description,
                            community_evidence,
                            community_anonymous,
                        ],
                        outputs=[community_message, community_table, community_evidence_gallery_component],
                    )

                    clear_community.click(
                        fn=clear_community_form,
                        inputs=[],
                        outputs=[
                            community_reporter,
                            community_contact,
                            community_state,
                            community_district,
                            community_type,
                            community_disease,
                            community_affected,
                            community_severity,
                            community_description,
                            community_evidence,
                            community_anonymous,
                            community_message,
                        ],
                    )

                # ------------------------------------------------
                # WHO OUTBREAK NEWS
                # ------------------------------------------------

                gr.HTML('<div id="who-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                with gr.Column(elem_classes=["who-card"]):

                    gr.Markdown(
                        """
                        ## 🌍 Global Outbreak Intelligence

                        Selected disease outbreak notices retrieved from the
                        **World Health Organization (WHO) Disease Outbreak News API**.
                        WHO Disease Outbreak News provides an external global
                        surveillance signal that can complement India-specific IDSP
                        surveillance and community reports. It is not an exhaustive
                        list of every global public-health event.
                        """
                    )

                    with gr.Row():
                        who_refresh = gr.Button(
                            "🔄 Refresh WHO Data",
                            variant="primary",
                        )

                    who_table = gr.Dataframe(
                        headers=[
                            "Date",
                            "WHO Outbreak Notice",
                            "DON ID",
                            "Summary",
                            "Source",
                        ],
                        datatype=[
                            "str",
                            "str",
                            "str",
                            "str",
                            "str",
                        ],
                        value=fetch_who_disease_outbreak_news(),
                        interactive=False,
                        wrap=True,
                    )

                    gr.Markdown(
                        f"**Official source:** [{WHO_DON_PAGE}]({WHO_DON_PAGE})  \
                        **Purpose:** Global outbreak intelligence that complements India-specific IDSP surveillance and community reports.  \
                        **Scope:** Selected WHO Disease Outbreak News notices; this is not an exhaustive global event list.  \
                        **API source:** `{WHO_DON_API}`",
                        elem_classes=["who-source-note"],
                    )

                    who_refresh.click(
                        fn=fetch_who_disease_outbreak_news,
                        inputs=[],
                        outputs=[who_table],
                    )

                # ------------------------------------------------
                # DATA SOURCE
                # ------------------------------------------------

                gr.HTML('<div id="settings-section" class="nav-anchor"></div>')

                gr.Markdown("---")

                gr.Markdown(
                    """
                    ## 📚 Data Source

                    **Source:** Integrated Disease Surveillance Programme (IDSP)

                    **Database:** PostgreSQL

                    **Coverage:** District-level surveillance records

                    Original IDSP source URLs are retained with each record
                    for traceability.

                    **Prototype note:** Early-warning thresholds are
                    project-defined demonstration thresholds and are not
                    official IDSP thresholds.
                    """,
                    elem_classes=["data-source-section"]
                )



    # ========================================================
    # HEADER / AUTH EVENTS
    # ========================================================

    profile_open = gr.State(False)

    def toggle_profile(is_open):
        return (not bool(is_open), gr.update(visible=not bool(is_open)))

    admin_button.click(
        fn=toggle_profile,
        inputs=[profile_open],
        outputs=[profile_open, profile_menu],
    )

    logout_button.click(
        fn=logout_user,
        inputs=[],
        outputs=[login_panel, dashboard_panel, login_message, profile_open, profile_menu],
    )

    login_button.click(
        fn=authenticate,
        inputs=[login_username, login_password],
        outputs=[login_panel, dashboard_panel, login_message],
    )

    # ========================================================
    # REFRESH EVENT
    # ========================================================

    refresh_dashboard.click(
        fn=load_dashboard,
        inputs=[],
        outputs=[
            total_hospitals,
            total_diseases,
            total_records,
            total_alerts,
            total_cases,
            total_deaths,
            alert_table,
            disease_donut_plot,
            disease_trend_plot,
            state_plot,
            map_plot,
            latest_table,
            disease_summary,
            state_summary,
        ],
    )

    # ========================================================
    # INITIAL LOAD
    # ========================================================

    demo.load(
        fn=load_dashboard,
        inputs=[],
        outputs=[
            total_hospitals,
            total_diseases,
            total_records,
            total_alerts,
            total_cases,
            total_deaths,
            alert_table,
            disease_donut_plot,
            disease_trend_plot,
            state_plot,
            map_plot,
            latest_table,
            disease_summary,
            state_summary,
        ],
    )


# ============================================================
# LAUNCH
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 65)
    print("SAMRAKSHA KENDRA - IDSP DASHBOARD")
    print("=" * 65)
    print()
    print("Backend API :", API_URL)
    print("Dashboard   :", f"http://127.0.0.1:{PORT}")
    print("Map source  :", GEOJSON_URL)
    print("WHO source  :", WHO_DON_API)
    print("WHO purpose : Global outbreak intelligence (not exhaustive global surveillance)")
    print()
    print("=" * 65)
    print()

    demo.launch(
        server_name="127.0.0.1",
        server_port=PORT,
        theme=gr.themes.Soft(),
        css=CUSTOM_CSS,
        inbrowser=True,
        show_error=True,
    )
