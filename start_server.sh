#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# 寻找 Python
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

# 尝试 Anaconda 路径
if [ -z "$PYTHON" ]; then
    for conda_path in "$HOME/anaconda3/bin/python" "$HOME/miniconda3/bin/python" "/opt/anaconda3/bin/python"; do
        if [ -x "$conda_path" ]; then
            PYTHON="$conda_path"
            break
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo "[ERROR] Python not found."
    exit 1
fi

echo "Using Python: $PYTHON"
echo "Starting 寻迹故宫 server on http://127.0.0.1:8000"
echo "Report mode: http://127.0.0.1:8000/?report=1"
echo ""

exec "$PYTHON" backend/server.py
