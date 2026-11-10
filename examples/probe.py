"""Protocol demonstration only: replace observation with an independently designed probe."""
import json
import os
from pathlib import Path

request = json.loads(Path(os.environ['APK_LAB_REQUEST']).read_text())
Path(os.environ['APK_LAB_RESPONSE']).write_text(json.dumps({'observation': len(bytes.fromhex(request['hex']))}))
