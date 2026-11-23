"""In-memory independent checks; never connects to persistent memory."""
import sqlite3
from drone_positive_store_v2 import PositiveStore


def main():
    conn = sqlite3.connect(':memory:')
    permission = [True]
    store = PositiveStore(conn, lambda: permission[0], lambda receipt: receipt == 'verified')
    store.add_fact('bounded engineering evidence', 'A' * 64, 'verified')
    rows = store.search('engineering')
    assert len(rows) == 1 and rows[0][1] == 'a' * 64
    before = conn.execute('SELECT count(*) FROM positive_facts').fetchone()[0]
    for receipt, grant in [('rejected', True), ('verified', False), ('verified', 1)]:
        permission[0] = grant
        try:
            store.add_fact('denied fact', 'b' * 64, receipt)
        except (ValueError, PermissionError):
            pass
        else:
            raise AssertionError('denied fact accepted')
        assert conn.execute('SELECT count(*) FROM positive_facts').fetchone()[0] == before
    fresh = sqlite3.connect(':memory:')
    try:
        PositiveStore(fresh, lambda: False, lambda receipt: True)
    except PermissionError:
        pass
    else:
        raise AssertionError('schema permission bypass')
    assert fresh.execute('SELECT count(*) FROM sqlite_master').fetchone()[0] == 0
    permission[0] = True
    for index in range(25):
        store.add_fact('engineering evidence', 'b' * 64, 'verified')
    assert len(store.search('engineering', 999)) == 20
    assert len(store.search('engineering', -1)) == 1
    print('PASS: retrieval, denied writes unchanged, schema denial, bounded search')


if __name__ == '__main__':
    main()
