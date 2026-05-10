#!/bin/bash
# 切換到腳本所在目錄（即專案資料夾）
cd "$(dirname "$0")"
poetry run jewelry-tool
