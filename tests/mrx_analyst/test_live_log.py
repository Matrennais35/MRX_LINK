"""The live-log emit handler must be safe when events arrive from worker
threads (the orchestrator's parallel wave-1 fetches): Streamlit calls raise
NoSessionContext off the script thread, so worker events are buffered and
flushed on the next main-thread event. Regression test for a real live crash.
"""

from mrx_analyst.ui import app as ui_app


class _Recorder:
    def __init__(self):
        self.calls = []

    def update(self, **kw):
        self.calls.append(("update", kw))

    def markdown(self, text):
        self.calls.append(("markdown", text))


def test_worker_thread_events_are_buffered_then_flushed(monkeypatch):
    status, thinking, stream = _Recorder(), _Recorder(), _Recorder()
    emit = ui_app._make_emit(status, thinking, stream)

    # Main-thread event renders immediately.
    monkeypatch.setattr(ui_app, "get_script_run_ctx", lambda: object())
    emit("status", {"label": "Designing the MRX views…"})
    assert any("Designing the MRX views" in c[1] for c in thinking.calls if c[0] == "markdown")

    # Worker-thread events (no script context) must NOT touch Streamlit...
    thinking.calls.clear()
    monkeypatch.setattr(ui_app, "get_script_run_ctx", lambda: None)
    emit("fetch", {"stage": "fetching", "label": "overview view"})
    emit("error", {"message": "MRX 500"})
    assert thinking.calls == []          # nothing rendered from the worker
    assert status.calls == [("update", {"label": "Designing the MRX views…"})]

    # ...and they flush with the next main-thread event, in order.
    monkeypatch.setattr(ui_app, "get_script_run_ctx", lambda: object())
    emit("agent", {"role": "analyst", "output": {"reasoning": "compute attribution"}})
    rendered = thinking.calls[-1][1]
    assert "overview view" in rendered   # the buffered fetch line
    assert "MRX 500" in rendered         # the buffered error line
    assert "compute attribution" in rendered


def test_token_events_off_thread_are_dropped_not_crashing(monkeypatch):
    status, thinking, stream = _Recorder(), _Recorder(), _Recorder()
    emit = ui_app._make_emit(status, thinking, stream)
    monkeypatch.setattr(ui_app, "get_script_run_ctx", lambda: None)
    emit("token", {"text": "partial"})   # must not raise, must not render
    assert stream.calls == []
