"""Plotly chart components for the AttentionOS dashboard."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from attentionos.sessions.metrics import DailySummary
from attentionos.storage.schema import Session

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------

# Curated palette for top applications
APP_COLORS = [
    "#6366f1",  # Indigo
    "#8b5cf6",  # Violet
    "#ec4899",  # Pink
    "#f43f5e",  # Rose
    "#f97316",  # Orange
    "#eab308",  # Yellow
    "#22c55e",  # Green
    "#14b8a6",  # Teal
    "#06b6d4",  # Cyan
    "#3b82f6",  # Blue
    "#a855f7",  # Purple
    "#64748b",  # Slate (fallback)
]

IDLE_COLOR = "rgba(100, 116, 139, 0.3)"  # Slate with transparency
FOCUS_HIGHLIGHT = "rgba(99, 102, 241, 0.15)"  # Indigo background


def _get_app_color(app_name: str, color_map: dict[str, str]) -> str:
    """Get a consistent color for an application name."""
    if app_name not in color_map:
        idx = len(color_map) % len(APP_COLORS)
        color_map[app_name] = APP_COLORS[idx]
    return color_map[app_name]


# ---------------------------------------------------------------------------
# Timeline chart
# ---------------------------------------------------------------------------


def render_timeline(
    sessions: Sequence[Session],
    target_date: date | None = None,
) -> go.Figure:
    """Render a horizontal timeline of work sessions for a day.

    Each session is a colored bar by application, idle periods are grey.
    Focus sessions get a subtle highlight.

    Args:
        sessions: Session objects for the day.
        target_date: The date to display (for axis limits).

    Returns:
        Plotly Figure object.
    """
    if target_date is None:
        target_date = date.today()

    color_map: dict[str, str] = {}
    fig = go.Figure()

    if not sessions:
        fig.add_annotation(
            text="No data for this day",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(size=18, color="#94a3b8"),
        )
        fig.update_layout(
            template="plotly_dark",
            height=200,
            margin=dict(l=20, r=20, t=40, b=20),
        )
        return fig

    # Add session bars
    for session in sessions:
        color = (
            IDLE_COLOR
            if session.is_idle
            else _get_app_color(session.process_name, color_map)
        )

        duration_min = session.duration_seconds / 60
        label = session.process_name.replace(".exe", "")

        hover_text = (
            f"<b>{label}</b><br>"
            f"Duration: {duration_min:.1f} min<br>"
            f"Keyboard: {session.total_keyboard_events}<br>"
            f"Mouse: {session.total_mouse_events}<br>"
            f"{'🎯 Focus' if session.is_focus else '💤 Idle' if session.is_idle else '📱 Active'}"
        )
        if session.task_label:
            hover_text += f"<br>Task: {session.task_label}"

        fig.add_trace(
            go.Bar(
                x=[duration_min],
                y=["Timeline"],
                base=[
                    (
                        session.ts_start
                        - datetime.combine(target_date, datetime.min.time())
                    ).total_seconds()
                    / 60
                ],
                orientation="h",
                marker=dict(
                    color=color,
                    line=dict(color="rgba(255,255,255,0.1)", width=0.5),
                ),
                name=label,
                text=label if duration_min > 5 else "",
                textposition="inside",
                textfont=dict(size=10, color="white"),
                hovertext=hover_text,
                hoverinfo="text",
                showlegend=False,
            )
        )

    # Layout
    fig.update_layout(
        template="plotly_dark",
        barmode="stack",
        height=120,
        margin=dict(l=20, r=20, t=10, b=30),
        xaxis=dict(
            title="Time (minutes from midnight)",
            range=[0, 24 * 60],
            dtick=60,
            ticktext=[f"{h:02d}:00" for h in range(25)],
            tickvals=[h * 60 for h in range(25)],
            gridcolor="rgba(255,255,255,0.05)",
        ),
        yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


# ---------------------------------------------------------------------------
# App distribution chart
# ---------------------------------------------------------------------------


def render_app_distribution(sessions: Sequence[Session]) -> go.Figure:
    """Render a donut chart showing time distribution across applications.

    Args:
        sessions: Session objects for the day.

    Returns:
        Plotly Figure with a donut chart.
    """
    app_times: dict[str, float] = {}
    for s in sessions:
        if not s.is_idle:
            name = s.process_name.replace(".exe", "")
            app_times[name] = app_times.get(name, 0.0) + s.duration_seconds / 60

    if not app_times:
        fig = go.Figure()
        fig.add_annotation(text="No active sessions", x=0.5, y=0.5, showarrow=False)
        return fig

    # Sort by time
    sorted_apps = sorted(app_times.items(), key=lambda x: x[1], reverse=True)
    labels = [a[0] for a in sorted_apps[:10]]
    values = [a[1] for a in sorted_apps[:10]]
    if len(sorted_apps) > 10:
        labels.append("Other")
        values.append(sum(a[1] for a in sorted_apps[10:]))

    colors = APP_COLORS[: len(labels)]

    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.5,
            marker=dict(colors=colors),
            textinfo="label+percent",
            textfont=dict(size=11),
            hovertemplate="<b>%{label}</b><br>%{value:.1f} min<br>%{percent}<extra></extra>",
        )
    )

    fig.update_layout(
        template="plotly_dark",
        height=350,
        margin=dict(l=20, r=20, t=20, b=20),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="right",
            x=1.2,
            font=dict(size=11),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


# ---------------------------------------------------------------------------
# Context switches over time
# ---------------------------------------------------------------------------


def render_context_switches(
    switch_data: list[tuple[int, int]],
) -> go.Figure:
    """Render context switch frequency over time.

    Args:
        switch_data: List of (minute_offset, switch_count) from metrics.

    Returns:
        Plotly Figure with an area chart.
    """
    if not switch_data:
        fig = go.Figure()
        fig.add_annotation(text="No switch data", x=0.5, y=0.5, showarrow=False)
        return fig

    minutes = [d[0] for d in switch_data]
    counts = [d[1] for d in switch_data]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=minutes,
            y=counts,
            mode="lines",
            fill="tozeroy",
            line=dict(color="#8b5cf6", width=2),
            fillcolor="rgba(139, 92, 246, 0.2)",
            hovertemplate="Minute %{x}<br>Switches: %{y}<extra></extra>",
        )
    )

    fig.update_layout(
        template="plotly_dark",
        height=250,
        margin=dict(l=40, r=20, t=10, b=40),
        xaxis=dict(
            title="Time (minutes)",
            gridcolor="rgba(255,255,255,0.05)",
        ),
        yaxis=dict(
            title="Context Switches",
            gridcolor="rgba(255,255,255,0.05)",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig


# ---------------------------------------------------------------------------
# Daily stats cards (as figure)
# ---------------------------------------------------------------------------


def render_daily_stats_figure(summary: DailySummary) -> go.Figure:
    """Render daily summary statistics as a compact indicator figure.

    Args:
        summary: DailySummary object.

    Returns:
        Plotly Figure with indicator traces.
    """
    fig = make_subplots(
        rows=1,
        cols=4,
        specs=[[{"type": "indicator"}] * 4],
    )

    active_hours = summary.total_active_seconds / 3600
    mean_focus_min = summary.mean_focus_block_sec / 60
    indicators = [
        ("Active Time", f"{active_hours:.1f}h", "#6366f1"),
        ("Focus Sessions", str(summary.focus_sessions), "#22c55e"),
        ("Avg Focus", f"{mean_focus_min:.0f} min", "#f97316"),
        ("Switches", str(summary.total_context_switches), "#ec4899"),
    ]

    for i, (title, value, color) in enumerate(indicators, 1):
        normalized_value = value.replace(".", "").replace("h", "").replace(" min", "")
        indicator_value = (
            float(value.replace("h", "").replace(" min", ""))
            if normalized_value.isdigit()
            else 0
        )
        fig.add_trace(
            go.Indicator(
                mode="number",
                value=indicator_value,
                title=dict(text=title, font=dict(size=13, color="#94a3b8")),
                number=dict(
                    suffix="" if value.isdigit() else "",
                    font=dict(size=28, color=color),
                ),
            ),
            row=1,
            col=i,
        )

    fig.update_layout(
        template="plotly_dark",
        height=120,
        margin=dict(l=20, r=20, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    return fig
