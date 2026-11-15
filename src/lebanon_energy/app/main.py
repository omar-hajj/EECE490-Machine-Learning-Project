"""Operator page: tomorrow's net-load forecast and the generator to run each hour.

Run with:  streamlit run src/lebanon_energy/app/main.py
The page only displays what the API returns; it holds no model of its own.
Meter history comes from the prepared hourly file (AZM_HISTORY_CSV); in real
use a live meter feed would replace it.
"""

import csv
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

import plotly.graph_objects as go
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
HISTORY_CSV = Path(os.environ.get("AZM_HISTORY_CSV", "outputs/baselines_confirmed_azm/hourly_data.csv"))
HISTORY_DAYS_SENT = 60
MISSING_OPTIONS = {"Nothing missing": 0, "Last 6 hours of meter data": 6,
                   "Last 24 hours of meter data": 24, "All meter history": None}

INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
FORECAST, BAND, ACTUAL = "#2a78d6", "rgba(42,120,214,0.18)", "#52514e"
# One hue, light to dark, in order of capacity: a bigger unit is a darker cell.
CAPACITY_STEPS = ["#cfe1f7", "#a6c8f0", "#74a9e6", "#2a78d6", "#1d5aa8", "#123c73"]
UNAVAILABLE = "#e6e5e1"


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


def forecast_figure(rows, actual_net, show_actual):
    hours = [datetime.fromisoformat(row["timestamp_local"]) for row in rows]
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=hours, y=[row["net_kw"] for row in rows], mode="lines", name="Forecast",
                                line=dict(color=FORECAST, width=2), hovertemplate="%{y:.0f} kW"))
    figure.add_trace(go.Scatter(x=hours, y=[row["net_upper_kw"] for row in rows], mode="lines",
                                name="Upper estimate (9 hours in 10 stay below)", fill="tonexty", fillcolor=BAND,
                                line=dict(color=FORECAST, width=1, dash="dot"), hovertemplate="%{y:.0f} kW"))
    if show_actual and any(value is not None for value in actual_net):
        figure.add_trace(go.Scatter(x=hours, y=actual_net, mode="lines+markers", name="What actually happened",
                                    line=dict(color=ACTUAL, width=2), marker=dict(size=6),
                                    hovertemplate="%{y:.0f} kW"))
    figure.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                         legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                         plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK))
    figure.update_xaxes(tickformat="%H:%M", dtick=3 * 3600 * 1000, showgrid=False, linecolor=GRID)
    figure.update_yaxes(title_text="Net load on the generators (kW)", gridcolor=GRID, zeroline=True,
                        zerolinecolor=GRID, rangemode="tozero")
    return figure


def generator_strip(rows, policy):
    """One cell per hour, labelled with the unit(s) to run; darker = larger capacity."""
    capacities = sorted({sum(policy["capacities_kw"][unit] for unit in option)
                         for option in policy["allowed_configurations"]})
    step = {capacity: CAPACITY_STEPS[min(index * (len(CAPACITY_STEPS) - 1) // max(len(capacities) - 1, 1),
                                         len(CAPACITY_STEPS) - 1)] for index, capacity in enumerate(capacities)}
    hours = [datetime.fromisoformat(row["timestamp_local"]) + timedelta(minutes=30) for row in rows]
    colours, labels, hover, text_colours = [], [], [], []
    for row in rows:
        capacity = row["generator"]["capacity_kw"]
        colour = step.get(capacity, UNAVAILABLE)
        colours.append(colour)
        labels.append(configuration_label(row))
        text_colours.append("#ffffff" if colour in CAPACITY_STEPS[3:] else INK)
        hover.append(f"{row['timestamp_local'][11:16]}<br>Run {labels[-1]}"
                     + (f" ({capacity:.0f} kW)<br>Needs to cover {row['generator']['required_capacity_kw']:.0f} kW"
                        if capacity else "<br>No recommendation"))
    figure = go.Figure(go.Bar(x=hours, y=[1] * len(rows), width=3600 * 1000 * 0.96, marker=dict(color=colours),
                              text=labels, textposition="inside", insidetextanchor="middle",
                              textfont=dict(color=text_colours, size=12), textangle=0,
                              hovertext=hover, hoverinfo="text", showlegend=False))
    figure.update_layout(height=110, margin=dict(l=10, r=10, t=4, b=10), bargap=0,
                         plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK),
                         uniformtext=dict(minsize=9, mode="show"))
    figure.update_xaxes(tickformat="%H:%M", dtick=3 * 3600 * 1000, showgrid=False,
                        range=[hours[0] - timedelta(minutes=30), hours[-1] + timedelta(minutes=30)])
    figure.update_yaxes(visible=False, range=[0, 1])
    return figure


def switch_blocks(rows):
    """Consecutive hours with the same recommendation, as (start, end, label)."""
    blocks = []
    for row in rows:
        label, hour = configuration_label(row), row["timestamp_local"][11:16]
        if blocks and blocks[-1][2] == label:
            blocks[-1][1] = hour
        else:
            blocks.append([hour, hour, label])
    return blocks


def main():
    st.set_page_config(page_title="Azm generator plan", page_icon="⚡", layout="wide")
    st.title("Azm generator plan")
    if not HISTORY_CSV.is_file():
        st.error(f"Meter history not found at `{HISTORY_CSV}`. Run `scripts/run_baselines.py` first.")
        st.stop()
    history = load_history(str(HISTORY_CSV), HISTORY_CSV.stat().st_mtime)
    last_reading = max(history["load"])
    latest_issue = (last_reading + timedelta(hours=1)).replace(hour=0, minute=0)

    with st.sidebar:
        st.header("Forecast day")
        earliest = date.fromisoformat(os.environ.get("AZM_FIRST_ISSUE_DATE", "2026-08-01"))
        day = st.date_input("Plan for", value=latest_issue.date(), min_value=earliest, max_value=latest_issue.date(),
                            help="The forecast is made at midnight at the start of this day.")
        st.header("Try a missing-data case")
        missing_label = st.radio("At midnight, what is missing?", list(MISSING_OPTIONS), index=0,
                                 help="Shows how the plan changes when the meter feed is late or down.")
        show_actual = st.toggle("Show what actually happened", value=False,
                                help="Only for past days. Never shown to the model.")
    issue = datetime.combine(day, datetime.min.time())
    try:
        data = request_forecast(issue, history, MISSING_OPTIONS[missing_label])
    except urllib.error.HTTPError as error:
        st.error(f"The forecast service refused this request: {error.read().decode('utf-8', 'replace')[:300]}")
        st.stop()
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        st.error(f"Cannot reach the forecast service at {API_URL}. Start it, then reload this page.")
        st.stop()

    status, rows, policy = data["input_status"], data["hourly"], data["generator_policy"]
    {"full": st.success, "fallback": st.warning, "unavailable": st.error}[status["level"]](status["message"])

    available = [row for row in rows if row["net_upper_kw"] is not None]
    if not available:
        st.stop()
    peak = max(available, key=lambda row: row["net_upper_kw"])
    largest = max(available, key=lambda row: row["generator"]["capacity_kw"] or 0)
    blocks = switch_blocks(rows)
    first, second, third = st.columns(3)
    first.metric("Highest net load to plan for", f"{peak['net_upper_kw']:.0f} kW", f"at {peak['timestamp_local'][11:16]}",
                 delta_color="off", delta_arrow="off")
    second.metric("Largest unit needed", configuration_label(largest),
                  f"{largest['generator']['capacity_kw']:.0f} kW" if largest["generator"]["capacity_kw"] else None,
                  delta_color="off", delta_arrow="off")
    third.metric("Generator changes during the day", max(len(blocks) - 1, 0))

    st.subheader(f"Net load, {day:%A %d %B %Y}")
    actual_net = [history["load"][stamp] - history["pv"][stamp]
                  if stamp in history["load"] and stamp in history["pv"] else None
                  for stamp in (datetime.fromisoformat(row["timestamp_local"]) for row in rows)]
    st.plotly_chart(forecast_figure(rows, actual_net, show_actual), use_container_width=True,
                    config={"displayModeBar": False})
    st.subheader("Generator to run each hour")
    st.plotly_chart(generator_strip(rows, policy), use_container_width=True, config={"displayModeBar": False})
    st.caption(f"Rule: {policy['rule']} Reserve margin {policy['reserve_margin_fraction']:.0%}. "
               "Capacities are the highest outputs seen in the data, not confirmed ratings. "
               "The operator keeps the final decision.")

    with st.expander("Plan as a list"):
        st.table([{"From": start, "To (hour starting)": end, "Run": label} for start, end, label in blocks])
    with st.expander("Hour-by-hour numbers"):
        st.dataframe([{"Hour": row["timestamp_local"][11:16],
                       "Net forecast (kW)": None if row["net_kw"] is None else round(row["net_kw"]),
                       "Upper estimate (kW)": None if row["net_upper_kw"] is None else round(row["net_upper_kw"]),
                       "Run": configuration_label(row), "Capacity (kW)": row["generator"]["capacity_kw"],
                       "Forecast method": row["net_method"],
                       **({"Actual net (kW)": None if actual is None else round(actual)} if show_actual else {})}
                      for row, actual in zip(rows, actual_net)], hide_index=True, use_container_width=True)
    with st.expander("Limits of this plan"):
        for line in data["limitations"]:
            st.markdown(f"- {line}")
        st.markdown(f"- Model trained on data before {data['model_training_end_exclusive'][:10]}; "
                    "September results are not yet evaluated.")


main()
