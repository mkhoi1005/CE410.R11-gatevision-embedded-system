#!/usr/bin/env bash
# GATE VISION - chay web (Linux, macOS, Raspberry Pi). Cach dung: bash chay_web.sh
# Doi GV_DEV=0 neu muon chay that (khong co du lieu mau, khong co cong cu thu).
cd "$(dirname "$0")" || exit 1
export GV_DEV="${GV_DEV:-1}"
PORT="${PORT:-8000}"
PY=python3
command -v "$PY" >/dev/null 2>&1 || { echo "Khong tim thay python3. Hay cai Python 3.10 tro len."; exit 1; }
if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "Dang cai thu vien lan dau, doi mot chut..."
  "$PY" -m pip install -r server/requirements.txt || "$PY" -m pip install --break-system-packages -r server/requirements.txt || { echo "Cai thu vien that bai."; exit 1; }
fi
echo "Server dang chay tai http://localhost:$PORT (bam Ctrl+C de tat). Cho may khac trong mang LAN: HOST=0.0.0.0 bash chay_web.sh"
exec "$PY" -m uvicorn server.main:app --host "${HOST:-127.0.0.1}" --port "$PORT"
