"""Check database authorization order without opening or writing a disk DB."""
from types import SimpleNamespace

from drone_positive_store_factory_v1 import open_positive_store


class FakeConnection:
    def __init__(self, events):
        self.events = events
        self.sql = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=()):
        self.events.append("sql")
        self.sql.append(sql)
        return SimpleNamespace(rowcount=1)

    def close(self):
        self.events.append("close")


def make_privacy(events, allowed=True):
    return SimpleNamespace(authorize_file_write=lambda path: (
        events.append("privacy") or {"allowed": allowed}
    ))


def main():
    path = "E:/Viv/positive_memory/drone_positive_rag.sqlite3"

    events = []
    opens = []
    def connector(value):
        events.append("open")
        connection = FakeConnection(events)
        opens.append(connection)
        return connection

    def allow_body():
        events.append("body")
        return {"allowed": True, "disposition": "ALLOW_MIND_RUNTIME",
                "authority": "deterministic_aios_body_rust",
                "execution_boundary": "wsl_docker"}

    try:
        open_positive_store(path, make_privacy(events, False), lambda _: True,
                            allow_body, connector)
    except PermissionError:
        pass
    else:
        raise AssertionError("PrivacyCore denial accepted")
    assert "open" not in events and "body" not in events

    events.clear()
    def deny_body():
        events.append("body")
        return {"allowed": False, "disposition": "HOLD_MIND_RUNTIME"}
    try:
        open_positive_store(path, make_privacy(events), lambda _: True,
                            deny_body, connector)
    except PermissionError:
        pass
    else:
        raise AssertionError("Rust Body denial accepted")
    assert "open" not in events

    events.clear()
    store = open_positive_store(path, make_privacy(events),
                                lambda receipt: receipt == "verified",
                                allow_body, connector)
    assert events.index("open") > events.index("body")
    assert opens[-1].sql and "CREATE VIRTUAL TABLE" in opens[-1].sql[0]
    before = len(opens[-1].sql)
    try:
        store.add_fact("rejected", "a" * 64, "bad")
    except PermissionError:
        pass
    else:
        raise AssertionError("unverified receipt accepted")
    assert len(opens[-1].sql) == before
    assert store.add_fact("verified fact", "A" * 64, "verified") == 1
    assert any(sql.startswith("INSERT INTO positive_facts")
               for sql in opens[-1].sql)
    print("PASS: both gates precede connect; rejected receipt writes nothing")


if __name__ == "__main__":
    main()
