#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python scripts/stop_system.py
echo ""
echo "按任意鍵關閉視窗。"
read -k 1
