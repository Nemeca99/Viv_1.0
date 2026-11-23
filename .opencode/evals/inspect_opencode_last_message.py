import json
import pathlib
import sqlite3
session="ses_e27fa6715ffeEVOtDVsNMnWrQy"
path=pathlib.Path.home()/".local/share/opencode/opencode.db"
c=sqlite3.connect(f"file:{path.as_posix()}?mode=ro",uri=True)
for mid,raw in c.execute("SELECT id,data FROM session_message WHERE session_id=? AND type='assistant' ORDER BY seq DESC LIMIT 1",(session,)):
 print("MESSAGE",json.dumps(json.loads(raw),ensure_ascii=False))
 for ordinal,kind,part_raw in c.execute("SELECT ordinal,type,data FROM session_part WHERE message_id=? ORDER BY ordinal",(mid,)):
  part=json.loads(part_raw); print("PART",ordinal,kind,json.dumps(part,ensure_ascii=False)[:1500])
