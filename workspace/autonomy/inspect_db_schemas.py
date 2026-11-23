import sqlite3

conn_lex = sqlite3.connect('L:/LocalCoder/workspace/autonomy/fast_lexical_index.sqlite3')
cur_lex = conn_lex.cursor()
cur_lex.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Fast Lexical Tables:", cur_lex.fetchall())

conn_top = sqlite3.connect('L:/LocalCoder/workspace/autonomy/viv_code_topology.sqlite3')
cur_top = conn_top.cursor()
cur_top.execute("SELECT name FROM sqlite_master WHERE type='table'")
print("Topology Tables:", cur_top.fetchall())

for tbl in [r[0] for r in cur_top.fetchall()]:
    cur_top.execute(f"PRAGMA table_info({tbl})")
    print(f"Schema {tbl}:", [col[1] for col in cur_top.fetchall()])

conn_lex.close()
conn_top.close()
