"""Operator page: tomorrow's plan, why, how it did on past days, and where it failed.

Run with:  streamlit run src/lebanon_energy/app/main.py

The page holds no model. The Tomorrow view shows what the API returns; the
Backtest page and Failure gallery show logged results:
  AZM_HISTORY_CSV    prepared hourly meter data (a live feed would replace it)
  AZM_BACKTEST_CSV   scripts/build_backtest_table.py
  AZM_FAILURES_JSON  scripts/analyse_errors.py

Design rules followed here (app screen, not a landing page): colour goes on
data and status only; headline numbers are type in one divided strip, not
tiles; surfaces are flat white cards with a 1px edge; each view opens with
its title and the one finding that matters.
"""

import csv
from datetime import date, datetime, timedelta
from html import escape
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

import plotly.graph_objects as go
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
HISTORY_CSV = Path(os.environ.get("AZM_HISTORY_CSV", "outputs/baselines_confirmed_azm/hourly_data.csv"))
BACKTEST_CSV = Path(os.environ.get("AZM_BACKTEST_CSV", "outputs/walk_forward/backtest.csv"))
FAILURES_JSON = Path(os.environ.get("AZM_FAILURES_JSON", "outputs/error_analysis/results.json"))
HISTORY_DAYS_SENT = 60
MISSING_OPTIONS = {"Nothing missing": 0, "Last 6 hours of meter data": 6,
                   "Last 24 hours of meter data": 24, "All meter history": None}

# Ink, greys and lines. Every grey that carries words is at least 4.5:1 on white.
INK, SECONDARY, MUTED = "#171717", "#4d4d4d", "#666666"
GROUND, SURFACE, EDGE, GRID = "#f3f6fb", "#ffffff", "#dfe5ee", "#e9edf3"
ACCENT, ACCENT_DEEP, ACCENT_PALE, WARM = "#2563eb", "#1d4ed8", "#e6efff", "#c2410c"
# One data hue: the forecast. Actuals are ink, the baseline is grey.
FORECAST, BAND, ACTUAL, BASELINE = ACCENT, "rgba(37,99,235,0.20)", INK, "#ea580c"
# Capacity ramp, mint through blue to deep indigo: a bigger generator set is a darker, cooler cell.
CAPACITY_STEPS = ["#8fe0c8", "#3fbfd0", "#2a8fe0", "#2f5fd6", "#3d3bb5", "#2a2175"]
UNAVAILABLE = "#f1f2f4"
# Status pairs (pale fill, dark text of the same hue) and the negative signal.
STATUS = {"full": ("#e3f6ea", "#0c4a26", "#bfe6cd", "Inputs complete"),
          "fallback": ("#fff7e0", "#7a4a05", "#f3dc9a", "Fallback in use"),
          "unavailable": ("#ffedea", "#831c1e", "#f5c6c0", "No forecast")}
NEGATIVE, OVER_FILL, OVER_TEXT = "#dc2626", "#fbd35a", "#4a2f00"
PLAIN = dict(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
             font=dict(color=INK, family="Segoe UI, Helvetica Neue, Arial, sans-serif", size=13))
NO_TOOLBAR = {"displayModeBar": False}

LOGO = f"""<svg xmlns="http://www.w3.org/2000/svg" width="210" height="36" viewBox="0 0 210 36">
<rect x="0" y="22" width="6" height="10" fill="{CAPACITY_STEPS[1]}"/><rect x="8" y="16" width="6" height="16" fill="{CAPACITY_STEPS[2]}"/>
<rect x="16" y="10" width="6" height="22" fill="{CAPACITY_STEPS[3]}"/><rect x="24" y="4" width="6" height="28" fill="{CAPACITY_STEPS[5]}"/>
<text x="40" y="24" font-family="Source Sans Pro, Segoe UI, Helvetica, Arial, sans-serif" font-size="18" font-weight="600" fill="{INK}">Azm generators</text></svg>"""

CSS = f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
html, body, .stApp, .stApp p, .stApp label, .stApp input, .stApp button, .stApp h1, .stApp h3, .stApp td, .stApp div {{
  font-family: Inter, "Segoe UI", "Helvetica Neue", Arial, sans-serif; }}
.stApp [data-testid="stIconMaterial"], .stApp span[class*="material"] {{ font-family: "Material Symbols Rounded" !important; }}
.block-container {{ max-width: 1240px; padding-top: 2.4rem; padding-bottom: 3rem; }}
h1 {{ font-size: 24px !important; font-weight: 600 !important; letter-spacing: -0.04em !important; line-height: 32px !important; padding: 0 0 2px 0 !important; }}
h3 {{ font-size: 15px !important; font-weight: 600 !important; letter-spacing: -0.02em !important; padding: 0 !important; }}
[class*="st-key-card"] {{ background: {SURFACE}; border: 1px solid {EDGE} !important; border-radius: 8px !important; }}
[data-testid="stSidebar"] {{ border-right: 1px solid {EDGE}; }}
.finding {{ font-size: 16px; color: {SECONDARY}; margin: 0 0 14px 0; max-width: 62rem; }}
.finding b {{ color: {INK}; font-weight: 600; }}
.stamp {{ font-size: 13px; color: {MUTED}; text-align: right; padding-top: 8px; line-height: 20px; }}
.pill {{ display: inline-block; font-size: 12px; font-weight: 500; line-height: 20px; padding: 0 9px; border-radius: 999px; border: 1px solid; white-space: nowrap; margin-bottom: 4px; }}
.navhead {{ font-size: 12px; color: {MUTED}; margin: 6px 0 -6px 10px; }}
[class*="st-key-nav_"] [data-testid="stRadioGroup"] {{ gap: 2px; }}
[class*="st-key-nav_"] [data-testid="stRadioOption"] {{ width: 100%; margin: 0; padding: 6px 10px; border-radius: 6px; cursor: pointer; }}
[class*="st-key-nav_"] [data-testid="stRadioOption"] > span:first-child {{ display: none !important; }}
[class*="st-key-nav_"] [data-testid="stRadioOption"]:hover {{ background: rgba(37,99,235,0.07); }}
[class*="st-key-nav_"] [data-testid="stRadioOption"]:has(input:checked) {{ background: {ACCENT_PALE}; }}
[class*="st-key-nav_"] [data-testid="stRadioOption"]:has(input:checked) p {{ color: {ACCENT_DEEP}; font-weight: 600; }}
[class*="st-key-nav_"] [data-testid="stRadioOption"]:has(input:focus-visible) {{ outline: 2px solid {ACCENT}; outline-offset: 1px; }}
[data-testid="stSidebar"] hr {{ margin: 10px 0; border-color: {EDGE}; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12px; color: {SECONDARY}; margin: 0 0 2px 56px; }}
.legend span {{ white-space: nowrap; }}
.legend i {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px; margin-right: 6px; vertical-align: -1px; }}
.legend .dim {{ color: {MUTED}; }}
.plan {{ width: 100%; border-collapse: collapse; font-size: 14px; margin-top: 8px; }}
.plan th {{ font-size: 12px; font-weight: 400; color: {MUTED}; text-align: left; padding: 0 0 6px 0; }}
.plan td {{ padding: 7px 0; border-top: 1px solid {EDGE}; font-variant-numeric: tabular-nums; white-space: nowrap; }}
.plan th.num, .plan td.num {{ text-align: right; }}
.plan td.run {{ font-weight: 600; }}
.plan td i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 8px; }}
.plan .dim {{ color: {MUTED}; }}
.notice {{ display: flex; gap: 10px; align-items: baseline; border: 1px solid; border-radius: 8px; padding: 9px 14px; font-size: 14px; margin-bottom: 14px; }}
.notice .tag {{ font-weight: 600; white-space: nowrap; }}
.kpis {{ display: grid; background: {SURFACE}; border: 1px solid {EDGE}; border-radius: 8px; margin-bottom: 16px; }}
.kpis > div {{ padding: 14px 18px 15px 18px; border-left: 1px solid {EDGE}; min-width: 0; }}
.kpis > div:first-child {{ border-left: 0; }}
.kpis {{ border-top: 3px solid {ACCENT}; overflow: hidden; }}
.kpis .lead {{ background: {ACCENT_PALE}; }}
.kpis .lead .value {{ color: {ACCENT_DEEP}; }}
.why td.pos {{ color: {ACCENT_DEEP}; }}
.why td.neg {{ color: {WARM}; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{ background: {ACCENT_PALE} !important; }}
[data-testid="stSidebarNavLink"][aria-current="page"] span {{ color: {ACCENT_DEEP} !important; font-weight: 600; }}
[class*="st-key-card"] h3 {{ border-left: 3px solid {ACCENT}; padding-left: 9px !important; }}
.finding b {{ color: {ACCENT_DEEP} !important; }}
.kpis .label {{ font-size: 13px; color: {MUTED}; }}
.kpis .value {{ font-size: 26px; line-height: 1.25; color: {INK}; font-variant-numeric: tabular-nums; white-space: nowrap; letter-spacing: -0.03em; }}
.kpis .lead .value {{ font-size: 32px; font-weight: 600; }}
.kpis .unit {{ font-size: 14px; color: {MUTED}; margin-left: 4px; letter-spacing: 0; font-weight: 400; }}
.kpis .note {{ font-size: 13px; color: {MUTED}; }}
.kpis .bad .value {{ color: {NEGATIVE}; }}
.cardnote {{ font-size: 13px; color: {MUTED}; margin: 2px 0 0 0; }}
.why {{ font-size: 15px; color: {INK}; margin: 0; }}
.why td {{ padding: 5px 0; vertical-align: baseline; }}
.why td.kw {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; padding-left: 18px; font-weight: 600; }}
.why tr.total td {{ border-top: 1px solid {EDGE}; padding-top: 8px; }}
.why .dim {{ color: {MUTED}; }}
@media (max-width: 640px) {{ .block-container {{ padding-top: 4.6rem; }} .kpis {{ grid-template-columns: 1fr 1fr !important; }} .kpis > div:nth-child(odd) {{ border-left: 0; }}
  .kpis > div:nth-child(n+3) {{ border-top: 1px solid {EDGE}; }} .stamp {{ text-align: left; padding-top: 0; }} }}
</style>"""


# ---------- data ----------

@st.cache_data(show_spinner=False)
def load_history(path, modified):
    """{target: {timestamp: kW}} for Azm from the prepared hourly file."""
    series = {"load": {}, "pv": {}}
    with open(path, encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["site_id"] == "azm":
                series[row["target"]][datetime.fromisoformat(row["timestamp_local_unverified"])] = float(
                    row["value_source_units"])
    return series


@st.cache_data(show_spinner=False)
def load_backtest(path, modified):
    """{date: [hourly rows]} from the logged backtest table; numbers are floats or None."""
    days = {}
    with open(path, encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            stamp = datetime.fromisoformat(row["timestamp_local"])
            entry = {key: (float(value) if value != "" else None) if key.endswith("_kw") else value
                     for key, value in row.items()}
            entry["stamp"] = stamp
            days.setdefault(stamp.date(), []).append(entry)
    return days


def request_forecast(issue, history, missing_hours):
    readings = []
    if missing_hours is not None:
        cutoff, start = issue - timedelta(hours=missing_hours), issue - timedelta(days=HISTORY_DAYS_SENT)
        for stamp in sorted(history["load"].keys() | history["pv"].keys()):
            if start <= stamp < cutoff:
                readings.append({"timestamp_local": stamp.isoformat(), "load_kw": history["load"].get(stamp),
                                 "pv_kw": history["pv"].get(stamp)})
    body = json.dumps({"issue_time_local": issue.isoformat(), "readings": readings}).encode("utf-8")
    call = urllib.request.Request(f"{API_URL}/forecast", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(call, timeout=30) as response:
        return json.load(response)


def configuration_label(row):
    options = row["generator"]["configurations"]
    if not options:
        return "none" if row["generator"]["status"] == "insufficient_available_capacity" else "?"
    return " or ".join("+".join(option) for option in options)


def switch_blocks(labels, hours):
    """Consecutive hours with the same recommendation, as [start, end (exclusive), label]."""
    blocks = []
    for label, hour in zip(labels, hours):
        if blocks and blocks[-1][2] == label:
            blocks[-1][1] = hour + timedelta(hours=1)
        else:
            blocks.append([hour, hour + timedelta(hours=1), label])
    return blocks


def day_scores(rows):
    scored = [row for row in rows if row["actual_kw"] is not None and row["forecast_kw"] is not None]
    if not scored:
        return None
    count = len(scored)
    return {"model": sum(abs(row["actual_kw"] - row["forecast_kw"]) for row in scored) / count,
            "baseline": sum(abs(row["actual_kw"] - row["baseline_kw"]) for row in scored
                            if row["baseline_kw"] is not None) / count,
            "peak": max(row["actual_kw"] for row in scored),
            "undersized": sum(row["verdict"] == "undersized" for row in rows),
            "oversized": sum(row["verdict"] == "oversized" for row in rows),
            "right": sum(row["verdict"] == "right-sized" for row in rows)}


# ---------- building blocks ----------

def header(title, finding, stamp="", status=None):
    """Title, the one finding under it, and on the right the input status and a freshness note."""
    left, right = st.columns([3, 1], vertical_alignment="top")
    left.title(title)
    pill = ""
    if status is not None:
        fill, text, edge, tag = STATUS[status["level"]]
        pill = f'<span class="pill" style="background:{fill};color:{text};border-color:{edge}">{tag}</span><br>'
    if stamp or pill:
        right.html(f'<div class="stamp">{pill}{escape(stamp)}</div>')
    st.html(f'<p class="finding">{finding}</p>')


def capacity_legend(policy, colours):
    """Swatch, unit names and capacity for every allowed configuration, smallest first."""
    items = sorted((sum(policy["capacities_kw"][unit] for unit in option), "+".join(sorted(option)))
                   for option in policy["allowed_configurations"])
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{colours[capacity]}"></i>{escape(name)} <span class="dim">{capacity:.0f} kW</span></span>'
        for capacity, name in items) + "</div>"


def kpi_strip(items):
    """One divided strip of figures. items: (label, value, unit, note, style) with style '', 'lead' or 'bad'."""
    cells = "".join(
        f'<div class="{style}"><div class="label">{escape(label)}</div>'
        f'<div class="value">{escape(str(value))}<span class="unit">{escape(unit)}</span></div>'
        f'<div class="note">{escape(note) if note else "&nbsp;"}</div></div>'
        for label, value, unit, note, style in items)
    st.html(f'<div class="kpis" style="grid-template-columns: repeat({len(items)}, 1fr)">{cells}</div>')


def notice(level, message):
    fill, text, edge, tag = STATUS[level]
    st.html(f'<div class="notice" role="status" style="background:{fill};color:{text};border-color:{edge}">'
            f'<span class="tag">{tag}</span><span>{escape(message)}</span></div>')


def load_figure(hours, forecast, upper, actual=None, baseline=None, height=300):
    """Forecast line with a band up to the upper estimate; optional actual (ink) and baseline (grey)."""
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=hours, y=forecast, mode="lines", name="Forecast",
                                line=dict(color=FORECAST, width=2), hovertemplate="%{y:.0f} kW"))
    figure.add_trace(go.Scatter(x=hours, y=upper, mode="lines", name="Upper estimate",
                                fill="tonexty", fillcolor=BAND, line=dict(color=FORECAST, width=1, dash="dot"),
                                hovertemplate="%{y:.0f} kW"))
    if baseline is not None:
        figure.add_trace(go.Scatter(x=hours, y=baseline, mode="lines", name="Baseline (last week)",
                                    line=dict(color=BASELINE, width=1.5, dash="dash"), hovertemplate="%{y:.0f} kW"))
    if actual is not None and any(value is not None for value in actual):
        figure.add_trace(go.Scatter(x=hours, y=actual, mode="lines", name="Actual",
                                    line=dict(color=ACTUAL, width=2), hovertemplate="%{y:.0f} kW"))
    figure.update_layout(height=height, margin=dict(l=56, r=12, t=34, b=28), hovermode="x unified",
                         legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, traceorder="normal",
                                     itemsizing="constant", font=dict(size=13, color=SECONDARY)),
                         hoverlabel=dict(bgcolor=SURFACE, bordercolor=EDGE, font=dict(color=INK, size=13)), **PLAIN)
    figure.update_xaxes(tickformat="%H:%M", nticks=9, showgrid=False, linecolor=GRID,
                        tickfont=dict(size=12, color=MUTED), range=[hours[0], hours[-1]])
    figure.update_yaxes(gridcolor=GRID, zeroline=True, zerolinecolor="#cfd2d6", rangemode="tozero", nticks=6,
                        tickfont=dict(size=12, color=MUTED), ticksuffix=" kW")
    return figure


def capacity_colours(capacities):
    ordered = sorted(capacities)
    last = len(CAPACITY_STEPS) - 1
    return {capacity: CAPACITY_STEPS[min(index * last // max(len(ordered) - 1, 1), last)]
            for index, capacity in enumerate(ordered)}


def capacity_lane(name, capacities, labels, hover, colours):
    fills = [colours.get(capacity, UNAVAILABLE) for capacity in capacities]
    return name, fills, labels, hover, ["#ffffff" if fill in CAPACITY_STEPS[2:] else INK for fill in fills]


def strip_figure(hours, lanes):
    """Hourly cells, one row per lane. lanes: (name, fills, labels, hover texts, text colours)."""
    figure = go.Figure()
    for name, fills, labels, hover, text_colours in lanes:
        figure.add_trace(go.Bar(
            y=[name] * len(hours), x=[3600 * 1000] * len(hours), base=list(hours), orientation="h",
            marker=dict(color=fills, line=dict(color=SURFACE, width=2)), text=labels, textposition="inside",
            insidetextanchor="middle", textangle=0, textfont=dict(color=text_colours, size=12),
            hovertext=hover, hoverinfo="text", showlegend=False))
    figure.update_layout(height=58 + 40 * len(lanes), margin=dict(l=56, r=12, t=2, b=26), barmode="overlay", bargap=0.16,
                         uniformtext=dict(minsize=11, mode="hide"),
                         hoverlabel=dict(bgcolor=SURFACE, bordercolor=EDGE, font=dict(color=INK, size=13)), **PLAIN)
    figure.update_xaxes(type="date", tickformat="%H:%M", nticks=9, showgrid=False,
                        tickfont=dict(size=12, color=MUTED), range=[hours[0], hours[-1] + timedelta(hours=1)])
    figure.update_yaxes(autorange="reversed", showgrid=False, tickfont=dict(size=13, color=SECONDARY))
    return figure


def card(name):
    """A flat white panel with a 1px edge (styled through its key in CSS)."""
    return st.container(border=True, key=f"card-{name}")


def card_title(title, note=""):
    st.subheader(title)
    if note:
        st.html(f'<p class="cardnote">{escape(note)}</p>')


def why_card(drivers):
    card_title("Why this peak")
    if not drivers.get("available"):
        st.html(f'<p class="cardnote">{escape(drivers.get("reason", "No explanation available."))}</p>')
        return
    hour = drivers["timestamp_local"][11:16]
    rows = [f'<tr><td class="dim">An average hour</td><td class="kw">{drivers["average_level_kw"]:.0f} kW</td></tr>']
    for driver in drivers["drivers"]:
        rows.append(f'<tr><td>{escape(driver["text"])}</td><td class="kw {"pos" if driver["effect_kw"] > 0 else "neg"}">{driver["effect_kw"]:+.0f} kW</td></tr>')
    rows.append(f'<tr class="total"><td>Forecast at {hour}</td><td class="kw">{drivers["forecast_kw"]:.0f} kW</td></tr>')
    rows.append(f'<tr><td>Safety margin: the upper range of recent errors at {hour}</td>'
                f'<td class="kw pos">+{drivers["margin_kw"]:.0f} kW</td></tr>')
    rows.append(f'<tr class="total"><td><b>Plan for</b></td><td class="kw">{drivers["upper_kw"]:.0f} kW</td></tr>')
    st.html(f'<table class="why">{"".join(rows)}</table>')
    st.html('<p class="cardnote">The three largest effects are shown; the model is linear, so effects add up exactly.</p>')


# ---------- views ----------

def tomorrow_page():
    if not HISTORY_CSV.is_file():
        st.title("Tomorrow's plan")
        notice("unavailable", f"Meter history not found at {HISTORY_CSV}. Run scripts/run_baselines.py first.")
        return
    history = load_history(str(HISTORY_CSV), HISTORY_CSV.stat().st_mtime)
    latest_issue = (max(history["load"]) + timedelta(hours=1)).replace(hour=0, minute=0)
    with st.sidebar:
        earliest = date.fromisoformat(os.environ.get("AZM_FIRST_ISSUE_DATE", "2026-08-01"))
        day = st.date_input("Plan for", value=latest_issue.date(), min_value=earliest, max_value=latest_issue.date(),
                            help="The forecast is made at midnight at the start of this day.")
        missing_label = st.radio("Missing at midnight", list(MISSING_OPTIONS), index=0,
                                 help="Try a missing-data case to see how the plan changes when the meter feed is late or down.")
        show_actual = st.toggle("Show what actually happened", value=False,
                                help="Only for past days. Never shown to the model.")
    issue = datetime.combine(day, datetime.min.time())
    title = f"Azm: plan for {day:%A %d %B %Y}"
    try:
        data = request_forecast(issue, history, MISSING_OPTIONS[missing_label])
    except urllib.error.HTTPError as error:
        st.title(title)
        notice("unavailable", f"The forecast service refused this request: {error.read().decode('utf-8', 'replace')[:300]}")
        return
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        st.title(title)
        notice("unavailable", f"Cannot reach the forecast service at {API_URL}. Start it, then reload this page.")
        return

    status, rows, policy = data["input_status"], data["hourly"], data["generator_policy"]
    available = [row for row in rows if row["net_upper_kw"] is not None]
    stamp = f"Forecast made at 00:00 · model trained to {data['model_training_end_exclusive'][:10]}"
    if not available:
        header(title, "No plan could be produced for this day.", stamp)
        notice(status["level"], status["message"])
        return
    hours = [datetime.fromisoformat(row["timestamp_local"]) for row in rows]
    labels = [configuration_label(row) for row in rows]
    blocks = switch_blocks(labels, hours)
    peak = max(available, key=lambda row: row["net_upper_kw"])
    largest = max(available, key=lambda row: row["generator"]["capacity_kw"] or 0)
    largest_label = configuration_label(largest)
    largest_blocks = [block for block in blocks if block[2] == largest_label]
    spans = ", ".join(f"{start:%H:%M}–{end:%H:%M}" if end.date() == start.date() else f"{start:%H:%M}–24:00"
                      for start, end, _ in largest_blocks)
    others = sorted({block[2] for block in blocks if block[2] != largest_label})
    finding = (f"Run <b>{escape(largest_label)}</b> {spans}" + (f", and {escape(' or '.join(others))} the rest of the day" if others else " all day")
               + f". The plan covers up to <b>{peak['net_upper_kw']:.0f} kW</b> at {peak['timestamp_local'][11:16]}.")
    header(title, finding, stamp, status)
    if status["level"] != "full":
        notice(status["level"], status["message"])

    forecast_peak = max(available, key=lambda row: row["net_kw"])
    kpi_strip([
        ("Highest load to plan for", f"{peak['net_upper_kw']:.0f}", "kW", f"at {peak['timestamp_local'][11:16]}", "lead"),
        ("Forecast peak", f"{forecast_peak['net_kw']:.0f}", "kW", f"at {forecast_peak['timestamp_local'][11:16]}, before the safety margin", ""),
        ("Largest unit needed", largest_label, f"{largest['generator']['capacity_kw']:.0f} kW" if largest["generator"]["capacity_kw"] else "",
         f"{sum(label == largest_label for label in labels)} of 24 hours", ""),
        ("Generator changes", max(len(blocks) - 1, 0), "", "during the day", ""),
    ])

    colours = capacity_colours({sum(policy["capacities_kw"][unit] for unit in option)
                                for option in policy["allowed_configurations"]})
    hover = [f"{row['timestamp_local'][11:16]}  Run {label}"
             + (f" ({row['generator']['capacity_kw']:.0f} kW) to cover {row['generator']['required_capacity_kw']:.0f} kW"
                if row["generator"]["capacity_kw"] else "") for row, label in zip(rows, labels)]
    strip, plan = st.columns([5, 3], gap="medium")
    with strip, card("strip"):
        card_title("Generator to run each hour", f"A dip shorter than {policy['minimum_run_hours']} hours "
                   "stays on the larger unit. Darker means larger.")
        st.plotly_chart(strip_figure(hours, [capacity_lane("Run", [row["generator"]["capacity_kw"] for row in rows],
                                                           labels, hover, colours)]),
                        use_container_width=True, config=NO_TOOLBAR)
        st.html(capacity_legend(policy, colours))
    with plan, card("plan"):
        card_title("Plan")
        capacity_of = {configuration_label(row): row["generator"]["capacity_kw"] for row in rows}
        body = "".join(
            f'<tr><td>{start:%H:%M} <span class="dim">to</span> {"24:00" if end.date() != start.date() else f"{end:%H:%M}"}</td>'
            f'<td class="run"><i style="background:{colours.get(capacity_of.get(label), UNAVAILABLE)}"></i>{escape(label)}</td>'
            f'<td class="num">{"" if not capacity_of.get(label) else f"{capacity_of[label]:.0f} kW"}</td>'
            f'<td class="num dim">{int((end - start).total_seconds() // 3600)} h</td></tr>'
            for start, end, label in blocks)
        st.html('<table class="plan"><tr><th>When</th><th>Run</th><th class="num">Capacity</th>'
                f'<th class="num">For</th></tr>{body}</table>')

    actual_net = [history["load"][stamp_] - history["pv"][stamp_]
                  if stamp_ in history["load"] and stamp_ in history["pv"] else None for stamp_ in hours]
    chart, why = st.columns([5, 3], gap="medium")
    with chart, card("load"):
        card_title("Net load on the generators", "Campus load minus solar, hourly average. "
                   "About 9 hours in 10 stay below the upper estimate.")
        st.plotly_chart(load_figure(hours, [row["net_kw"] for row in rows], [row["net_upper_kw"] for row in rows],
                                    actual_net if show_actual else None, height=336), use_container_width=True, config=NO_TOOLBAR)
    with why, card("why"):
        why_card(data["peak_drivers"])

    with st.expander("Hour-by-hour numbers"):
        st.dataframe([{"Hour": row["timestamp_local"][11:16],
                       "Net forecast (kW)": None if row["net_kw"] is None else round(row["net_kw"]),
                       "Upper estimate (kW)": None if row["net_upper_kw"] is None else round(row["net_upper_kw"]),
                       "Run": label, "Capacity (kW)": row["generator"]["capacity_kw"],
                       "Forecast method": row["net_method"],
                       **({"Actual net (kW)": None if actual is None else round(actual)} if show_actual else {})}
                      for row, label, actual in zip(rows, labels, actual_net)],
                     hide_index=True, use_container_width=True)
    with st.expander("Limits of this plan"):
        for line in data["limitations"]:
            st.markdown(f"- {line}")
        st.markdown(f"- Reserve margin {policy['reserve_margin_fraction']:.0%}. {policy['rule']}")


def all_capacity_colours(days):
    """One colour per capacity across the whole table, so a unit keeps its colour on every day."""
    return capacity_colours({row[key] for rows in days.values() for row in rows
                             for key in ("picked_capacity_kw", "needed_capacity_kw") if row[key] is not None})


def backtest_day(rows, colours, height=290):
    """Forecast against actual, then what the rule picked, what was needed, and the verdict for each hour."""
    hours = [row["stamp"] for row in rows]
    st.plotly_chart(load_figure(hours, [row["forecast_kw"] for row in rows], [row["upper_kw"] for row in rows],
                                [row["actual_kw"] for row in rows], [row["baseline_kw"] for row in rows], height),
                    use_container_width=True, config=NO_TOOLBAR)

    def lane(name, key, label_key, note):
        return capacity_lane(name, [row[key] for row in rows], [row[label_key] for row in rows],
                             [f"{row['stamp']:%H:%M}  {note} {row[label_key] or 'nothing'}" for row in rows], colours)

    marks = {"undersized": (NEGATIVE, "under", "#ffffff"), "oversized": (OVER_FILL, "over", OVER_TEXT),
             "right-sized": (UNAVAILABLE, "", INK), "": (UNAVAILABLE, "", INK)}
    verdict = ("Result", [marks[row["verdict"]][0] for row in rows], [marks[row["verdict"]][1] for row in rows],
               [f"{row['stamp']:%H:%M}  {row['verdict'] or 'not scored'}" for row in rows],
               [marks[row["verdict"]][2] for row in rows])
    st.plotly_chart(strip_figure(hours, [lane("Picked", "picked_capacity_kw", "picked", "Rule picked"),
                                         lane("Needed", "needed_capacity_kw", "needed", "Load needed"), verdict]),
                    use_container_width=True, config=NO_TOOLBAR)
    st.html(f'<div class="legend"><span><i style="background:{OVER_FILL}"></i>over: a smaller unit would have done</span>'
            f'<span><i style="background:{NEGATIVE}"></i>under: the picked unit was below the load</span>'
            f'<span><i style="background:{UNAVAILABLE}"></i>right-sized</span></div>')


def day_strip(scores, lead_label="Model error"):
    kpi_strip([
        (lead_label, f"{scores['model']:.0f}", "kW", "average over the day", "lead"),
        ("Baseline error", f"{scores['baseline']:.0f}", "kW", "same hour last week", ""),
        ("Hours undersized", scores["undersized"], "", "picked unit below the load", "bad" if scores["undersized"] else ""),
        ("Hours oversized", scores["oversized"], "", "a smaller unit would have done", ""),
        ("Actual peak", f"{scores['peak']:.0f}", "kW", "highest hour", ""),
    ])


def backtest_page():
    if not BACKTEST_CSV.is_file():
        st.title("Backtest")
        notice("unavailable", f"Backtest table not found at {BACKTEST_CSV}. Run scripts/walk_forward.py, then "
               "scripts/build_backtest_table.py.")
        return
    days = load_backtest(str(BACKTEST_CSV), BACKTEST_CSV.stat().st_mtime)
    usable = sorted(day for day, rows in days.items() if day_scores(rows))
    with st.sidebar:
        day = st.date_input("Past day", value=usable[-1], min_value=usable[0], max_value=usable[-1],
                            help="Each day was forecast at midnight by a model fitted on earlier data only.")
    stamp = f"Logged forecasts, {usable[0]:%d %b} to {usable[-1]:%d %b %Y}"
    if day not in days or not day_scores(days[day]):
        header(f"Azm backtest: {day:%A %d %B %Y}", "No logged forecast for this day: the meter data is incomplete.", stamp)
        return
    scores = day_scores(days[day])
    better = scores["model"] < scores["baseline"]
    finding = (f"The forecast was <b>{scores['model']:.0f} kW</b> off on average, "
               f"{'better' if better else 'worse'} than the baseline's {scores['baseline']:.0f} kW. "
               + (f"The rule picked too small a unit in <b>{scores['undersized']} hour{'s' if scores['undersized'] != 1 else ''}</b>."
                  if scores["undersized"] else "The rule never picked too small a unit."))
    header(f"Azm backtest: {day:%A %d %B %Y}", finding, stamp)
    day_strip(scores)
    with card("backtest"):
        card_title("Forecast against what happened", "Picked: what the rule would have run. Needed: the smallest "
                   "configuration that covers the actual load. Darker means larger.")
        backtest_day(days[day], all_capacity_colours(days))


def failure_page():
    if not FAILURES_JSON.is_file() or not BACKTEST_CSV.is_file():
        st.title("Where the forecast failed")
        notice("unavailable", "Run scripts/analyse_errors.py and scripts/build_backtest_table.py to build this view.")
        return
    analysis = json.loads(FAILURES_JSON.read_text(encoding="utf-8"))["analysis"]
    days = load_backtest(str(BACKTEST_CSV), BACKTEST_CSV.stat().st_mtime)
    colours = all_capacity_colours(days)
    worst = analysis["worst_days"]
    under = sum("Under-forecast" in failure["explanation"] for failure in worst)
    header("Azm: where the forecast failed",
           f"The three worst days of {analysis['hours']:,} logged hours: <b>{under} under-forecast"
           f"{'s' if under != 1 else ''}</b> (the unsafe direction) and {len(worst) - under} over-forecast"
           f"{'s' if len(worst) - under != 1 else ''}. Explanations state what the data shows, not confirmed causes.",
           f"{analysis['first_hour'][:10]} to {analysis['last_hour'][:10]}")
    for failure in worst:
        day = date.fromisoformat(failure["date"])
        with card(f"failure-{failure['date']}"):
            card_title(f"{failure['weekday']} {day:%d %B %Y}", failure["explanation"])
            if day in days and day_scores(days[day]):
                day_strip(day_scores(days[day]))
                backtest_day(days[day], colours, height=250)


# ---------- new site ----------

TIME_COLUMNS = ("timestamp", "timestamp_local", "time", "datetime", "date")
LOAD_COLUMNS = ("load_kw", "load", "load power", "load_power", "demand", "consumption", "load power (w)", "load_w")
PV_COLUMNS = ("pv_kw", "pv", "solar", "production", "pv power (w)", "pv_w")
TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M")
TEMPLATE = "timestamp,load_kw,pv_kw\n2026-08-01 00:00,82.4,0\n2026-08-01 01:00,80.9,0\n2026-08-01 02:00,79.6,0\n"


def parse_time(text):
    text = text.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "")).replace(tzinfo=None)
    except ValueError:
        for pattern in TIME_FORMATS:
            try:
                return datetime.strptime(text, pattern)
            except ValueError:
                continue
    raise ValueError(f"Cannot read the time '{text}'")


def parse_history(content, scale):
    """Hourly net load {timestamp: kW} from an uploaded CSV, plus a short description of what was read.

    Readings finer than an hour are averaged into the hour. Net load is load
    minus PV when a PV column is present, otherwise the load itself.
    """
    rows = list(csv.DictReader(content.decode("utf-8-sig").splitlines()))
    if not rows:
        raise ValueError("The file has no data rows.")
    names = {name.strip().lower(): name for name in rows[0] if name}
    pick = lambda options: next((names[option] for option in options if option in names), None)
    time_column, load_column, pv_column = pick(TIME_COLUMNS), pick(LOAD_COLUMNS), pick(PV_COLUMNS)
    if time_column is None or load_column is None:
        raise ValueError("The file needs a 'timestamp' column and a 'load_kw' column. Found: " + ", ".join(rows[0]))
    buckets, skipped = {}, 0
    for row in rows:
        try:
            stamp = parse_time(row[time_column]).replace(minute=0, second=0, microsecond=0)
            load = float(row[load_column])
            pv = float(row[pv_column]) if pv_column and row[pv_column] not in ("", None) else 0.0
        except (ValueError, TypeError):
            skipped += 1
            continue
        buckets.setdefault(stamp, []).append((load - pv) * scale)
    if not buckets:
        raise ValueError("No row could be read. Check the time format, for example 2026-08-01 13:00.")
    net = {stamp: sum(values) / len(values) for stamp, values in buckets.items()}
    days = len({stamp.date() for stamp in net})
    note = (f"{len(net):,} hours over {days} days, {min(net):%d %b %Y} to {max(net):%d %b %Y}. "
            + ("Net load = load minus PV. " if pv_column else "No PV column: the load itself is forecast. ")
            + (f"{skipped} unreadable rows were skipped." if skipped else ""))
    return net, note


def request_site_forecast(name, net, generators, parallel, reserve, minimum_run, location="", lebanese_holidays=True):
    body = json.dumps({"site_name": name or "New site", "location": location, "use_lebanese_holidays": lebanese_holidays,
                       "readings": [{"timestamp_local": stamp.isoformat(), "net_kw": value} for stamp, value in sorted(net.items())],
                       "generators": generators, "allow_parallel": parallel, "reserve_margin_fraction": reserve,
                       "minimum_run_hours": minimum_run}).encode("utf-8")
    call = urllib.request.Request(f"{API_URL}/sites/forecast", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(call, timeout=120) as response:
        return json.load(response)


def site_result(data):
    rows, policy, status = data["hourly"], data["generator_policy"], data["input_status"]
    hours = [datetime.fromisoformat(row["timestamp_local"]) for row in rows]
    available = [row for row in rows if row["net_upper_kw"] is not None]
    day = hours[0]
    if not available:
        notice("unavailable", status["message"])
        return
    peak = max(available, key=lambda row: row["net_upper_kw"])
    forecast_peak = max(available, key=lambda row: row["net_kw"])
    labels = [configuration_label(row) if policy else "" for row in rows]
    items = [("Highest load to plan for", f"{peak['net_upper_kw']:.0f}", "kW", f"at {peak['timestamp_local'][11:16]}", "lead"),
             ("Forecast peak", f"{forecast_peak['net_kw']:.0f}", "kW", f"at {forecast_peak['timestamp_local'][11:16]}, before the safety margin", "")]
    if policy:
        largest = max(available, key=lambda row: row["generator"]["capacity_kw"] or 0)
        blocks = switch_blocks(labels, hours)
        short = any(row["generator"]["status"] == "insufficient_available_capacity" for row in rows)
        items += [("Largest unit needed", configuration_label(largest),
                   f"{largest['generator']['capacity_kw']:.0f} kW" if largest["generator"]["capacity_kw"] else "",
                   "the generators entered cannot cover some hours" if short else "", "bad" if short else ""),
                  ("Generator changes", max(len(blocks) - 1, 0), "", "during the day", "")]
    items.append(("History used", data["history_days"], "days", f"{data['history_hours']:,} hours", ""))
    notice(status["level"], status["message"])
    kpi_strip(items)
    if policy:
        colours = capacity_colours({sum(policy["capacities_kw"][unit] for unit in option)
                                    for option in policy["allowed_configurations"]})
        hover = [f"{row['timestamp_local'][11:16]}  Run {label}" for row, label in zip(rows, labels)]
        strip, plan = st.columns([5, 3], gap="medium")
        with strip, card("site-strip"):
            card_title("Generator to run each hour", f"A dip shorter than {policy['minimum_run_hours']} hours stays on "
                       f"the larger unit. Reserve margin {policy['reserve_margin_fraction']:.0%}.")
            st.plotly_chart(strip_figure(hours, [capacity_lane("Run", [row["generator"]["capacity_kw"] for row in rows],
                                                               labels, hover, colours)]),
                            use_container_width=True, config=NO_TOOLBAR)
            st.html(capacity_legend(policy, colours))
        with plan, card("site-plan"):
            card_title("Plan")
            capacity_of = {configuration_label(row): row["generator"]["capacity_kw"] for row in rows}
            body = "".join(
                f'<tr><td>{start:%H:%M} <span class="dim">to</span> {"24:00" if end.date() != start.date() else f"{end:%H:%M}"}</td>'
                f'<td class="run"><i style="background:{colours.get(capacity_of.get(label), UNAVAILABLE)}"></i>{escape(label)}</td>'
                f'<td class="num">{"" if not capacity_of.get(label) else f"{capacity_of[label]:.0f} kW"}</td>'
                f'<td class="num dim">{int((end - start).total_seconds() // 3600)} h</td></tr>'
                for start, end, label in blocks)
            st.html('<table class="plan"><tr><th>When</th><th>Run</th><th class="num">Capacity</th>'
                    f'<th class="num">For</th></tr>{body}</table>')
    with card("site-load"):
        card_title("Net load forecast", "Hourly average. About 9 hours in 10 stay below the upper estimate.")
        st.plotly_chart(load_figure(hours, [row["net_kw"] for row in rows], [row["net_upper_kw"] for row in rows]),
                        use_container_width=True, config=NO_TOOLBAR)
    check = data["history_check"]
    if check:
        with card("site-check"):
            card_title("How the method did on this site's own history",
                       f"The last {check['days']} days, each forecast from earlier data only. This is the only evidence "
                       "for this site: it has not been tested on held-out data.")
            better = check["mae_kw"] < check["baseline_mae_kw"]
            coverage = check["upper_coverage"]
            kpi_strip([
                ("Forecast error", f"{check['mae_kw']:.1f}", "kW", "" if check["nmae"] is None else f"{check['nmae']:.0%} of the average load", "lead"),
                ("Baseline error", f"{check['baseline_mae_kw']:.1f}", "kW", "same hour last week", ""),
                ("Against the baseline", "better" if better else "worse", "", "the model should beat it to be worth using", "" if better else "bad"),
                ("Hours below the upper estimate", "–" if coverage is None else f"{coverage:.0%}", "", "target 90%",
                 "bad" if coverage is not None and coverage < 0.8 else ""),
            ])
    with st.expander("Hour-by-hour numbers"):
        st.dataframe([{"Hour": row["timestamp_local"][11:16],
                       "Forecast (kW)": None if row["net_kw"] is None else round(row["net_kw"], 1),
                       "Upper estimate (kW)": None if row["net_upper_kw"] is None else round(row["net_upper_kw"], 1),
                       **({"Run": label, "Capacity (kW)": row["generator"]["capacity_kw"]} if policy else {}),
                       "Method": row["net_method"]} for row, label in zip(rows, labels)],
                     hide_index=True, use_container_width=True)
    with st.expander("Limits of this plan"):
        for line in data["limitations"]:
            st.markdown(f"- {line}")


def unique_site_name(name, existing):
    name = (name or "").strip() or f"Site {len(existing) + 1}"
    candidate, count = name, 2
    while candidate in existing or candidate in (AZM, ADD_SITE):
        candidate, count = f"{name} ({count})", count + 1
    return candidate


def new_site_page():
    header("Add a site", "Upload the site's hourly history, say where it is and which generators it has. "
           "It then appears in the list of sites on the left. <b>It is kept for this browser session only.</b>",
           "At least 14 days of history; 5 weeks or more is better")
    state = st.session_state
    left, right = st.columns([1, 1], gap="medium")
    with left, card("site-history"):
        card_title("1. Site and history", "A CSV with a timestamp column and load_kw; pv_kw is optional. Finer than "
                   "hourly is averaged to hours.")
        name = st.text_input("Site name", value=state.get("site_name", ""), placeholder="For example: North campus")
        location = st.text_input("Location", value=state.get("site_location", ""), placeholder="Town, or latitude and longitude",
                                 help="Shown with the plan. The forecast itself is learned from the site's own readings; "
                                      "location only decides which public holidays apply.")
        holidays = st.radio("Public holidays", ["Lebanon", "None (site outside Lebanon)"], horizontal=True,
                            help="Holidays are treated as days off. Choose None for a site in another country.")
        upload = st.file_uploader("Hourly history (CSV)", type=["csv"])
        unit = st.radio("Power unit in the file", ["kW", "W"], horizontal=True)
        first, second = st.columns(2)
        first.download_button("Download a template", TEMPLATE, file_name="site_history_template.csv", mime="text/csv",
                              use_container_width=True)
        example = second.button("Fill in an example", use_container_width=True,
                                help="Loads Azm's prepared history and its four generators as a second site, to see how this works.")
    if example and HISTORY_CSV.is_file():
        history = load_history(str(HISTORY_CSV), HISTORY_CSV.stat().st_mtime)
        state["site_net"] = {stamp: history["load"][stamp] - history["pv"][stamp]
                             for stamp in history["load"].keys() & history["pv"].keys()}
        state["site_note"] = "Example: Azm's prepared hourly history, net load = load minus PV."
        state["site_name"], state["site_location"] = "Example campus", "Tripoli, Lebanon"
        state["site_units"] = [{"Name": "G3", "Capacity (kW)": 146.1}, {"Name": "G2", "Capacity (kW)": 236.8},
                               {"Name": "G4", "Capacity (kW)": 315.0}, {"Name": "G1", "Capacity (kW)": 413.4}]
        st.rerun()
    if upload is not None and state.get("site_file") != (upload.name, upload.size, unit):
        try:
            state["site_net"], state["site_note"] = parse_history(upload.getvalue(), 0.001 if unit == "W" else 1.0)
            state["site_file"] = (upload.name, upload.size, unit)
        except (ValueError, UnicodeDecodeError) as error:
            state.pop("site_net", None)
            state["site_note"] = None
            with left:
                notice("unavailable", str(error))
    if state.get("site_net") and state.get("site_note"):
        with left:
            st.html(f'<p class="cardnote">Read: {escape(state["site_note"])}</p>')
    with right, card("site-generators"):
        card_title("2. Generators (optional)", "One row per unit. Leave empty for a load forecast without a "
                   "generator plan.")
        units = st.data_editor(state.get("site_units", [{"Name": "", "Capacity (kW)": None}]), num_rows="dynamic",
                               use_container_width=True, key="site_units_editor",
                               column_config={"Name": st.column_config.TextColumn(width="medium"),
                                              "Capacity (kW)": st.column_config.NumberColumn(min_value=1, format="%.1f")})
        parallel = st.checkbox("Units can run in parallel", value=False,
                               help="Allows any combination of units to share the load.")
        first, second = st.columns(2)
        reserve = first.slider("Reserve margin", 0, 30, 10, format="%d%%") / 100
        minimum_run = second.number_input("Minimum run (hours)", min_value=1, max_value=12, value=3)
    generators = [{"generator_id": str(row["Name"]).strip(), "usable_capacity_kw": float(row["Capacity (kW)"])}
                  for row in units if row.get("Name") and str(row["Name"]).strip() and row.get("Capacity (kW)")]
    ready = bool(state.get("site_net"))
    if st.button("Add the site", type="primary", disabled=not ready):
        sites = state.setdefault("sites", {})
        site_name = unique_site_name(name, sites)
        try:
            with st.spinner("Fitting the model on this site's history"):
                result = request_site_forecast(site_name, state["site_net"], generators, parallel, reserve,
                                               int(minimum_run), location.strip(), holidays == "Lebanon")
            sites[site_name] = {"result": result}
            for key in ("site_net", "site_note", "site_file", "site_name", "site_location", "site_units", "site_error"):
                state.pop(key, None)
            state["pending_site"] = site_name
            st.rerun()
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            state["site_error"] = str(detail)[:400]
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            state["site_error"] = f"Cannot reach the forecast service at {API_URL}."
    if not ready:
        st.html('<p class="cardnote">Upload a history file, or fill in the example, to enable this.</p>')
    if state.get("site_error"):
        notice("unavailable", state["site_error"])


def added_site_page(name):
    data = st.session_state["sites"][name]["result"]
    rows = [row for row in data["hourly"] if row["net_upper_kw"] is not None]
    day = datetime.fromisoformat(data["hourly"][0]["timestamp_local"])
    if rows:
        peak = max(rows, key=lambda row: row["net_upper_kw"])
        finding = (f"Plan for <b>{day:%A %d %B %Y}</b>, the day after the last reading. It covers up to "
                   f"<b>{peak['net_upper_kw']:.0f} kW</b> at {peak['timestamp_local'][11:16]}.")
    else:
        finding = f"No plan could be produced for {day:%A %d %B %Y}."
    place = data.get("location") or "Location not given"
    header(name, finding, f"{place} · holidays: {data.get('holiday_calendar', 'Lebanon')} · {data['history_days']} days of history")
    with st.sidebar:
        if st.button("Remove this site", use_container_width=True):
            del st.session_state["sites"][name]
            st.session_state["pending_site"] = AZM
            st.rerun()
    site_result(data)


AZM, ADD_SITE = "Azm", "+ Add a site"
VIEWS = {"Tomorrow": tomorrow_page, "Backtest": backtest_page, "Failure gallery": failure_page}


def main():
    st.set_page_config(page_title="Generator planner", layout="wide")
    st.html(CSS)
    state = st.session_state
    sites = state.setdefault("sites", {})
    options = [AZM, *sites, ADD_SITE]
    if state.get("pending_site") in options:
        state["nav_site"] = state.pop("pending_site")
    if state.get("nav_site") not in options:
        state["nav_site"] = AZM
    with st.sidebar:
        st.html('<div class="navhead">Sites</div>')
        site = st.radio("Sites", options, key="nav_site", label_visibility="collapsed")
        view = None
        if site == AZM:
            st.html('<div class="navhead">View</div>')
            view = st.radio("View", list(VIEWS), key="nav_view", label_visibility="collapsed")
        st.divider()
    if site == AZM:
        VIEWS[view]()
    elif site == ADD_SITE:
        new_site_page()
    else:
        added_site_page(site)

main()
