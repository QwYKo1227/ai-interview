# Use one chunked recording session per interview

Each Interview has at most one active Recording Session, acquired through a short-lived reservation and owned by one assigned interviewer. Audio uploads continuously as ordered chunks and is sealed idempotently before AI analysis starts; this adds recovery and takeover logic but avoids duplicate recordings, unbounded browser memory, and total recording loss after a tab failure.
