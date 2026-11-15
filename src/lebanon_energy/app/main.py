"""Operator page: tomorrow's plan, why, how it did on past days, and where it failed.

Run with:  streamlit run src/lebanon_energy/app/main.py

The page holds no model. The Tomorrow view shows what the API returns; the
Backtest page and Failure gallery show logged results:
  AZM_HISTORY_CSV    prepared hourly meter data (a live feed would replace it)
  AZM_BACKTEST_CSV   scripts/build_backtest_table.py
  AZM_FAILURES_JSON  scripts/analyse_errors.py
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
BACKTEST_CSV = Path(os.environ.get("AZM_BACKTEST_CSV", "outputs/walk_forward/backtest.csv"))
FAILURES_JSON = Path(os.environ.get("AZM_FAILURES_JSON", "outputs/error_analysis/results.json"))
HISTORY_DAYS_SENT = 60
MISSING_OPTIONS = {"Nothing missing": 0, "Last 6 hours of meter data": 6,
                   "Last 24 hours of meter data": 24, "All meter history": None}

INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
FORECAST, BAND, ACTUAL, BASELINE = "#2a78d6", "rgba(42,120,214,0.18)", "#0b0b0b", "#eb6834"
# One hue, light to dark, in order of capacity: a bigger unit is a darker cell.
CAPACITY_STEPS = ["#cfe1f7", "#a6c8f0", "#74a9e6", "#2a78d6", "#1d5aa8", "#123c73"]
UNAVAILABLE = "#e6e5e1"
PLAIN = dict(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font=dict(color=INK))
NO_TOOLBAR = {"displayModeBar": False}


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


def load_figure(hours, forecast, upper, actual=None, baseline=None, height=340):
    """Forecast line, shaded band up to the upper estimate, and optional actual and baseline lines."""
    figure = go.Figure()
    figure.add_trace(go.Scatter(x=hours, y=forecast, mode="lines", name="Forecast",
                                line=dict(color=FORECAST, width=2), hovertemplate="%{y:.0f} kW"))
    figure.add_trace(go.Scatter(x=hours, y=upper, mode="lines", name="Upper estimate (9 hours in 10 stay below)",
                                fill="tonexty", fillcolor=BAND, line=dict(color=FORECAST, width=1, dash="dot"),
                                hovertemplate="%{y:.0f} kW"))
    if baseline is not None:
        figure.add_trace(go.Scatter(x=hours, y=baseline, mode="lines", name="Baseline: same hour last week",
                                    line=dict(color=BASELINE, width=2, dash="dash"), hovertemplate="%{y:.0f} kW"))
    if actual is not None and any(value is not None for value in actual):
        figure.add_trace(go.Scatter(x=hours, y=actual, mode="lines+markers", name="What actually happened",
                                    line=dict(color=ACTUAL, width=2), marker=dict(size=6),
                                    hovertemplate="%{y:.0f} kW"))
    figure.update_layout(height=height, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                         legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), **PLAIN)
    figure.update_xaxes(tickformat="%H:%M", dtick=3 * 3600 * 1000, showgrid=False, linecolor=GRID)
    figure.update_yaxes(title_text="Net load on the generators (kW)", gridcolor=GRID, zeroline=True,
                        zerolinecolor=GRID, rangemode="tozero")
    return figure


def capacity_colours(capacities):
    ordered = sorted(capacities)
    last = len(CAPACITY_STEPS) - 1
    return {capacity: CAPACITY_STEPS[min(index * last // max(len(ordered) - 1, 1), last)]
            for index, capacity in enumerate(ordered)}


def strip_figure(hours, lanes, colours):
    """One row of hourly cells per lane; lanes are (name, [capacity], [label], [hover])."""
    figure = go.Figure()
    for name, capacities, labels, hover in lanes:
        fill = [colours.get(capacity, UNAVAILABLE) for capacity in capacities]
        figure.add_trace(go.Bar(
            y=[name] * len(hours), x=[3600 * 1000] * len(hours), base=[hour for hour in hours], orientation="h",
            marker=dict(color=fill, line=dict(color="#fcfcfb", width=2)), text=labels, textposition="inside",
            insidetextanchor="middle", textangle=0,
            textfont=dict(color=["#ffffff" if colour in CAPACITY_STEPS[3:] else INK for colour in fill], size=12),
            hovertext=hover, hoverinfo="text", showlegend=False))
    figure.update_layout(height=70 + 44 * len(lanes), margin=dict(l=10, r=10, t=4, b=10), barmode="overlay",
                         bargap=0.15, uniformtext=dict(minsize=9, mode="show"), **PLAIN)
    figure.update_xaxes(type="date", tickformat="%H:%M", dtick=3 * 3600 * 1000, showgrid=False,
                        range=[hours[0], hours[-1] + timedelta(hours=1)])
    figure.update_yaxes(autorange="reversed", showgrid=False)
    return figure


def switch_blocks(labels, hours):
    """Consecutive hours with the same recommendation, as [start, end, label]."""
    blocks = []
    for label, hour in zip(labels, hours):
        if blocks and blocks[-1][2] == label:
            blocks[-1][1] = hour.strftime("%H:%M")
        else:
            blocks.append([hour.strftime("%H:%M"), hour.strftime("%H:%M"), label])
    return blocks


def why_panel(drivers):
    st.subheader("Why this peak")
    if not drivers.get("available"):
        st.info(drivers.get("reason", "No explanation available."))
        return
    hour = drivers["timestamp_local"][11:16]
    st.markdown(f"The highest hour of the plan is **{hour}**: forecast **{drivers['forecast_kw']:.0f} kW**, "
                f"planned for **{drivers['upper_kw']:.0f} kW**. An average hour is "
                f"{drivers['average_level_kw']:.0f} kW. What moves this hour away from average:")
    for rank, driver in enumerate(drivers["drivers"], start=1):
        direction = "adds" if driver["effect_kw"] > 0 else "removes"
        st.markdown(f"{rank}. {driver['text']} — {direction} **{abs(driver['effect_kw']):.0f} kW**")
    st.markdown(f"Then a safety margin of **{drivers['margin_kw']:.0f} kW** is added, the upper range of the "
                f"forecast's errors at {hour} over recent days.")
    st.caption("These effects are exact for this model (a linear one): average + effects = forecast.")


def tomorrow_page(history):
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
        return
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        st.error(f"Cannot reach the forecast service at {API_URL}. Start it, then reload this page.")
        return

    status, rows, policy = data["input_status"], data["hourly"], data["generator_policy"]
    {"full": st.success, "fallback": st.warning, "unavailable": st.error}[status["level"]](status["message"])
    available = [row for row in rows if row["net_upper_kw"] is not None]
    if not available:
        return
    hours = [datetime.fromisoformat(row["timestamp_local"]) for row in rows]
    labels = [configuration_label(row) for row in rows]
    peak = max(available, key=lambda row: row["net_upper_kw"])
    largest = max(available, key=lambda row: row["generator"]["capacity_kw"] or 0)
    blocks = switch_blocks(labels, hours)
    first, second, third = st.columns(3)
    first.metric("Highest net load to plan for", f"{peak['net_upper_kw']:.0f} kW", f"at {peak['timestamp_local'][11:16]}",
                 delta_color="off", delta_arrow="off")
    second.metric("Largest unit needed", configuration_label(largest),
                  f"{largest['generator']['capacity_kw']:.0f} kW" if largest["generator"]["capacity_kw"] else None,
                  delta_color="off", delta_arrow="off")
    third.metric("Generator changes during the day", max(len(blocks) - 1, 0))

    st.subheader(f"Net load, {day:%A %d %B %Y}")
    actual_net = [history["load"][stamp] - history["pv"][stamp]
                  if stamp in history["load"] and stamp in history["pv"] else None for stamp in hours]
    st.plotly_chart(load_figure(hours, [row["net_kw"] for row in rows], [row["net_upper_kw"] for row in rows],
                                actual_net if show_actual else None), use_container_width=True, config=NO_TOOLBAR)
    st.subheader("Generator to run each hour")
    colours = capacity_colours({sum(policy["capacities_kw"][unit] for unit in option)
                                for option in policy["allowed_configurations"]})
    hover = [f"{row['timestamp_local'][11:16]}<br>Run {label}"
             + (f" ({row['generator']['capacity_kw']:.0f} kW)<br>Needs to cover "
                f"{row['generator']['required_capacity_kw']:.0f} kW" if row["generator"]["capacity_kw"] else "")
             for row, label in zip(rows, labels)]
    st.plotly_chart(strip_figure(hours, [("Run", [row["generator"]["capacity_kw"] for row in rows], labels, hover)],
                                 colours), use_container_width=True, config=NO_TOOLBAR)
    st.caption(f"Rule: {policy['rule']} Reserve margin {policy['reserve_margin_fraction']:.0%}; a dip shorter than "
               f"{policy['minimum_run_hours']} hours stays on the larger unit. Capacities are the highest outputs "
               "seen in the data, not confirmed ratings. The operator keeps the final decision.")
    why_panel(data["peak_drivers"])

    with st.expander("Plan as a list"):
        st.table([{"From": start, "To (hour starting)": end, "Run": label} for start, end, label in blocks])
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
        st.markdown(f"- Model trained on data before {data['model_training_end_exclusive'][:10]}; "
                    "September results are not yet evaluated.")


def all_capacity_colours(days):
    """One colour per capacity across the whole table, so a unit keeps its colour on every day."""
    return capacity_colours({row[key] for rows in days.values() for row in rows
                             for key in ("picked_capacity_kw", "needed_capacity_kw") if row[key] is not None})


def backtest_day(rows, colours, height=320):
    """Charts for one logged day; rows come from the backtest table."""
    hours = [row["stamp"] for row in rows]
    st.plotly_chart(load_figure(hours, [row["forecast_kw"] for row in rows], [row["upper_kw"] for row in rows],
                                [row["actual_kw"] for row in rows], [row["baseline_kw"] for row in rows], height),
                    use_container_width=True, config=NO_TOOLBAR)

    def lane(name, key, label_key, note):
        return (name, [row[key] for row in rows], [row[label_key] for row in rows],
                [f"{row['stamp']:%H:%M}<br>{note} {row[label_key] or 'nothing'}"
                 + (f"<br>{row['verdict']}" if row["verdict"] else "") for row in rows])

    st.plotly_chart(strip_figure(hours, [lane("Picked", "picked_capacity_kw", "picked", "Rule picked"),
                                         lane("Needed", "needed_capacity_kw", "needed", "Load needed")], colours),
                    use_container_width=True, config=NO_TOOLBAR)


def day_scores(rows):
    scored = [row for row in rows if row["actual_kw"] is not None and row["forecast_kw"] is not None]
    if not scored:
        return None
    count = len(scored)
    return {"model": sum(abs(row["actual_kw"] - row["forecast_kw"]) for row in scored) / count,
            "baseline": sum(abs(row["actual_kw"] - row["baseline_kw"]) for row in scored
                            if row["baseline_kw"] is not None) / count,
            "undersized": sum(row["verdict"] == "undersized" for row in rows),
            "oversized": sum(row["verdict"] == "oversized" for row in rows),
            "right": sum(row["verdict"] == "right-sized" for row in rows)}


def backtest_page():
    if not BACKTEST_CSV.is_file():
        st.error(f"Backtest table not found at `{BACKTEST_CSV}`. Run `scripts/walk_forward.py`, then "
                 "`scripts/build_backtest_table.py`.")
        return
    days = load_backtest(str(BACKTEST_CSV), BACKTEST_CSV.stat().st_mtime)
    usable = sorted(day for day, rows in days.items() if day_scores(rows))
    with st.sidebar:
        st.header("Past day")
        day = st.date_input("Show", value=usable[-1], min_value=usable[0], max_value=usable[-1],
                            help="Each day was forecast at midnight by a model fitted on earlier data only.")
    if day not in days or not day_scores(days[day]):
        st.info("No logged forecast for this day (meter data incomplete).")
        return
    scores = day_scores(days[day])
    st.subheader(f"{day:%A %d %B %Y}: forecast against what happened")
    first, second, third, fourth = st.columns(4)
    first.metric("Model error (average)", f"{scores['model']:.0f} kW")
    second.metric("Baseline error (average)", f"{scores['baseline']:.0f} kW")
    third.metric("Hours undersized", scores["undersized"])
    fourth.metric("Hours oversized", scores["oversized"])
    backtest_day(days[day], all_capacity_colours(days))
    st.caption("Picked: what the rule would have run, from the upper estimate. Needed: the smallest allowed "
               "configuration that covers the actual load. Darker means larger. Undersized means the picked "
               "unit's observed maximum was below the actual hourly load.")


def failure_page():
    if not FAILURES_JSON.is_file() or not BACKTEST_CSV.is_file():
        st.error("Failure gallery needs `scripts/analyse_errors.py` and `scripts/build_backtest_table.py` to be run.")
        return
    analysis = json.loads(FAILURES_JSON.read_text(encoding="utf-8"))["analysis"]
    days = load_backtest(str(BACKTEST_CSV), BACKTEST_CSV.stat().st_mtime)
    st.markdown(f"The three days with the largest average error among {analysis['hours']:,} logged hours "
                f"({analysis['first_hour'][:10]} to {analysis['last_hour'][:10]}). The explanations state what "
                "the data shows; they are not confirmed causes.")
    for rank, failure in enumerate(analysis["worst_days"], start=1):
        day = date.fromisoformat(failure["date"])
        st.subheader(f"{rank}. {failure['weekday']} {day:%d %B %Y}")
        st.markdown(f"**{failure['explanation']}**")
        first, second, third = st.columns(3)
        first.metric("Model error (average)", f"{failure['mae_kw']:.0f} kW")
        second.metric("Baseline error (average)", f"{failure['baseline_mae_kw']:.0f} kW")
        third.metric("Hours above the upper estimate", failure["hours_above_upper"])
        if day in days:
            backtest_day(days[day], all_capacity_colours(days), height=280)


def main():
    st.set_page_config(page_title="Azm generator plan", page_icon="⚡", layout="wide")
    with st.sidebar:
        page = st.radio("View", ["Tomorrow", "Backtest", "Failure gallery"], label_visibility="collapsed",
                        horizontal=True)
    st.title({"Tomorrow": "Azm generator plan", "Backtest": "Backtest: any past day",
              "Failure gallery": "Where the forecast failed"}[page])
    if page == "Tomorrow":
        if not HISTORY_CSV.is_file():
            st.error(f"Meter history not found at `{HISTORY_CSV}`. Run `scripts/run_baselines.py` first.")
            return
        tomorrow_page(load_history(str(HISTORY_CSV), HISTORY_CSV.stat().st_mtime))
    elif page == "Backtest":
        backtest_page()
    else:
        failure_page()


main()
