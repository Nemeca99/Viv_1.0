import sqlite3

conn = sqlite3.connect('L:/LocalCoder/workspace/autonomy/viv_live_chat_history.sqlite3')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print("Chat History Tables:", tables)
for t in tables:
    cur.execute(f"PRAGMA table_info({t[0]})")
    print(f"Schema {t[0]}:", cur.fetchall())
    cur.execute(f"SELECT * FROM {t[0]} ORDER BY 1 DESC LIMIT 3")
    print(f"Recent entries in {t[0]}:", cur.fetchall())
conn.close()
