#!/usr/bin/env python3
"""
codex_manual.py — 把 codex_auto 队列里的任务导出成可以直接粘贴到 Codex App 新对话里的说明，方便多开对话并行跑。

  python3 ~/codex_manual.py            导出「实习就业」「今日重点」的任务说明，并从自动队列里移除这两类（避免重复做）
  python3 ~/codex_manual.py --copy 2   把第 2 个任务说明复制到剪贴板，去 Codex App 新建对话粘贴即可
  python3 ~/codex_manual.py --restore  把这两类放回自动队列
"""
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, "codex-auto")
QUEUE = os.path.join(BASE, "queue.json")
OUT = os.path.join(BASE, "manual")
CATS = ["实习就业", "今日重点"]

sys.path.insert(0, HOME)
try:
    from codex_auto import SAFETY  # 复用同一套安全规则
except Exception:
    SAFETY = "\n## 安全规则\n不要提交申请、不要发邮件/消息、不要购买、不要交易、不要 git push、不要删除用户文件。\n"


def load():
    with open(QUEUE, encoding="utf-8") as f:
        return json.load(f)


def save(q):
    with open(QUEUE, "w", encoding="utf-8") as f:
        json.dump(q, f, ensure_ascii=False, indent=2)


def export():
    q = load()
    os.makedirs(OUT, exist_ok=True)
    files = []
    for c in q["categories"]:
        if c.get("name") not in CATS:
            continue
        for t in c.get("tasks", []):
            d = t.get("dir") or "~/codex-auto/work"
            text = (f"# 任务：{t['name']}\n工作目录 `{d}`（不存在就先创建）。\n\n{t.get('prompt', '')}\n"
                    + SAFETY.replace("用户在睡觉/不在电脑前。**不要提问、不要等确认**，按最合理的假设继续，并把假设写下来。",
                                     "遇到不确定的地方先按最合理的假设继续，并把假设写下来。"))
            path = os.path.join(OUT, f"{len(files) + 1:02d}_{t['name']}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            files.append((path, c["name"], t["name"], d))
        c["enabled"] = False
    save(q)
    print(f"✅ 已导出 {len(files)} 个任务说明到 {OUT}，并从自动队列里移除了：{'、'.join(CATS)}\n")
    for i, (p, cat, name, d) in enumerate(files, 1):
        print(f"  {i}. [{cat}] {name}    （工作目录 {d}）")
    print("\n下一步：python3 ~/codex_manual.py --copy 1  → 在 Codex App 新建对话（工作目录选上面那个）→ 粘贴 → 发送")


def copy(n):
    files = sorted(f for f in os.listdir(OUT) if f.endswith(".md"))
    p = os.path.join(OUT, files[n - 1])
    with open(p, encoding="utf-8") as f:
        subprocess.run(["pbcopy"], input=f.read().encode("utf-8"))
    print(f"📋 已复制：{files[n - 1]}")


def restore():
    q = load()
    for c in q["categories"]:
        if c.get("name") in CATS:
            c["enabled"] = True
    save(q)
    print("✅ 已把「实习就业」「今日重点」放回自动队列")


if __name__ == "__main__":
    if "--copy" in sys.argv:
        copy(int(sys.argv[sys.argv.index("--copy") + 1]))
    elif "--restore" in sys.argv:
        restore()
    else:
        export()
