#!/usr/bin/env python3
"""
codex_night.py — 等到 Codex 额度重置(默认本地时间 02:38)后，全程调用 Codex:
  1) 续跑 Externship 里未完成的两个价格对比任务，并制作表格(xlsx + csv)
  2) 用剩余的 5 小时额度，循环深度分析 IB 持仓，直到额度用完或 5 小时窗口结束

用法(在你自己的电脑上，终端里):
  python3 codex_night.py --dry-run      # 先看看找到的会话对不对(强烈建议先跑)
  python3 codex_night.py                # 正式运行：等到 02:38 后自动开始
  python3 codex_night.py --now          # 立即开始(测试用)
可选:
  --at 02:38                  重置时间(本地时间)
  --externship-ids ID1,ID2    手动指定 Externship 会话 ID
  --ib-id ID                  手动指定 IB 持仓会话 ID
  --model MODEL               指定模型(默认用你 config.toml 里的)

运行期间会阻止电脑睡眠(屏幕可以熄灭)。Mac 请插电源、不要合盖。
"""
import argparse
import datetime as dt
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time

EXTERNSHIP_KEYS = ["externship", "价格对比", "比价", "price comparison", "price compare"]
IB_KEYS = ["ibkr", "interactive brokers", "盈透", "ib持仓", "ib 持仓", "持仓", "portfolio", "positions"]
LIMIT_RE = re.compile(r"hit your usage limit|usage_limit_reached|usage limit\. |rate limit reached", re.I)

IB_TOPICS = [
    ("overview", "持仓总览与集中度：每个标的的权重、行业/地区/币种/资产类别暴露、前五大集中度、HHI 指数，用表格呈现"),
    ("fundamentals", "逐个持仓的基本面与估值：业务概况、最近四个季度财报要点、营收/利润增速、PE/PS/EV-EBITDA/FCF yield 与历史区间及同行对比"),
    ("technicals", "技术面与动量：趋势、50/200 日均线、支撑阻力、RSI、相对大盘强弱、近 1/3/6/12 个月涨跌幅"),
    ("risk", "组合风险量化：写 Python 脚本拉取历史价格，计算波动率、Beta、最大回撤、相关性矩阵、95%/99% VaR 与 CVaR、风险贡献度"),
    ("stress", "情景压力测试：利率上行 100bp、经济衰退、科技股回调 20%、美元走强 10%、2020 年 3 月与 2022 年重演，估算每个情景下组合与单票损益"),
    ("catalysts", "催化剂日历：未来 90 天每个持仓的财报日、除息日、FOMC/CPI/非农等宏观事件，以及各自可能的影响"),
    ("hedging", "期权与对冲方案：保护性看跌、领口策略、备兑开仓、指数对冲，给出具体行权价/到期日示例和成本估算"),
    ("rebalance", "再平衡与仓位优化：当前权重 vs 均值方差/风险平价/最小方差的目标权重，给出具体调仓清单和理由"),
    ("tax_cost", "税务与成本：未实现盈亏、税损收割机会、wash sale 规则注意事项、IB 佣金与汇率成本"),
    ("income_cash", "收益与现金：分红收益率、分红安全性、现金/保证金使用情况、利息收入与融资成本"),
    ("thesis", "逐个持仓的看多/看空论点、关键监控指标、止损/加仓触发条件"),
    ("devils_advocate", "魔鬼代言人：逐条挑战前面所有报告的结论，找出遗漏的风险和过于乐观的假设"),
]


def log(msg, fh=None):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    if fh:
        fh.write(line + "\n")
        fh.flush()


# ---------------------------------------------------------------- keep awake
class KeepAwake:
    """阻止系统睡眠(允许熄屏)。"""

    def __init__(self):
        self.proc = None

    def __enter__(self):
        system = platform.system()
        try:
            if system == "Darwin":
                self.proc = subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())])
            elif system == "Windows":
                import ctypes
                ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            elif shutil.which("systemd-inhibit"):
                self.proc = subprocess.Popen(
                    ["systemd-inhibit", "--what=sleep:idle", "--why=codex_night", "sleep", "infinity"])
        except Exception as e:  # 不致命
            print(f"[warn] 无法阻止睡眠: {e}")
        return self

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()
        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            except Exception:
                pass


# ---------------------------------------------------------------- sessions
def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")


def parse_session(path):
    sid, cwd, msgs = None, None, []
    seen = set()
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", os.path.basename(path))
    if m:
        sid = m.group(1)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                try:
                    obj = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                p = obj.get("payload") if isinstance(obj.get("payload"), dict) else obj
                if obj.get("type") == "session_meta" or (sid is None and "instructions" in obj and "id" in obj):
                    sid = p.get("id") or sid
                    cwd = p.get("cwd") or cwd
                    continue
                role, text = None, None
                if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
                    role = p["role"]
                    parts = [c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict)]
                    text = "\n".join(t for t in parts if t)
                elif p.get("type") == "user_message":
                    role, text = "user", p.get("message", "")
                if not text or text.lstrip().startswith("<") or text.startswith("# AGENTS.md"):
                    continue
                key = (role, text[:500])
                if key in seen:
                    continue
                seen.add(key)
                msgs.append((role, text))
    except OSError:
        return None
    if not sid:
        return None
    first_user = next((t for r, t in msgs if r == "user"), "")
    if first_user.startswith("The following is the Codex agent history"):
        return None  # Codex 自动审批产生的子会话，不是真正的对话
    return {"id": sid, "cwd": cwd, "path": path, "mtime": os.path.getmtime(path), "msgs": msgs}


def all_sessions():
    home = codex_home()
    files = glob.glob(os.path.join(home, "sessions", "**", "*.jsonl"), recursive=True)
    files += glob.glob(os.path.join(home, "archived_sessions", "**", "*.jsonl"), recursive=True)
    out = []
    for fp in files:
        s = parse_session(fp)
        if s and s["msgs"]:
            out.append(s)
    out.sort(key=lambda s: s["mtime"], reverse=True)
    return out


def score(session, keys, cwd_keys=()):
    text = "\n".join(t for r, t in session["msgs"] if r == "user").lower()
    cwd = (session.get("cwd") or "").lower()
    return sum(text.count(k) for k in keys) + 100 * sum(k in cwd for k in cwd_keys)


def find_by_id(sessions, sid):
    for s in sessions:
        if s["id"] == sid:
            return s
    return {"id": sid, "cwd": None, "path": None, "mtime": 0, "msgs": []}


def pick_sessions(args):
    sessions = all_sessions()
    if args.externship_ids:
        ext = [find_by_id(sessions, i.strip()) for i in args.externship_ids.split(",") if i.strip()]
    else:
        ext = [s for s in sessions if score(s, EXTERNSHIP_KEYS, ["externship"]) > 0]
        ext = sorted(ext, key=lambda s: (score(s, EXTERNSHIP_KEYS, ["externship"]) >= 100, s["mtime"]),
                     reverse=True)[:2]
    if args.ib_id:
        ib = find_by_id(sessions, args.ib_id)
    else:
        ext_ids = {s["id"] for s in ext}
        ck = ["interactive-brokers", "ibkr"]
        cands = [s for s in sessions if s["id"] not in ext_ids and score(s, IB_KEYS, ck) > 0]
        cands.sort(key=lambda s: (score(s, IB_KEYS, ck) >= 100, s["mtime"]), reverse=True)
        ib = cands[0] if cands else None
    return sessions, ext, ib


def find_codex(override=None):
    if override:
        return [override]
    c = shutil.which("codex")
    if c:
        return [c]
    home = os.path.expanduser("~")
    pats = ["/Applications/Codex*.app/Contents/Resources/codex",
            "/Applications/Codex*.app/Contents/Resources/*/codex",
            "/Applications/Codex*.app/Contents/Resources/**/bin/codex",
            home + "/Applications/Codex*.app/Contents/Resources/**/codex",
            "/opt/homebrew/bin/codex", "/usr/local/bin/codex",
            home + "/.nvm/versions/node/*/bin/codex", home + "/.npm-global/bin/codex",
            home + "/.local/bin/codex", home + "/.codex/bin/codex"]
    for pat in pats:
        for f in sorted(glob.glob(pat, recursive=True)):
            if os.path.isfile(f) and os.access(f, os.X_OK):
                return [f]
    npx = shutil.which("npx")
    if npx:  # 和 App 共用 ~/.codex 里的登录
        return [npx, "-y", "@openai/codex@latest"]
    return None


def describe(s):
    first = next((t for r, t in s["msgs"] if r == "user"), "")
    first = re.sub(r"\s+", " ", first)[:80]
    when = dt.datetime.fromtimestamp(s["mtime"]).strftime("%m-%d %H:%M") if s["mtime"] else "?"
    return f"{s['id']}  [{when}]  cwd={s['cwd']}  首条: {first}"


def dump_transcript(s, path, limit=300_000):
    parts = [f"# Codex 会话记录 {s['id']}\n\n原工作目录: {s['cwd']}\n"]
    for role, text in s["msgs"]:
        parts.append(f"\n## {'用户' if role == 'user' else 'Codex'}\n\n{text}\n")
    body = "".join(parts)
    if len(body) > limit:  # 保留开头和结尾
        body = body[: limit // 3] + "\n\n...(中间省略)...\n\n" + body[-2 * limit // 3:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


# ---------------------------------------------------------------- codex runner
class Runner:
    def __init__(self, codex, model, logfh, workdir):  # codex: list
        self.codex, self.model, self.logfh, self.workdir = codex, model, logfh, workdir
        self.n = 0

    def base_cfg(self, writable=None):
        cfg = ["-c", 'approval_policy="never"',
               "-c", 'sandbox_mode="workspace-write"',
               "-c", "sandbox_workspace_write.network_access=true",
               "-c", 'web_search="live"',
               "-c", 'model_reasoning_effort="high"']
        roots = [r for r in (writable or []) if r]
        if roots:
            cfg += ["-c", "sandbox_workspace_write.writable_roots=" + json.dumps(roots)]
        if self.model:
            cfg += ["-m", self.model]
        return cfg

    def prompt_file(self, name, text):
        self.n += 1
        path = os.path.join(self.workdir, "prompts", f"{self.n:02d}_{name}.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        # 命令行只传一行 ASCII 指令，真正的内容放文件里(避免 Windows 引号/换行问题)
        return (f"Read the file {path} and carry out every instruction in it exactly. "
                "The user is asleep: never ask questions or wait for confirmation; make reasonable "
                "assumptions, write them down, and keep going until everything is done.")

    def run(self, argv, cwd, timeout_min=90):
        """返回 (status, output)。status: ok / limit / fail"""
        cmd = self.codex + argv
        log("$ " + " ".join(a if len(a) < 120 else a[:117] + "..." for a in cmd), self.logfh)
        try:
            proc = subprocess.Popen(cmd, cwd=cwd if cwd and os.path.isdir(cwd) else self.workdir,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        except OSError as e:
            log(f"启动 codex 失败: {e}", self.logfh)
            return "fail", ""
        lines = []

        def reader():
            for line in proc.stdout:
                lines.append(line)
                self.logfh.write(line)
                self.logfh.flush()
                sys.stdout.write(line)
                sys.stdout.flush()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        try:
            proc.wait(timeout=timeout_min * 60)
        except subprocess.TimeoutExpired:
            log(f"单次运行超过 {timeout_min} 分钟，终止", self.logfh)
            proc.kill()
            proc.wait()
        t.join(timeout=10)
        out = "".join(lines)
        if LIMIT_RE.search("".join(lines[-40:])):
            return "limit", out
        return ("ok" if proc.returncode == 0 else "fail"), out

    def resume(self, sid, prompt, cwd, writable=None, out_file=None):
        extra = ["-o", out_file] if out_file else []
        argv = ["exec", "resume", "--skip-git-repo-check"] + self.base_cfg(writable) + extra + [sid, prompt]
        st, out = self.run(argv, cwd)
        if st == "fail":  # 退回最简参数再试一次
            log("resume 失败，用最简参数重试", self.logfh)
            st, out = self.run(["exec", "resume", sid, prompt] + [], cwd)
        return st, out

    def fresh(self, prompt, cwd, writable=None, out_file=None):
        extra = ["-o", out_file] if out_file else []
        argv = ["exec", "--skip-git-repo-check", "-C", cwd] + self.base_cfg(writable) + extra + [prompt]
        st, out = self.run(argv, cwd)
        if st == "fail":
            log("exec 失败，用最简参数重试", self.logfh)
            st, out = self.run(["exec", "--skip-git-repo-check", "-s", "workspace-write", "-C", cwd, prompt], cwd)
        return st, out


# ---------------------------------------------------------------- prompts
def externship_prompt(deliver_dir, transcript):
    return f"""# 任务：完成 Externship 未完成的部分并制作表格

现在是 Codex 额度重置后的自动续跑。用户在睡觉，**不要提问、不要等确认**，遇到不确定的地方按最合理的假设继续，并把假设记下来。

1. 回顾本对话（完整记录也备份在 `{transcript}`）中的 Externship 项目——两个价格对比任务。逐条列出任务要求，判断哪些已完成、哪些没完成。
2. 把所有未完成的部分全部做完。需要最新价格就联网查（记下来源网址和查询时间）；查不到的标注"未获取"并说明原因，不要编造数字。
3. 制作表格：
   - 任务里规定了表格的列、格式或模板，就**严格按任务要求**来；
   - 没有规定的话，自己设计清晰的对比表：商品/服务、各渠道价格、单位价格、差价、差价百分比、最低价渠道、数据来源、查询日期；
   - 输出 `.xlsx`（用 openpyxl 或 pandas，没有就 `pip install --user openpyxl`；表头加粗、冻结首行、列宽自适应、价格列用货币格式、最低价高亮），同时输出同样内容的 `.csv`；
   - 两个任务各一个工作表，再加一个"汇总"工作表。
4. 所有交付物保存到 `{deliver_dir}`（项目里原来就有约定的输出位置，就再复制一份过去）。
5. 最后写 `{deliver_dir}/SUMMARY.md`：完成了什么、表格说明、数据来源和日期、做了哪些假设、仍未完成的部分及原因。
"""


def ib_extract_prompt(ana_dir, transcript):
    return f"""# 任务：整理 IB 持仓

用户在睡觉，不要提问。根据本对话（完整记录也备份在 `{transcript}`）中用户给出的 Interactive Brokers (IB) 持仓：

1. 把持仓**原样、完整**整理成 `{ana_dir}/holdings.md`（Markdown 表格：代码、名称、资产类型、数量、成本价、现价、市值、未实现盈亏、币种、占比，以及原始数据里的其他字段）和 `{ana_dir}/holdings.csv`。缺的字段留空，不要编造。
2. 在 `{ana_dir}/00_raw_notes.md` 里记下对话中用户提到的投资目标、风险偏好、限制条件和关心的问题。
3. 最后一条回复里简单说明一共多少个持仓、总市值多少。
"""


def ib_topic_prompt(ana_dir, idx, slug, topic):
    return f"""# IB 持仓深度分析 · 第 {idx} 轮：{slug}

工作目录 `{ana_dir}`。用户在睡觉，不要提问。

1. 先读 `holdings.md`、`holdings.csv`、`00_raw_notes.md`，再浏览已有的分析报告（`*.md`），**不要重复**已经做过的内容，可以引用。
2. 本轮专题：**{topic}**
3. 尽量联网获取最新行情、财报、新闻、期权链等数据（注明来源和获取时间）；需要计算的话，在 `scripts/` 下写 Python 脚本并运行（可以 `pip install --user yfinance pandas numpy openpyxl`）。拿不到数据就明确写出来，用已有数据继续，不要编造。
4. 把结果写到 `{idx:02d}_{slug}.md`：要深入、量化、多用表格，结尾写"关键结论"和"建议行动"。
5. 更新 `IB_Final_Report.md`（没有就新建）：把本轮的关键结论合并进对应章节，保持它是一份完整、最新的综合报告（执行摘要放最前面）。
"""


def ib_final_prompt(ana_dir):
    return f"""# IB 持仓 · 综合报告与表格

工作目录 `{ana_dir}`。用户在睡觉，不要提问。

1. 通读全部分析报告，重写 `IB_Final_Report.md`：执行摘要（5 条以内最重要的发现）→ 持仓概况 → 风险 → 估值与基本面 → 情景 → 对冲/再平衡建议 → 未来 90 天日历 → 行动清单（按优先级）→ 数据来源与局限。
2. 生成 `IB_Analysis.xlsx`，包含这些工作表：持仓明细、暴露与集中度、风险指标、相关性矩阵、压力测试、催化剂日历、再平衡建议、行动清单。表头加粗、冻结首行、数字格式规范、风险高的项目条件格式标红。
3. 末尾注明：本报告由 AI 自动生成，仅供参考，不构成投资建议。
"""


def ib_deepen_prompt(ana_dir, rnd):
    return f"""# IB 持仓 · 深化第 {rnd} 轮

工作目录 `{ana_dir}`。用户在睡觉，不要提问。

1. 读全部报告，挑出**最薄弱、证据最少或数据最旧**的部分（每轮选不同的部分，在 `deepen_log.md` 里记录选了什么，避免重复）。
2. 联网补充最新数据、加更严谨的计算（写脚本），把这部分重写得更扎实。
3. 结果写到 `deep_{rnd:02d}.md`，并同步更新 `IB_Final_Report.md` 和 `IB_Analysis.xlsx` 里对应的内容。
"""


# ---------------------------------------------------------------- main flow
def next_reset(at):
    hh, mm = map(int, at.split(":"))
    now = dt.datetime.now()
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t <= now:
        t += dt.timedelta(days=1)
    return t


def wait_until(t, logfh):
    log(f"等待到 {t:%Y-%m-%d %H:%M}（本地时间）……", logfh)
    while True:
        left = (t - dt.datetime.now()).total_seconds()
        if left <= 0:
            return
        time.sleep(min(left, 60))


def run_with_retry(fn, logfh, deadline, label):
    """遇到额度限制时（可能重置还没生效），每 5 分钟重试，最多 30 分钟。"""
    for attempt in range(7):
        st, out = fn()
        if st != "limit":
            return st, out
        if attempt == 6 or dt.datetime.now() > deadline:
            break
        log(f"[{label}] 提示额度不足，5 分钟后重试（{attempt + 1}/6）", logfh)
        time.sleep(300)
    return "limit", ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--at", default="02:38")
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--externship-ids")
    ap.add_argument("--ib-id")
    ap.add_argument("--model")
    ap.add_argument("--codex", help="codex 程序路径")
    ap.add_argument("--window-hours", type=float, default=5.0)
    ap.add_argument("--workdir", default=os.path.join(os.path.expanduser("~"), "Codex-Night"))
    args = ap.parse_args()

    codex = find_codex(args.codex)
    sessions, ext, ib = pick_sessions(args)

    print(f"Codex 程序: {' '.join(codex) if codex else '未找到！请确认已安装并登录 codex'}")
    print(f"会话目录: {codex_home()}  共 {len(sessions)} 个会话")
    print("\nExternship 会话:" + ("" if ext else "  未找到（可用 --externship-ids 指定）"))
    for s in ext:
        print("  - " + describe(s))
    print("\nIB 持仓会话:" + (f"\n  - {describe(ib)}" if ib else "  未找到（可用 --ib-id 指定）"))
    start = dt.datetime.now() if args.now else next_reset(args.at) + dt.timedelta(minutes=2)
    print(f"\n计划开始时间: {start:%Y-%m-%d %H:%M}（本地时间，重置后留 2 分钟余量）")
    print(f"输出目录: {args.workdir}")
    if args.dry_run:
        print("\n其他候选（如果上面选错了，用 --externship-ids / --ib-id 指定）:")
        shown = {s["id"] for s in ext} | ({ib["id"]} if ib else set())
        cands = [s for s in sessions if s["id"] not in shown and
                 (score(s, EXTERNSHIP_KEYS, ["externship"]) or score(s, IB_KEYS, ["interactive-brokers", "ibkr"]))]
        for s in (cands or sessions)[:10]:
            print("  - " + describe(s))
        return
    if not codex:
        sys.exit("找不到 codex 命令，退出。")

    os.makedirs(args.workdir, exist_ok=True)
    logfh = open(os.path.join(args.workdir, "run.log"), "a", encoding="utf-8")
    with KeepAwake():
        wait_until(start, logfh)
        t0 = dt.datetime.now()
        deadline = t0 + dt.timedelta(hours=args.window_hours) - dt.timedelta(minutes=5)
        r = Runner(codex, args.model, logfh, args.workdir)
        log(f"开始！本轮额度窗口截止约 {deadline:%H:%M}", logfh)

        # ---- 1. Externship
        for i, s in enumerate(ext, 1):
            deliver = os.path.join(s["cwd"] or args.workdir, "deliverables")
            os.makedirs(deliver, exist_ok=True)
            tr = os.path.join(args.workdir, f"externship_{i}_transcript.md")
            dump_transcript(s, tr)
            prompt = r.prompt_file(f"externship_{i}", externship_prompt(deliver, tr))
            log(f"== Externship 会话 {i}/{len(ext)}: {s['id']}", logfh)
            st, _ = run_with_retry(lambda: r.resume(s["id"], prompt, s["cwd"], [deliver, args.workdir]),
                                   logfh, deadline, "Externship")
            if st == "fail":  # resume 不行就开新会话，靠记录文件接上
                log("resume 不可用，改为新会话 + 会话记录", logfh)
                st, _ = r.fresh(prompt, s["cwd"] or args.workdir, [deliver, args.workdir])
            if st == "limit":
                log("额度已用完，结束。", logfh)
                return
            log(f"Externship {i} 结果: {st}，交付物在 {deliver}", logfh)

        # ---- 2. IB 持仓分析：一直跑到额度用完或窗口结束
        if not ib:
            log("没找到 IB 持仓会话，跳过分析。", logfh)
            return
        ana = os.path.join(args.workdir, "ib_analysis")
        os.makedirs(ana, exist_ok=True)
        tr = os.path.join(ana, "ib_session_transcript.md")
        dump_transcript(ib, tr)

        log(f"== IB 持仓提取: {ib['id']}", logfh)
        p = r.prompt_file("ib_extract", ib_extract_prompt(ana, tr))
        st, _ = run_with_retry(lambda: r.resume(ib["id"], p, ib["cwd"], [ana]), logfh, deadline, "IB")
        if st != "limit" and not os.path.exists(os.path.join(ana, "holdings.md")):
            log("resume 没写出 holdings.md，改从会话记录里提取", logfh)
            st, _ = r.fresh(p, ana, [ana])
        if st == "limit":
            log("额度已用完，结束。", logfh)
            return

        jobs = [(f"{i:02d}_{slug}", ib_topic_prompt(ana, i, slug, topic))
                for i, (slug, topic) in enumerate(IB_TOPICS, 1)]
        jobs.append(("final", ib_final_prompt(ana)))
        rnd = 0
        while dt.datetime.now() < deadline:
            if jobs:
                name, text = jobs.pop(0)
            else:
                rnd += 1
                name, text = f"deepen_{rnd:02d}", ib_deepen_prompt(ana, rnd)
            log(f"== IB 分析: {name}（距窗口截止还有 {(deadline - dt.datetime.now()).seconds // 60} 分钟）", logfh)
            st, _ = r.fresh(r.prompt_file(name, text), ana, [ana])
            if st == "limit":
                log("额度已用完 ✔", logfh)
                break
            if st == "fail":
                time.sleep(30)
        log(f"全部结束。结果在 {args.workdir}，日志 run.log", logfh)


if __name__ == "__main__":
    main()
