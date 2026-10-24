"""Speaker-labeled transcript -> graph. OWNER: Person A.

This will turn a "Speaker N: ..." transcript into graph nodes and edges (who was met, what was discussed, what
each side promised) through Person B's `app.graph.writes` seam. Nothing is built yet: the transcript itself is
saved to cache/transcripts/<session_id>.txt by the route, so no recording is lost while this is a stub.
"""

# TODO(A): build the graph from the transcript. Until then this writes nothing and reports "not_built".


def build(session_id: str, transcript: str) -> str:
    """Return a graph status for the session: "not_built" until the conversion exists."""
    return "not_built"
