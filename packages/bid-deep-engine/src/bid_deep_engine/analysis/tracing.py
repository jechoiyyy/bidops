"""Offline tracing seam. BidOps owns audit persistence; no telemetry transport."""
from contextlib import contextmanager
class NoticeTrace:
    trace_id = ""
    def update_metadata(self, **kwargs): pass
    def set_input(self, value): pass
    def set_output(self, value): pass
class NullTracer:
    enabled = False
    @contextmanager
    def notice_scope(self, **kwargs): yield NoticeTrace()
Tracer = NullTracer
NULL_TRACER = NullTracer()
def traced_parse(tracer, client, *, purpose, chunk=None, **kwargs):
    return client.parse(purpose=purpose, **kwargs)
