#!/bin/bash
# 一键处理：停掉旧运行 → 调整队列(IB→求职→Coding，关掉生活项目) → IB 结果导回原 IB 对话
#          → 跑求职/Coding（运行期间关掉崩溃弹窗）→ 结束后恢复弹窗并同步 token tracker
set -u
IB_ID="01a13156-6ff3-7981-b1ac-475884479aed"
IB_DIR="$HOME/Documents/Codex/2026-10-12/interactive-brokers-ibkr-plugin-app-69bc11db874881918718abaca20b68ce"
REORDER="https://raw.githubusercontent.com/LucasYanzy/Lucasyanzy/2a40a15fae0f1830b7c8ffd002d2b85ba6ba9e58/codex_reorder.py"
MODEL="gpt-6.1-sol"
CODEX=/opt/homebrew/bin/codex
[ -x "$CODEX" ] || CODEX="$(command -v codex)"

restore() { defaults write com.apple.CrashReporter DialogType crashreport 2>/dev/null; }
trap restore EXIT

echo "① 停掉正在跑的自动化"
pkill -f "codex_auto.py --loop"; pkill -f "codex exec --skip-git-repo-check"; pkill -f "codex exec resume --skip-git-repo-check"; sleep 2

echo "② 调整队列：IB → 实习就业 → Coding → 今日重点；关掉生活项目"
curl -fsSL "$REORDER" | python3 || { echo "下载队列配置失败"; exit 1; }
python3 - <<'EOF'
import json, os
p = os.path.expanduser("~/codex-auto/queue.json")
q = json.load(open(p, encoding="utf-8"))
for c in q["categories"]:
    c["enabled"] = c["name"] != "生活项目"
json.dump(q, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("   " + " → ".join(c["name"] + ("" if c["enabled"] else "(关)") for c in q["categories"]))
EOF

echo "③ 把 IB 结果导回原来的 IB 对话"
if [ -d "$IB_DIR" ] && [ -d "$HOME/codex-auto/ib_analysis" ]; then
  mkdir -p "$IB_DIR/codex_auto_ib_analysis" && cp -R "$HOME/codex-auto/ib_analysis/." "$IB_DIR/codex_auto_ib_analysis/"
  (cd "$IB_DIR" && env -u OPENAI_API_KEY -u CODEX_API_KEY "$CODEX" exec resume --skip-git-repo-check -m "$MODEL" "$IB_ID" \
    "自动化已完成 IB 持仓深度分析，全部结果已复制到本项目的 codex_auto_ib_analysis/ 文件夹（入口：IB_Final_Report.md、IB_Analysis.xlsx）。请读完后在本对话里用中文给我：1) 最重要的 5 条结论；2) 和我之前'准备加仓科技'计划的冲突；3) 需要我自己决定的 3 个问题。只读，不要下单、改单或修改账户。" \
    </dev/null 2>&1 | tail -25)
  echo "   ✅ 已写入 IB 对话（打开 Codex App 的 IB 对话查看；没显示就 Cmd+Q 重开 App）"
else
  echo "   ⚠️ 没找到 IB 项目文件夹或 ~/codex-auto/ib_analysis，跳过这一步"
fi

echo "④ 运行期间关闭崩溃弹窗（结束或 Ctrl+C 后自动恢复）"
defaults write com.apple.CrashReporter DialogType none

echo "⑤ 开始跑：实习就业 → Coding → 今日重点（求职结果在 ~/Desktop/G_Career/Codex_Career）"
python3 "$HOME/codex_auto.py" --loop --until 23:59 --codex "$CODEX" --model "$MODEL"

echo "⑥ 同步 token tracker"
npx --yes tokentracker-cli sync
