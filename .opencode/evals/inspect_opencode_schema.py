import pathlib
import sqlite3

path = pathlib.Path.home() / ".local/share/opencode/opencode.db"
connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
    columns = connection.execute(f'PRAGMA table_info("{name}")').fetchall()
    print(f"TABLE {name}: {columns}")
