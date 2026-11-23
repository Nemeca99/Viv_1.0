import pathlib
from typing import Optional, Callable, Any


def open_positive_store(
    database_path: str,
    privacy_core: Any,
    verify_receipt: Callable[[Any], bool],
    body_gate: Optional[Any] = None,
    connector: Optional[Callable[[str], Any]] = None,
) -> "PositiveStore":
    """Open a PositiveStore with authorization gates."""
    path = pathlib.Path(database_path).resolve()

    if not privacy_core.authorize_file_write(path):
        raise PermissionError("PrivacyCore denied write access")

    make_write_authorizer = __import__("drone_store_write_authority_v1", fromlist=["make_write_authorizer"]).make_write_authorizer
    authorize = make_write_authorizer(privacy_core, path)

    try:
        if connector is not None:
            conn = connector(str(path))
        else:
            conn = __import__("sqlite3").connect(str(path))

        PositiveStore(conn, authorize, verify_receipt)
        return PositiveStore(conn, authorize, verify_receipt)
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        raise
