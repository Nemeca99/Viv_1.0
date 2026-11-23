import pathlib
import sqlite3
from drone_positive_store_v2 import PositiveStore
from drone_store_write_authority_v1 import make_write_authorizer


def open_positive_store(database_path, privacy_core, verify_receipt, body_gate=None, connector=None):
    """Open a positive store with authorization before access."""
    path = pathlib.Path(database_path)
    
    # Build authorizer and call it before opening the database
    authorize = make_write_authorizer(str(path), privacy_core, body_gate)
    authorize()  # Authorize before opening
    
    # Connect using connector if supplied, otherwise use sqlite3 directly
    if connector is not None:
        conn = connector(str(path))
    else:
        conn = sqlite3.connect(str(path))
    
    try:
        store = PositiveStore(conn, authorize, verify_receipt)
        return store
    except Exception as e:
        # Construction failed - close connection and re-raise
        conn.close()
        raise
