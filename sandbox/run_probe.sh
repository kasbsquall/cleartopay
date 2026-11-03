#!/usr/bin/env bash
# usage: runprobe.sh <name> <allow-rules> <task-json>
set -u
export PATH=$HOME/.local/bin:$PATH
R=~/runs/$1; rm -rf "$R"; mkdir -p "$R/in" "$R/out"; chmod 777 "$R/out"
printf '%s' "$3" > "$R/in/task.json"
S=$(date +%s.%N)
msb run -c 1 -m 2G --no-net --net-rule "$2" --tls-intercept --timeout 150s --no-tty --no-stdin \
  --mount-dir /home/ctp/cleartopay/sandbox/pylib:/opt/pylib:ro --mount-dir /home/ctp/cleartopay/sandbox:/opt/probe:ro \
  --mount-dir "$R/in":/in:ro --mount-dir "$R/out":/out \
  -e PYTHONPATH=/opt/pylib mcr.microsoft.com/playwright/python:v1.64.1-noble -- python3 /opt/probe/probe.py >"$R/msb.log" 2>&1
echo "== $1  total $(echo "$(date +%s.%N) - $S" | bc | cut -c1-5)s"
python3 -c "import json;d=json.load(open('$R/out/result.json'));d.pop('env_names');print(json.dumps(d)[:600])"
sha256sum "$R/out/screenshot.png" 2>/dev/null | cut -c1-16
