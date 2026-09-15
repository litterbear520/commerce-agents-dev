#!/usr/bin/env bash
# workspace 的安装脚本
#
#   ./scripts/install.sh            # requirements.txt：包本身 + 运行时依赖
#   ./scripts/install.sh dev        # requirements-dev.txt：加上 pytest 和 ruff
set -euo pipefail

cd "$(dirname "$0")/.."

if ! python3 -c 'import sys; sys.exit(0 if sys.prefix != sys.base_prefix else 1)' 2>/dev/null; then
  echo "warning: 没有激活 virtualenv；系统 Python 通常拒绝全局安装。" >&2
fi

case "${1:-all}" in
  all) pip install -r requirements.txt ;;
  dev) pip install -r requirements-dev.txt ;;
  *) echo "usage: $0 [all|dev]" >&2; exit 2 ;;
esac
