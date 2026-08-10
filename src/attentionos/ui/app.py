"""AttentionOS Dashboard — Streamlit application."""

from __future__ import annotations

import sys
from datetime import date, datetime

import streamlit as st

from attentionos.config import get_config
from attentionos.sessions.builder import build_sessions_for_day
from attentionos.sessions.metrics import (
    compute_context_switches,
    compute_daily_summary,
)
from attentionos.storage.db import get_daily_events, get_self_reports_range, init_db
from attentionos.ui.charts import (
    render_app_distribution,
    render_context_switches,
    render_timeline,
)
from attentionos.ui.self_report import render_self_report_form
from attentionos.ui.task_labels import render_task_label_selector

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AttentionOS",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Custom CSS for premium dark theme
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* Global */
    .stApp {
        font-family: 'Inter', sans-serif;
    }

    /* Metric cards */
    .metric-card {
        background: linear-gradient(135deg, rgba(99,102,241,0.1), rgba(139,92,246,0.05));
        border: 1px solid rgba(99,102,241,0.2);
        border-radius: 16px;
        padding: 20px 24px;
        text-align: center;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 32px rgba(99,102,241,0.15);
    }
    .metric-value {
        font-size: 2.2em;
        font-weight: 700;
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 4px;
    }
    .metric-label {
        font-size: 0.85em;
        color: #94a3b8;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Section headers */
    .section-header {
        font-size: 1.1em;
        font-weight: 600;
        color: #e2e8f0;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 1px solid rgba(148,163,184,0.1);
    }

    /* Self-report history */
    .report-item {
        background: rgba(30, 41, 59, 0.5);
        border: 1px solid rgba(148,163,184,0.1);
        border-radius: 12px;
        padding: 12px 16px;
        margin-bottom: 8px;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(15,23,42,0.95), rgba(30,41,59,0.9));
    }

    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


@st.cache_resource
def _init_database():
    """Initialize the database once."""
    config = get_config()
    init_db(config.db_path)
    return config


config = _init_database()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown(
        """
        <div style="text-align: center; padding: 20px 0;">
            <div style="font-size: 2.5em;">🧠</div>
            <h1 style="
                font-size: 1.5em;
                font-weight: 700;
                background: linear-gradient(135deg, #6366f1, #a855f7);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                margin: 8px 0 4px 0;
            ">AttentionOS</h1>
            <p style="color: #64748b; font-size: 0.8em; margin: 0;">
                Personal Performance Modeling
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.divider()

    # Date picker
    selected_date = st.date_input(
        "📅 Date",
        value=date.today(),
        max_value=date.today(),
    )

    st.divider()

    # Task label selector
    current_label = render_task_label_selector()

    st.divider()

    # Collector status
    st.markdown(
        '<p class="section-header">⚙️ Collector Status</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="color: #64748b; font-size: 0.85em;">'
        f"Data dir: <code>{config.data_dir}</code><br>"
        f"Polling: {config.collector.polling_interval_sec}s<br>"
        f"Idle threshold: {config.collector.idle_threshold_sec}s"
        "</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

# Load data for selected date
events = get_daily_events(selected_date)
sessions = build_sessions_for_day(events)
summary = compute_daily_summary(sessions)

# Header
st.markdown(
    f"""
    <div style="margin-bottom: 24px;">
        <h2 style="font-weight: 700; margin-bottom: 4px;">
            📊 Daily Report — {selected_date.strftime('%A, %B %d, %Y')}
        </h2>
        <p style="color: #64748b; font-size: 0.9em;">
            {len(events)} events • {len(sessions)} sessions •
            {summary.unique_apps} apps tracked
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---- Metric cards ----
col1, col2, col3, col4, col5 = st.columns(5)

active_h = summary.total_active_seconds / 3600
focus_min = summary.mean_focus_block_sec / 60
idle_h = summary.total_idle_seconds / 3600

metrics = [
    (col1, f"{active_h:.1f}h", "Active Time", "⚡"),
    (col2, str(summary.focus_sessions), "Focus Blocks", "🎯"),
    (col3, f"{focus_min:.0f} min", "Avg Focus", "📊"),
    (col4, str(summary.total_context_switches), "Switches", "🔄"),
    (col5, f"{idle_h:.1f}h", "Idle Time", "💤"),
]

for col, value, label, icon in metrics:
    with col:
        st.markdown(
            f"""
            <div class="metric-card">
                <div style="font-size: 1.5em; margin-bottom: 4px;">{icon}</div>
                <div class="metric-value">{value}</div>
                <div class="metric-label">{label}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("<br>", unsafe_allow_html=True)

# ---- Tabs ----
tab_timeline, tab_analytics, tab_report = st.tabs(
    ["📈 Timeline", "📊 Analytics", "📝 Self-Report"]
)

# ---- Timeline tab ----
with tab_timeline:
    st.markdown(
        '<p class="section-header">🕐 Activity Timeline</p>',
        unsafe_allow_html=True,
    )
    fig_timeline = render_timeline(sessions, selected_date)
    st.plotly_chart(fig_timeline, use_container_width=True, key="timeline")

    if sessions:
        st.markdown(
            '<p class="section-header">📋 Session Details</p>',
            unsafe_allow_html=True,
        )

        row_style = "display: flex; justify-content: space-between; align-items: center;"
        for s in sessions:
            duration_min = s.duration_seconds / 60
            status_icon = "🎯" if s.is_focus else "💤" if s.is_idle else "📱"
            app_name = s.process_name.replace(".exe", "")

            st.markdown(
                f"""
                <div class="report-item">
                    <div style="{row_style}">
                        <div>
                            {status_icon} <strong>{app_name}</strong>
                            <span style="color: #64748b; margin-left: 8px;">
                                {s.ts_start.strftime('%H:%M')} — {s.ts_end.strftime('%H:%M')}
                            </span>
                        </div>
                        <div style="color: #94a3b8;">
                            {duration_min:.1f} min
                            {f' • 🏷️ {s.task_label}' if s.task_label else ''}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

# ---- Analytics tab ----
with tab_analytics:
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown(
            '<p class="section-header">🍩 App Distribution</p>',
            unsafe_allow_html=True,
        )
        fig_apps = render_app_distribution(sessions)
        st.plotly_chart(fig_apps, use_container_width=True, key="app_dist")

    with col_right:
        st.markdown(
            '<p class="section-header">🔄 Context Switches Over Time</p>',
            unsafe_allow_html=True,
        )
        switch_data = compute_context_switches(sessions, window_minutes=15)
        fig_switches = render_context_switches(switch_data)
        st.plotly_chart(fig_switches, use_container_width=True, key="switches")

    # Task distribution
    if summary.task_distribution:
        st.markdown(
            '<p class="section-header">🏷️ Task Distribution</p>',
            unsafe_allow_html=True,
        )
        cols = st.columns(len(summary.task_distribution))
        for col, (label, pct) in zip(cols, summary.task_distribution.items(), strict=False):
            with col:
                st.metric(label, f"{pct * 100:.0f}%")

# ---- Self-Report tab ----
with tab_report:
    col_form, col_history = st.columns([1, 1])

    with col_form:
        render_self_report_form(task_labels=config.self_report.default_task_labels)

    with col_history:
        st.markdown(
            '<p class="section-header">📜 Today\'s Reports</p>',
            unsafe_allow_html=True,
        )

        day_start = datetime.combine(selected_date, datetime.min.time())
        day_end = datetime.combine(selected_date, datetime.max.time())
        reports = get_self_reports_range(day_start, day_end)

        if not reports:
            st.markdown(
                '<p style="color: #64748b; text-align: center; padding: 40px 0;">'
                "No reports yet today. Submit one to start tracking! 👈"
                "</p>",
                unsafe_allow_html=True,
            )
        else:
            for r in reversed(reports):
                eff_bar = (
                    "⚡" * r.perceived_effectiveness
                    + "⬜" * (5 - r.perceived_effectiveness)
                )
                fat_bar = "😴" * r.perceived_fatigue + "⬜" * (5 - r.perceived_fatigue)
                note_html = (
                    '<div style="color: #64748b; font-size: 0.85em; margin-top: 4px;">'
                    f"📎 {r.note}</div>"
                    if r.note
                    else ""
                )

                st.markdown(
                    f"""
                    <div class="report-item">
                        <div style="color: #94a3b8; font-size: 0.8em; margin-bottom: 4px;">
                            {r.timestamp.strftime('%H:%M')}
                        </div>
                        <div>Effectiveness: {eff_bar}</div>
                        <div>Fatigue: {fat_bar}</div>
                        {note_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for `attentionos-ui` command."""
    import subprocess
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", __file__, "--server.headless", "true"],
        check=True,
    )
