"""Self-report UI component for Streamlit."""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from attentionos.storage.db import insert_self_report
from attentionos.storage.schema import SelfReport


def render_self_report_form(
    task_labels: list[str] | None = None,
) -> SelfReport | None:
    """Render a self-report form in Streamlit and return the submitted report.

    Args:
        task_labels: Available task categories for context.

    Returns:
        SelfReport if submitted, None otherwise.
    """
    st.markdown("### 📝 Self-Report")
    st.markdown(
        '<p style="color: #94a3b8; font-size: 0.9em;">'
        "Rate your current state. This helps build your personal model."
        "</p>",
        unsafe_allow_html=True,
    )

    with st.form("self_report_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            effectiveness = st.slider(
                "⚡ Perceived Effectiveness",
                min_value=1,
                max_value=5,
                value=3,
                help="1 = very unproductive, 5 = peak performance",
            )

        with col2:
            fatigue = st.slider(
                "😴 Perceived Fatigue",
                min_value=1,
                max_value=5,
                value=2,
                help="1 = fresh and energetic, 5 = exhausted",
            )

        col3, col4 = st.columns(2)

        with col3:
            difficulty = st.slider(
                "🎯 Task Difficulty (optional)",
                min_value=0,
                max_value=5,
                value=0,
                help="0 = skip, 1 = trivial, 5 = extremely difficult",
            )

        with col4:
            note = st.text_input(
                "📎 Note (optional)",
                max_chars=500,
                placeholder="e.g., stuck on a bug, meetings all morning...",
            )

        submitted = st.form_submit_button(
            "Submit Report",
            type="primary",
            use_container_width=True,
        )

        if submitted:
            report = SelfReport(
                timestamp=datetime.now(tz=UTC),
                perceived_effectiveness=effectiveness,
                perceived_fatigue=fatigue,
                task_difficulty=difficulty if difficulty > 0 else None,
                note=note.strip() if note.strip() else None,
            )

            try:
                insert_self_report(report)
                st.success("✅ Self-report saved!")
                return report
            except Exception as e:
                st.error(f"Failed to save report: {e}")

    return None
