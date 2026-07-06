"""The sidebar: new chat, past conversations, recent data, the feedback log."""

from datetime import datetime

import streamlit as st

from ..storage import catalog, feedback


def _timestamp(iso_str: str) -> str:
    try:
        return datetime.fromisoformat(iso_str).strftime("%b %d, %H:%M")
    except ValueError:
        return iso_str


def render(active_conversation_id, session_id) -> None:
    with st.sidebar:
        if st.button("+ New chat", use_container_width=True, type="primary"):
            st.query_params.clear()
            st.session_state.pop("turns", None)
            st.rerun()

        st.divider()
        st.subheader("Conversations", anchor=False)
        try:
            conversations = catalog.list_conversations()
        except Exception:
            conversations = []
        if not conversations:
            st.caption("No conversations yet — ask a question to start one.")
        for summary in conversations:
            is_active = summary.conversation_id == active_conversation_id
            preview = summary.first_question
            if len(preview) > 45:
                preview = preview[:42] + "..."
            with st.container(border=True):
                st.markdown(f"{'🟢 ' if is_active else ''}**{preview}**")
                st.caption(f"{summary.turn_count} turn{'s' if summary.turn_count != 1 else ''} · "
                           f"{_timestamp(summary.last_activity_at)}")
                if not is_active:
                    if st.button("Open", key=f"conv_{summary.conversation_id}",
                                 use_container_width=True):
                        st.query_params["c"] = summary.conversation_id
                        st.session_state.pop("turns", None)
                        st.rerun()

        st.divider()
        with st.expander("Recently fetched data"):
            try:
                recent = catalog.list_all(session_id=session_id)[:10]
            except Exception:
                recent = []
            if not recent:
                st.caption("No datasets fetched yet.")
            for dataset in recent:
                st.markdown(f"**{dataset.description}**")
                st.caption(_timestamp(dataset.created_at))

        st.divider()
        try:
            records = feedback.list_feedback()
        except Exception:
            records = []
        with st.expander(f"💬 Feedback log ({len(records)})"):
            if not records:
                st.caption("No feedback submitted yet. Rate an answer to start.")
            else:
                st.download_button("⬇ Download feedback.txt", data=feedback.readable_text(),
                                   file_name="feedback.txt", use_container_width=True)
                for rec in records:
                    icon = {"up": "👍", "down": "👎"}.get(rec.get("rating"), "•")
                    q = rec.get("question", "")
                    if len(q) > 50:
                        q = q[:47] + "..."
                    with st.container(border=True):
                        st.markdown(f"{icon} **{q}**")
                        if rec.get("comment"):
                            st.caption(rec["comment"])
                        st.caption(_timestamp(rec.get("created_at", "")))
