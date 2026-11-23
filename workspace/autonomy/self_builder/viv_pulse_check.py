import sqlite3
import json
from pathlib import Path

DB_PATH = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs\language-routes-20261107T222340465626Z\neuron_graph.sqlite3")

def viv_pulse_check(db_path: Path = DB_PATH) -> dict:
    """Viv's self-diagnostic pulse check."""
    if not db_path.exists():
        return {'status': 'OFFLINE', 'reason': 'Database file not found'}
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM neurons")
    total_neurons = cur.fetchone()[0]
    
    cur.execute("SELECT count(*) FROM links")
    total_links = cur.fetchone()[0]
    
    is_healthy = total_neurons >= 100000 and total_links >= 90000
    status = "PULSE STABLE (100k+ NEURONS)" if is_healthy else "PULSE DEGRADED"
    
    return {
        'status': status,
        'neurons': total_neurons,
        'links': total_links,
        'db_size_mb': round(db_path.stat().st_size / (1024*1024), 2)
    }

if __name__ == '__main__':
    res = viv_pulse_check()
    print("=== VIV SELF-BUILT INTERNAL PULSE REPORT ===")
    print(f"Status    : {res['status']}")
    print(f"Neurons   : {res['neurons']:,}")
    print(f"Links     : {res['links']:,}")
    print(f"Lattice   : {res['db_size_mb']} MB")
