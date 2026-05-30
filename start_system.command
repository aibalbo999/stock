#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python scripts/start_system.py --open-browser
echo ""
echo "系統啟動流程已結束。服務會在背景持續執行。"
echo "可關閉這個視窗；需要停止時雙擊 stop_system.command。"
echo "按任意鍵關閉視窗。"
read -k 1
