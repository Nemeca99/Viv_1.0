import json
import pathlib
import sqlite3

sessions = [
    "ses_e27fa6715ffeEVOtDVsNMnWrQy",
    "ses_e27fc09e3ffedQrqNgiNUoxHL2",
    "ses_e27fd38e3ffeVwPVddyLE6tqMz",
    "ses_e27fc5804ffeqsKSGSk6v9Zd2",
    "ses_e27fa6715ffeEVOtDVsNMnWrQy",
]
path = pathlib.Path.home() / ".local/share/opencode/opencode.db"
connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
for session in dict.fromkeys(sessions):
    print(f"SESSION {session}")
    for row in connection.execute("SELECT type, seq, data FROM session_message WHERE session_id=? ORDER BY seq", (session,)):
        kind, seq, raw = row
        data = json.loads(raw)
        summary = {key: data.get(key) for key in ("role", "agent", "model", "finish", "finishReason", "error", "tokens", "time") if key in data}
        print(" MESSAGE", seq, kind, summary)
    for row in connection.execute("SELECT type, ordinal, data FROM session_part WHERE session_id=? ORDER BY time_created, ordinal", (session,)):
        kind, ordinal, raw = row
        data = json.loads(raw)
        summary = {key: data.get(key) for key in ("type", "name", "callID", "state", "text", "reasoning") if key in data}
        if "text" in summary and isinstance(summary["text"], str): summary["text"] = summary["text"][:180]
        print(" PART", ordinal, kind, summary)
