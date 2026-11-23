import json
from pathlib import Path
path=Path("opencode.json")
data=json.loads(path.read_text(encoding="utf-8"))
data["agents"]["build"]["temperature"]=0.0
path.write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
