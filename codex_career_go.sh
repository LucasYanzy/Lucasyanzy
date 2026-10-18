#!/bin/bash
# 追加完整求职任务 → 等正在跑的「申请材料准备」做完 → 重启，让求职任务排在 Coding 前面
set -u
BASE="https://raw.githubusercontent.com/LucasYanzy/Lucasyanzy/295142b06b9c451fe7d06cd6ae7be7cc3c07b3a5"
CODEX=/opt/homebrew/bin/codex; [ -x "$CODEX" ] || CODEX="$(command -v codex)"
restore() { defaults write com.apple.CrashReporter DialogType crashreport 2>/dev/null; }
trap restore EXIT

echo "① 追加求职任务（已完成的不重做）"
curl -fsSL "$BASE/codex_career.py" | python3 || { echo "下载失败"; exit 1; }

echo "② 等当前的「申请材料准备」做完（每分钟检查一次）"
while pgrep -f "codex_auto.py --loop" >/dev/null; do
  if python3 - <<'PY'
import os, sys
log = open(os.path.expanduser("~/codex-auto/run.log"), encoding="utf-8", errors="replace").read().splitlines()
idx = max([i for i, l in enumerate(log) if "申请材料准备（不提交）（队列剩余" in l] or [-1])
if idx < 0:
    sys.exit(1)
after = log[idx + 1:]
done = any(l.startswith("[") and ("▶" in l or "结束" in l or "队列已全部完成" in l) for l in after)
sys.exit(0 if done else 1)
PY
  then echo "   ✅ 已完成，切换到新的求职任务"; break; fi
  echo "   $(date +%H:%M) 还在做，继续等…"; sleep 60
done
pkill -f "codex_auto.py --loop"; pkill -f "codex exec --skip-git-repo-check"; pkill -f "codex exec resume --skip-git-repo-check"; sleep 2

echo "③ 开始跑：实习就业（13 个新任务）→ Coding → 今日重点"
defaults write com.apple.CrashReporter DialogType none
python3 "$HOME/codex_auto.py" --loop --until 23:59 --codex "$CODEX" --model gpt-6.1-sol

echo "④ 同步 token tracker"
npx --yes tokentracker-cli sync
