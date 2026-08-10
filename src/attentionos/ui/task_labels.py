"""Task labels UI component for Streamlit."""

from __future__ import annotations

import streamlit as st

from attentionos.config import get_config


def render_task_label_selector() -> str | None:
    """Render a task label selector widget.

    Returns:
        Selected task label string, or None if 'None' is selected.
    """
    config = get_config()
    labels = config.self_report.default_task_labels

    st.markdown("### 🏷️ Current Task")
    st.markdown(
        '<p style="color: #94a3b8; font-size: 0.9em;">'
        "Tag your current activity to improve analytics."
        "</p>",
        unsafe_allow_html=True,
    )

    # Session state for custom labels
    if "custom_labels" not in st.session_state:
        st.session_state.custom_labels = []

    all_labels = ["None"] + labels + st.session_state.custom_labels

    col1, col2 = st.columns([3, 1])

    with col1:
        selected = st.selectbox(
            "Task category",
            options=all_labels,
            index=0,
            label_visibility="collapsed",
        )

    with col2, st.popover("➕"):
        new_label = st.text_input("New label", max_chars=64, key="new_task_label")
        new_label = new_label.strip()
        if st.button("Add", use_container_width=True) and new_label and new_label not in all_labels:
            st.session_state.custom_labels.append(new_label)
            st.rerun()

    if selected == "None":
        return None

    # Display current label with a colored badge
    label_colors = {
        "Coding": "#6366f1",
        "ML": "#8b5cf6",
        "Math": "#f97316",
        "English": "#22c55e",
        "Rest": "#64748b",
        "Meeting": "#ec4899",
        "Admin": "#eab308",
        "Other": "#94a3b8",
    }
    color = label_colors.get(selected, "#3b82f6")

    st.markdown(
        f'<div style="display:inline-block; background:{color}; color:white; '
        f'padding: 4px 16px; border-radius: 20px; font-size: 0.9em; '
        f'font-weight: 500; margin-top: 4px;">'
        f"🏷️ {selected}"
        f"</div>",
        unsafe_allow_html=True,
    )

    return selected
