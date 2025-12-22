#!/usr/bin/env bash
set -euo pipefail
shopt -s nullglob

WORKDIR="$(pwd)"

# 1순위: repo root에서 실행한 경우 (./llmgoat/challenges)
# 2순위: 이미 패키지 폴더(llmgoat/) 안에서 실행한 경우 (./challenges)
if [[ -d "$WORKDIR/llmgoat/challenges" ]]; then
  TARGET_DIR="$WORKDIR/llmgoat/challenges"
elif [[ -d "$WORKDIR/challenges" ]]; then
  TARGET_DIR="$WORKDIR/challenges"
else
  echo "[ERROR] challenges 폴더를 찾을 수 없습니다."
  echo "  - 찾는 후보:"
  echo "    1) $WORKDIR/llmgoat/challenges"
  echo "    2) $WORKDIR/challenges"
  echo "  - 현재 작업 폴더: $WORKDIR"
  exit 1
fi

for f in "$TARGET_DIR"/a0{4..9}_*.py "$TARGET_DIR"/a10_*.py; do
  echo "===== $f ====="
  sed -n '1,260p' "$f"
done
