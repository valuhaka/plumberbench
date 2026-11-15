"""Open a house for a job on the online play server: python scripts/pb_open.py JOB LEVEL SEED

The seed stays with the operator; the agent gets only the job name (see scripts/pb).
"""
import http.cookiejar
import json
import os
import sys
import urllib.request
from pathlib import Path

job, level, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
d = Path(os.environ.get("PB_JOBS", "jobs")) / job
d.mkdir(parents=True, exist_ok=True)
jar = http.cookiejar.MozillaCookieJar(str(d / "cookies.txt"))
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), urllib.request.ProxyHandler({}))
url = os.environ.get("PB_URL", "http://127.0.0.1:8080")
reply = json.load(opener.open(f"{url}/history?level={level}&seed={seed}"))
jar.save(ignore_discard=True)
print(job, "level", level, reply["log"][0][1].splitlines()[1])
