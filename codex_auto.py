#!/usr/bin/env python3
"""
codex_auto.py — 一句「开启」，自动识别 Codex 额度时间，按顺序用 Codex 跑项目队列。

队列顺序(可在 ~/codex-auto/queue.json 里改):
  1. IB 分析      —— 持仓提取 → 12 个专题 → 综合报告 + Excel；跑完自动换下一类
  2. Coding 项目  —— 最近有 Codex 对话、且目录是代码项目的：检查没做完的继续做
  3. 生活项目     —— 其余最近的 Codex 对话(作业、求职、Externship 等)：同上
  4. ……你在 queue.json 里加的任何项目

时间识别:
  读取 ~/.codex 会话里记录的额度信息(5 小时窗口 + 每周额度)：
  - 额度够 → 立刻开始
  - 5 小时额度已用完 → 显示重置时间，等到重置后自动开始
  - 运行中撞到额度上限 → 停止(加 --loop 则等下一次重置后继续)

命令:
  python3 ~/codex_auto.py --install   安装快捷命令：以后终端里输入「开启」就行
  开启                                 = python3 ~/codex_auto.py
  开启 --dry-run                       只看时间、额度和队列，不运行
  开启 --loop                          额度用完后等重置继续，直到队列清空
  codex状态                            查看额度、队列进度、最近日志

安全: 所有任务都只做本地工作和草稿；不发邮件/消息、不提交申请、不买东西、
     不下单交易、不 push、不删数据。需要你确认的事写进 NEXT_STEPS.md。
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

HOME = os.path.expanduser("~")
BASE = os.path.join(HOME, "codex-auto")
QUEUE_FILE = os.path.join(BASE, "queue.json")
STATE_FILE = os.path.join(BASE, "state.json")
LOG_FILE = os.path.join(BASE, "run.log")

AUTH_RE = re.compile(r"401 Unauthorized|invalid_api_key|Incorrect API key|not logged in|Please log ?in", re.I)
MODEL_RE = re.compile(r"model is not supported|model_not_found|Unsupported model|does not exist or you do not have access", re.I)
LIMIT_RE = re.compile(r"hit your usage limit|usage_limit_reached|usage limit\. |rate limit reached", re.I)
TRY_AGAIN_RE = re.compile(r"try again at ([0-9]{1,2}:[0-9]{2}\s*[AP]M)", re.I)
STATUS_RE = re.compile(r"STATUS:\s*(DONE|PARTIAL|BLOCKED)", re.I)
CODE_MARKERS = [".git", "package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod",
                "pom.xml", "build.gradle", "Makefile", "CMakeLists.txt", "Package.swift", "pubspec.yaml"]

SAFETY = """
## 安全规则（必须遵守）
用户在睡觉/不在电脑前。**不要提问、不要等确认**，按最合理的假设继续，并把假设写下来。
只做本地工作和草稿，**绝对不要**做任何对外、不可撤销的操作：
- 不发送邮件、消息、评论；不提交表单、申请、报名；不购买、不付款；
- 不下单、改单、撤单、转账（IB / 任何券商账户只读）；
- 不 git push、不发布、不部署；不删除用户已有的文件或数据（改动前先备份）。
需要用户亲自确认或操作的事，写进工作目录下的 `NEXT_STEPS.md`。
最后一条回复的最后一行必须是以下之一：`STATUS: DONE`（全部完成）/ `STATUS: PARTIAL`（还有没做完的）/ `STATUS: BLOCKED`（需要用户才能继续）。
"""

IB_TOPICS = [
    ("overview", "持仓总览与集中度：每个标的的权重、行业/地区/币种/资产类别暴露、前五大集中度、HHI 指数"),
    ("fundamentals", "逐个持仓的基本面与估值：业务概况、最近四季财报、营收/利润增速、PE/PS/EV-EBITDA/FCF yield 与历史及同行对比"),
    ("technicals", "技术面与动量：趋势、50/200 日均线、支撑阻力、RSI、相对大盘强弱、近 1/3/6/12 个月涨跌幅"),
    ("risk", "组合风险量化：写 Python 拉历史价格，算波动率、Beta、最大回撤、相关性矩阵、95%/99% VaR 与 CVaR、风险贡献"),
    ("stress", "情景压力测试：利率 +100bp、衰退、科技股回调 20%、美元走强 10%、2020/3 与 2022 重演下组合与单票损益"),
    ("catalysts", "催化剂日历：未来 90 天财报日、除息日、FOMC/CPI/非农等宏观事件及可能影响"),
    ("hedging", "期权与对冲方案：保护性看跌、领口、备兑、指数对冲，给出行权价/到期日示例与成本估算"),
    ("rebalance", "再平衡与仓位优化：当前权重 vs 均值方差/风险平价/最小方差目标权重，给出调仓清单与理由"),
    ("tax_cost", "税务与成本：未实现盈亏、税损收割机会、wash sale 注意事项、佣金与汇率成本"),
    ("income_cash", "收益与现金：分红收益率与安全性、现金/保证金使用、利息收入与融资成本"),
    ("thesis", "逐个持仓的看多/看空论点、关键监控指标、止损/加仓触发条件"),
    ("devils_advocate", "魔鬼代言人：挑战前面所有报告的结论，找出遗漏风险与过度乐观的假设"),
]

DEFAULT_QUEUE = {
    "_说明": "按顺序执行。kind: ib=IB 持仓分析；sessions=续做最近的 Codex 对话；tasks=你手写的任务。"
             "enabled 改成 false 可跳过某一类。tasks 例子: {\"name\": \"整理简历\", \"dir\": \"~/Desktop/G_Career\", \"prompt\": \"...\"}",
    "categories": [
        {"name": "IB分析", "kind": "ib", "enabled": True,
         "cwd_contains": ["interactive-brokers", "ibkr"]},
        {"name": "Coding项目", "kind": "sessions", "enabled": True, "filter": "code", "days": 7,
         "exclude_cwd_contains": ["interactive-brokers", "ibkr"]},
        {"name": "生活项目", "kind": "sessions", "enabled": True, "filter": "noncode", "days": 7,
         "exclude_cwd_contains": ["interactive-brokers", "ibkr"]},
        {"name": "其他任务", "kind": "tasks", "enabled": True, "tasks": []},
    ],
}


# ---------------------------------------------------------------- utils
def now():
    return dt.datetime.now()


def fmt(t):
    return t.strftime("%m-%d %H:%M") if t else "?"


class Log:
    def __init__(self):
        os.makedirs(BASE, exist_ok=True)
        self.fh = open(LOG_FILE, "a", encoding="utf-8")

    def __call__(self, msg):
        line = f"[{now():%Y-%m-%d %H:%M:%S}] {msg}"
        print(line, flush=True)
        self.fh.write(line + "\n")
        self.fh.flush()

    def raw(self, text):
        self.fh.write(text)
        self.fh.flush()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def clean_env():
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
    # nvm 装的 codex 需要 node 在 PATH 里
    extra = sorted(glob.glob(os.path.join(HOME, ".nvm/versions/node/*/bin")), reverse=True)
    extra += ["/opt/homebrew/bin", "/usr/local/bin"]
    env["PATH"] = os.pathsep.join([p for p in extra if os.path.isdir(p)] + [env.get("PATH", "")])
    return env


class KeepAwake:
    """阻止系统睡眠(允许熄屏)。"""

    def __init__(self):
        self.proc = None

    def __enter__(self):
        try:
            if platform.system() == "Darwin":
                self.proc = subprocess.Popen(["caffeinate", "-i", "-s", "-w", str(os.getpid())])
            elif platform.system() == "Windows":
                import ctypes
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
            elif shutil.which("systemd-inhibit"):
                self.proc = subprocess.Popen(
                    ["systemd-inhibit", "--what=sleep:idle", "--why=codex_auto", "sleep", "infinity"])
        except Exception as e:
            print(f"[warn] 无法阻止睡眠: {e}")
        return self

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()


# ---------------------------------------------------------------- codex binary + login
def find_codex(override=None):
    if override:
        return [override]
    env = clean_env()
    c = shutil.which("codex", path=env["PATH"])
    if c:
        return [c]
    for pat in ["/Applications/Codex*.app/Contents/Resources/codex",
                "/Applications/Codex*.app/Contents/Resources/**/codex",
                HOME + "/.npm-global/bin/codex", HOME + "/.local/bin/codex"]:
        for f in sorted(glob.glob(pat, recursive=True)):
            if os.path.isfile(f) and os.access(f, os.X_OK):
                return [f]
    npx = shutil.which("npx", path=env["PATH"])
    return [npx, "-y", "@openai/codex@latest"] if npx else None


def model_candidates():
    """最近成功出过回复、且没有报过「ChatGPT 账号不支持」的会话所用的模型，按新到旧排列。"""
    files = sorted(session_files(), key=os.path.getmtime, reverse=True)[:80]
    seen, out, bad = set(), [], set()
    for fp in files:
        models, ok, err = [], False, False
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for raw in f:
                    if "not supported when using Codex with a ChatGPT account" in raw:
                        err = True
                    if '"model"' not in raw and '"assistant"' not in raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    p = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
                    if obj.get("type") == "turn_context" and p.get("model"):
                        models.append(p["model"])
                    if p.get("type") == "message" and p.get("role") == "assistant":
                        ok = True
        except OSError:
            continue
        if err:
            bad.update(models)
            continue
        for m in reversed(models):
            if ok and m not in seen:
                seen.add(m)
                out.append(m)
    return [m for m in out if m not in bad]


def login_status(codex):
    try:
        r = subprocess.run(codex + ["login", "status"], capture_output=True, text=True, timeout=120, env=clean_env())
        return (r.stdout + r.stderr).strip()
    except Exception as e:
        return f"无法检查: {e}"


# ---------------------------------------------------------------- sessions
def codex_home():
    return os.environ.get("CODEX_HOME") or os.path.join(HOME, ".codex")


def session_files():
    h = codex_home()
    files = glob.glob(os.path.join(h, "sessions", "**", "*.jsonl"), recursive=True)
    files += glob.glob(os.path.join(h, "archived_sessions", "**", "*.jsonl"), recursive=True)
    return files


def parse_session(path):
    sid, cwd, msgs, seen = None, None, [], set()
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
                if obj.get("type") == "session_meta":
                    sid = p.get("id") or sid
                    cwd = p.get("cwd") or cwd
                    continue
                role, text = None, None
                if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
                    role = p["role"]
                    text = "\n".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
                elif p.get("type") == "user_message":
                    role, text = "user", p.get("message", "")
                if not text or text.lstrip().startswith("<") or text.startswith("# AGENTS.md"):
                    continue
                key = (role, text[:500])
                if key not in seen:
                    seen.add(key)
                    msgs.append((role, text))
    except OSError:
        return None
    if not sid or not msgs:
        return None
    first = next((t for r, t in msgs if r == "user"), "")
    if first.startswith("The following is the Codex agent history") or first.startswith("Read the file "):
        return None  # 自动审批子会话 / 本工具自己开的会话
    return {"id": sid, "cwd": cwd, "path": path, "mtime": os.path.getmtime(path), "msgs": msgs}


def all_sessions():
    best = {}
    for fp in session_files():
        s = parse_session(fp)
        if not s:
            continue
        if s["cwd"] and os.path.abspath(s["cwd"]).startswith(BASE):
            continue
        old = best.get(s["id"])
        if not old or s["mtime"] > old["mtime"]:
            if old:  # 同一会话多个文件：合并消息
                s["msgs"] = old["msgs"] + [m for m in s["msgs"] if m not in old["msgs"]]
            best[s["id"]] = s
    return sorted(best.values(), key=lambda s: s["mtime"], reverse=True)


def is_code_dir(cwd):
    if not cwd or not os.path.isdir(cwd):
        return False
    d = cwd
    for _ in range(4):  # 向上找几层(子目录里开的会话)
        if any(os.path.exists(os.path.join(d, m)) for m in CODE_MARKERS):
            return True
        if glob.glob(os.path.join(d, "*.xcodeproj")):
            return True
        nd = os.path.dirname(d)
        if nd == d or nd == HOME:
            break
        d = nd
    return False


def first_user(s, n=60):
    t = next((t for r, t in s["msgs"] if r == "user"), "")
    return re.sub(r"\s+", " ", t)[:n]


def dump_transcript(s, path, limit=300_000):
    parts = [f"# Codex 会话记录 {s['id']}\n\n原工作目录: {s['cwd']}\n"]
    for role, text in s["msgs"]:
        parts.append(f"\n## {'用户' if role == 'user' else 'Codex'}\n\n{text}\n")
    body = "".join(parts)
    if len(body) > limit:
        body = body[: limit // 3] + "\n\n...(中间省略)...\n\n" + body[-2 * limit // 3:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


# ---------------------------------------------------------------- quota / time detection
def _abs_reset(win, ts):
    if not isinstance(win, dict):
        return None
    if win.get("resets_at"):
        try:
            return dt.datetime.fromtimestamp(float(win["resets_at"]))
        except Exception:
            pass
    secs = win.get("resets_in_seconds")
    if secs is not None and ts:
        return ts + dt.timedelta(seconds=float(secs))
    return None


def read_rate_limits():
    """从最近的会话记录里找最新的额度信息。返回 dict 或 None。"""
    files = sorted(session_files(), key=os.path.getmtime, reverse=True)[:8]
    best = None
    for fp in files:
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[-400:]
        except OSError:
            continue
        for raw in reversed(lines):
            if "rate_limits" not in raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            p = obj.get("payload") or {}
            rl = p.get("rate_limits") or (p.get("info") or {}).get("rate_limits")
            if not isinstance(rl, dict):
                continue
            try:
                ts = dt.datetime.fromisoformat(obj.get("timestamp", "").replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
            except Exception:
                ts = dt.datetime.fromtimestamp(os.path.getmtime(fp))
            info = {"ts": ts}
            for name in ("primary", "secondary"):
                w = rl.get(name)
                if isinstance(w, dict):
                    info[name] = {"used": float(w.get("used_percent", 0) or 0),
                                  "window_min": w.get("window_minutes"),
                                  "reset": _abs_reset(w, ts)}
            if not best or ts > best["ts"]:
                best = info
            break
    return best


def window_label(w):
    m = w.get("window_min")
    if not m:
        return "额度"
    return "5小时额度" if m <= 360 else ("每周额度" if m >= 7 * 24 * 60 - 60 else f"{m}分钟额度")


def quota_report(rl):
    if not rl:
        return ["额度信息: 暂无记录（之前没用过 Codex 或版本不记录），直接尝试开始"]
    out = [f"额度信息（记录于 {fmt(rl['ts'])}）:"]
    for name in ("primary", "secondary"):
        w = rl.get(name)
        if w:
            r = w["reset"]
            reset_txt = "已过重置时间→已恢复" if r and r <= now() else f"{fmt(r)} 重置"
            out.append(f"  - {window_label(w)}: 已用 {w['used']:.0f}%，{reset_txt}")
    return out


def blocked_until(rl):
    """额度用完时返回(重置时间, 名称)；可用则返回 None。"""
    if not rl:
        return None
    worst = None
    for name in ("primary", "secondary"):
        w = rl.get(name)
        if w and w["used"] >= 99.5 and w["reset"] and w["reset"] > now():
            if not worst or w["reset"] > worst[0]:
                worst = (w["reset"], window_label(w))
    return worst


def parse_try_again(text):
    m = TRY_AGAIN_RE.search(text or "")
    if not m:
        return None
    try:
        t = dt.datetime.strptime(m.group(1).upper().replace(" ", ""), "%I:%M%p")
    except ValueError:
        return None
    r = now().replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    return r if r > now() else r + dt.timedelta(days=1)


def sleep_until(t, log, why):
    log(f"⏳ {why}，等到 {t:%m-%d %H:%M} 再开始（现在 {now():%H:%M}）")
    while True:
        left = (t - now()).total_seconds()
        if left <= 0:
            return
        time.sleep(min(left, 60))


# ---------------------------------------------------------------- codex runner
class ModelError(Exception):
    pass


class QuotaHit(Exception):
    def __init__(self, reset=None):
        self.reset = reset


class Runner:
    def __init__(self, codex, model, log):
        self.codex, self.model, self.log = codex, model, log
        self.n = 0
        self.prompt_dir = os.path.join(BASE, "prompts", now().strftime("%Y%m%d-%H%M"))

    def cfg(self, writable):
        c = ["-c", 'forced_login_method="chatgpt"', "-c", 'approval_policy="never"',
             "-c", 'sandbox_mode="workspace-write"', "-c", "sandbox_workspace_write.network_access=true",
             "-c", 'web_search="live"', "-c", 'model_reasoning_effort="high"']
        roots = [r for r in (writable or []) if r]
        if roots:
            c += ["-c", "sandbox_workspace_write.writable_roots=" + json.dumps(roots)]
        if self.model:
            c += ["-m", self.model]
        return c

    def prompt(self, name, text):
        self.n += 1
        os.makedirs(self.prompt_dir, exist_ok=True)
        path = os.path.join(self.prompt_dir, f"{self.n:03d}_{re.sub(r'[^0-9A-Za-z_-]+', '_', name)[:40]}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n" + SAFETY)
        return (f"Read the file {path} and carry out every instruction in it exactly. The user is asleep: "
                "never ask questions or wait for confirmation; follow the safety rules in that file.")

    def _run(self, argv, cwd, out_file, timeout_min):
        cmd = self.codex + argv
        self.log("$ codex " + " ".join(a if len(a) < 80 else a[:77] + "..." for a in argv[:3]) + " …")
        proc = subprocess.Popen(cmd, cwd=cwd if cwd and os.path.isdir(cwd) else BASE, env=clean_env(),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        lines = []

        def reader():
            for line in proc.stdout:
                lines.append(line)
                self.log.raw(line)
                sys.stdout.write(line)
                sys.stdout.flush()

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        try:
            proc.wait(timeout=timeout_min * 60)
        except subprocess.TimeoutExpired:
            self.log(f"单次运行超过 {timeout_min} 分钟，终止")
            proc.kill()
            proc.wait()
        t.join(timeout=10)
        out = "".join(lines)
        if MODEL_RE.search(out):
            raise ModelError(out[-300:])
        if AUTH_RE.search(out):
            self.log("❌ Codex 鉴权失败（不是 ChatGPT 账号登录）。请运行 `codex logout; codex login` 选 Sign in with ChatGPT。")
            raise SystemExit(2)
        tail = "".join(lines[-40:])
        if LIMIT_RE.search(tail):
            rl = read_rate_limits()
            b = blocked_until(rl)
            raise QuotaHit(parse_try_again(tail) or (b[0] if b else None))
        last = ""
        if out_file and os.path.exists(out_file):
            with open(out_file, encoding="utf-8", errors="replace") as f:
                last = f.read()
        m = STATUS_RE.findall(last or tail)
        status = m[-1].upper() if m else ("DONE" if proc.returncode == 0 else "FAIL")
        return status

    def resume(self, sid, prompt, cwd, writable=None, timeout_min=90):
        out = os.path.join(self.prompt_dir, f"last_{self.n:03d}.md")
        st = self._run(["exec", "resume", "--skip-git-repo-check"] + self.cfg(writable) + ["-o", out, sid, prompt],
                       cwd, out, timeout_min)
        if st == "FAIL":
            self.log("resume 失败，改用新会话 + 会话记录继续")
        return st

    def fresh(self, prompt, cwd, writable=None, timeout_min=90):
        os.makedirs(cwd, exist_ok=True)
        out = os.path.join(self.prompt_dir, f"last_{self.n:03d}.md")
        return self._run(["exec", "--skip-git-repo-check", "-C", cwd] + self.cfg(writable) + ["-o", out, prompt],
                         cwd, out, timeout_min)


# ---------------------------------------------------------------- job builders
def ib_jobs(cat, state, sessions):
    keys = [k.lower() for k in cat.get("cwd_contains", [])]
    ib = next((s for s in sessions if s["cwd"] and any(k in s["cwd"].lower() for k in keys)), None)
    if not ib:
        return [], "没找到 IB 持仓会话"
    st = state.setdefault("ib", {"done": []})
    ana = os.path.join(BASE, "ib_analysis")
    jobs = []
    tr = os.path.join(ana, "ib_session_transcript.md")
    if "extract" not in st["done"]:
        jobs.append({"key": "ib:extract", "label": "IB 持仓提取", "type": "resume_then_fresh", "session": ib,
                     "cwd": ana, "transcript": tr, "writable": [ana], "text": f"""# 任务：整理 IB 持仓（只读）
根据本对话（完整记录也备份在 `{tr}`）里的 Interactive Brokers 持仓：
1. 原样、完整整理成 `{ana}/holdings.md`（Markdown 表格：代码、名称、类型、数量、成本、现价、市值、未实现盈亏、币种、占比等）和 `{ana}/holdings.csv`。缺的留空，不要编造。
2. 如果 IBKR 插件可用，可以**只读**刷新最新持仓与价格；**绝对不要下单、改单、撤单或转账**。
3. 在 `{ana}/00_raw_notes.md` 记下用户提到的投资目标、风险偏好、限制条件和关心的问题。"""})
    for i, (slug, topic) in enumerate(IB_TOPICS, 1):
        if slug in st["done"]:
            continue
        jobs.append({"key": f"ib:{slug}", "label": f"IB 专题 {i:02d} {slug}", "type": "fresh", "cwd": ana,
                     "writable": [ana], "text": f"""# IB 持仓深度分析 · 第 {i} 轮：{slug}（只读，不交易）
工作目录 `{ana}`。
1. 先读 `holdings.md`、`holdings.csv`、`00_raw_notes.md`，再浏览已有报告（`*.md`），不要重复已做内容。
2. 本轮专题：**{topic}**
3. 联网获取最新行情/财报/新闻/期权数据（注明来源与时间）；需要计算就在 `scripts/` 写 Python 并运行（可 `pip install --user yfinance pandas numpy openpyxl`）。拿不到的数据如实说明，不要编造。
4. 写入 `{i:02d}_{slug}.md`：深入、量化、多用表格，结尾写"关键结论"和"建议行动"（建议仅供用户参考，不执行任何交易）。
5. 把本轮关键结论合并进 `IB_Final_Report.md`（没有就新建，执行摘要放最前）。"""})
    if "final" not in st["done"]:
        jobs.append({"key": "ib:final", "label": "IB 综合报告 + Excel", "type": "fresh", "cwd": ana, "writable": [ana],
                     "text": f"""# IB 持仓 · 综合报告与表格
工作目录 `{ana}`。
1. 通读全部报告，重写 `IB_Final_Report.md`：执行摘要 → 持仓概况 → 风险 → 估值与基本面 → 情景 → 对冲/再平衡建议 → 90 天日历 → 行动清单（按优先级）→ 数据来源与局限。
2. 生成 `IB_Analysis.xlsx`：持仓明细、暴露与集中度、风险指标、相关性矩阵、压力测试、催化剂日历、再平衡建议、行动清单；表头加粗、冻结首行、数字格式规范、高风险项标红。
3. 末尾注明：AI 自动生成，仅供参考，不构成投资建议。"""})
    return jobs, f"会话 {ib['id'][:8]}…（{first_user(ib, 30)}）"


def session_jobs(cat, state, sessions):
    days = cat.get("days", 7)
    cutoff = time.time() - days * 86400
    excl = [k.lower() for k in cat.get("exclude_cwd_contains", [])]
    want = cat.get("filter", "any")
    done = state.setdefault("sessions", {})
    jobs = []
    for s in sessions:
        if s["mtime"] < cutoff:
            continue
        cwd = (s["cwd"] or "").lower()
        if any(k in cwd for k in excl):
            continue
        code = is_code_dir(s["cwd"])
        if (want == "code" and not code) or (want == "noncode" and code):
            continue
        rec = done.get(s["id"], {})
        if rec.get("status") in ("DONE", "BLOCKED") and s["mtime"] <= rec.get("mtime", 0) + 5:
            continue  # 已完成且之后没有新对话
        if rec.get("tries", 0) >= 3 and s["mtime"] <= rec.get("mtime", 0) + 5:
            continue
        tr = os.path.join(BASE, "transcripts", f"{s['id']}.md")
        jobs.append({"key": f"s:{s['id']}", "label": f"{cat['name']}: {first_user(s, 40)}", "type": "resume_then_fresh",
                     "session": s, "cwd": s["cwd"] or os.path.join(BASE, "work", s["id"][:8]), "transcript": tr,
                     "writable": [s["cwd"]] if s["cwd"] else [], "text": f"""# 自动续做：检查这个对话的任务是否完成
这是额度重置后的自动续跑（完整对话记录也备份在 `{tr}`）。
1. 回顾本对话，逐条列出用户提出的全部要求和交付物。
2. 检查工作目录里的实际文件，判断每一条：已完成 / 部分完成 / 未开始。
3. 把未完成的部分全部做完；如果是代码项目，写完要运行测试/构建确认能跑，修好报错（不要 push）。
4. 需要表格的做成 `.xlsx` + `.csv`；需要文档的写成 `.md` 或按原要求的格式。
5. 在工作目录写/更新 `CODEX_AUTO_SUMMARY.md`：这次做了什么、产出文件在哪、做了哪些假设、还剩什么。
如果一切早已完成，只需简单核对并回复 `STATUS: DONE`。"""})
    return jobs, f"{len(jobs)} 个待处理对话（最近 {days} 天）"


def task_jobs(cat, state):
    done = state.setdefault("tasks", {})
    jobs = []
    for t in cat.get("tasks", []):
        name = t.get("name") or t.get("prompt", "")[:20]
        if done.get(name) in ("DONE", "BLOCKED"):
            continue
        d = os.path.expanduser(t.get("dir") or os.path.join(BASE, "work", re.sub(r"\W+", "_", name)))
        extra = [os.path.expanduser(x) for x in t.get("extra_dirs", [])]
        jobs.append({"key": f"t:{name}", "label": f"{cat['name']}: {name}", "type": "fresh", "cwd": d,
                     "writable": [d] + extra, "clone": t.get("clone"), "timeout_min": t.get("timeout_min", 90),
                     "text": f"# 任务：{name}\n工作目录 `{d}`。\n\n{t.get('prompt', '')}\n"})
    return jobs, f"{len(jobs)} 个任务"


def build_queue(queue, state, sessions):
    plan = []
    for cat in queue["categories"]:
        if not cat.get("enabled", True):
            continue
        if cat["kind"] == "ib":
            jobs, note = ib_jobs(cat, state, sessions)
        elif cat["kind"] == "sessions":
            jobs, note = session_jobs(cat, state, sessions)
        else:
            jobs, note = task_jobs(cat, state)
        plan.append((cat, jobs, note))
    return plan


def record(state, job, status):
    k = job["key"]
    if k.startswith("ib:"):
        if status in ("DONE", "PARTIAL"):  # 专题一轮跑完就算完成
            state.setdefault("ib", {"done": []})["done"].append(k[3:])
    elif k.startswith("s:"):
        rec = state.setdefault("sessions", {}).setdefault(k[2:], {})
        rec["status"] = status
        rec["tries"] = rec.get("tries", 0) + 1
        rec["mtime"] = time.time() + 60  # 本次续做本身也会更新会话文件
    elif k.startswith("t:"):
        state.setdefault("tasks", {})[k[2:]] = status
    save_json(STATE_FILE, state)


def run_job(r, job):
    if job.get("clone") and not os.path.isdir(job["cwd"]):  # 先把用户自己的仓库下载到本地
        r.log(f"下载仓库 {job['clone']} → {job['cwd']}")
        os.makedirs(os.path.dirname(job["cwd"]), exist_ok=True)
        subprocess.run(["gh", "repo", "clone", job["clone"], job["cwd"]], env=clean_env())
    if job["type"] == "fresh":
        return r.fresh(r.prompt(job["key"], job["text"]), job["cwd"], job["writable"], job.get("timeout_min", 90))
    s = job["session"]
    dump_transcript(s, job["transcript"])
    p = r.prompt(job["key"], job["text"])
    os.makedirs(job["cwd"], exist_ok=True)
    st = r.resume(s["id"], p, job["cwd"], job["writable"] + [os.path.dirname(job["transcript"])])
    if st == "FAIL":
        st = r.fresh(p, job["cwd"], job["writable"] + [os.path.dirname(job["transcript"])])
    return st


# ---------------------------------------------------------------- presets
P = "~/Desktop/Project"
NO_GIT_WRITE = ("\n**不要 git commit / push / pull / rebase / fork**（沙盒里 .git 是只读的，这些由用户醒来后自己做）。"
                "改动留在工作区；把建议的分支名、commit 信息和 PR 描述写进 `PR_DESCRIPTION.md`。\n")
TODAY_TASKS = [
    {"name": "YesPlayMusic 升级 Electron 修复正在播放", "dir": f"{P}/YesPlayMusic", "clone": "LucasYanzy/YesPlayMusic",
     "timeout_min": 240, "extra_dirs": ["~/Library/Caches/electron", "~/Library/Caches/electron-builder",
                                        "~/Library/Caches/Yarn", "~/.npm", "~/.cache"],
     "prompt": """
背景：用户 Mac 是 macOS 27.0.1，YesPlayMusic 0.4.10（Electron 13）播放时，NotchNook/控制中心“正在播放”不显示它。
macOS 走 Chromium Media Session（`src/utils/Player.js` 的 `_initMediaSession` / `_updateMediaSessionMetaData`；
`src/background.js` 只在 Linux 关闭 MediaSessionService）。Electron 13 太旧，很可能是新系统上 Now Playing 集成失效。
1. 把 Electron 升级到当前稳定版，并升级配套依赖（electron-builder、vue-cli-plugin-electron-builder 等），修掉破坏性变更
   （remote 模块、contextIsolation/nodeIntegration、protocol API、ipc 等），保证 `yarn install` 成功、开发模式能启动。
2. 确认 Media Session 在 macOS 上完整生效（标题/歌手/封面/播放暂停/上下首），补上 `playbackState` 与进度更新。
3. 尝试编译 macOS arm64 安装包；失败就修到成功，记录产物路径。不要安装或替换 /Applications 里的 App。
4. 写 `CODEX_AUTO_SUMMARY.md`：改了什么、怎么测试、产物在哪、已知问题。""" + NO_GIT_WRITE},
    {"name": "Git 仓库体检", "dir": f"{P}/_git_health", "timeout_min": 60, "prompt": """
只读检查 `~/Desktop/Project` 下所有 git 仓库（含子目录）：分支、未提交改动、未推送提交、与远程的差距（`git status -sb`、`git log --oneline @{u}..`、`git log --oneline ..@{u}`）。
已知：RUCF、RUCF/github-copy、Study/RutgersIEEE26_副本 落后于远程；paperclip、TradingAgents 不是用户的仓库（需 fork）；Breathless（Breathless-Game/Breathless）本地可能没有。
1. 写 `GIT_HEALTH.md` 表格：仓库 / 分支 / 状态 / 问题 / 建议操作。对落后的仓库，预判 `pull --rebase` 会不会冲突（比较改动的文件），列出可能冲突的文件。
2. 写 `fix_git.sh`：用户审核后可以手动运行的修复脚本（pull --rebase --autostash、`gh repo fork --remote`、clone Breathless 等），每一步先 echo 说明，遇到错误就停；不含 force push、不删分支。**你自己不要运行它。**""" + NO_GIT_WRITE},
    {"name": "NotchNook 日历与正在播放诊断", "dir": "~/codex-auto/work/notchnook", "timeout_min": 90, "prompt": """
用户 Mac：macOS 27.0.1，NotchNook 1.6.2。①日历显示 "Nothing for today"，但系统日历 App 有日程，NotchNook 已有“完全访问”权限，已重启并 tccutil reset 过；②YesPlayMusic 播放时 NotchNook 不显示它。
1. 只读诊断：`log show --last 2h --predicate 'process == "NotchNook"'` 中与 calendar/EventKit/MediaRemote/now playing/error 相关的条目；
   `defaults read <NotchNook bundle id>` 中与日历、媒体相关的设置（选中了哪些日历、媒体来源限制等）。不要修改任何系统或 App 设置。
2. 联网调研：NotchNook 是否有新版本或已知的 macOS 27 问题；开源替代 Boring Notch（TheBoredTeam/boring.notch）在 macOS 27 上的日历和 Now Playing 支持情况。
3. 写 `REPORT.md`：根因判断、证据、用户可以手动执行的修复步骤（按顺序，附可直接复制的命令，修改设置前先备份）。"""},
    {"name": "codex_auto 自检", "dir": "~/codex-auto", "timeout_min": 45, "prompt": """
阅读 `~/codex-auto/run.log` 和 `~/codex-auto/state.json`，找出之前哪些任务 FAIL/PARTIAL 以及原因（鉴权、网络、沙盒权限、超时、命令错误等）。
写 `~/codex-auto/DIAGNOSIS.md`：每个失败任务的原因和建议修复。若是 `codex_auto.py` 的 bug，把修复写成 `~/codex-auto/codex_auto.patch`（统一 diff），**不要直接改 codex_auto.py**。"""},
]


def apply_preset(name):
    if name != "today":
        sys.exit(f"未知预设: {name}")
    queue = load_json(QUEUE_FILE, DEFAULT_QUEUE)
    cats = [c for c in queue["categories"] if c.get("name") != "今日重点"]
    cats.insert(0, {"name": "今日重点", "kind": "tasks", "enabled": True, "tasks": TODAY_TASKS})
    queue["categories"] = cats
    save_json(QUEUE_FILE, queue)
    print(f"✅ 已把 {len(TODAY_TASKS)} 个「今日重点」任务放到队列最前面")


# ---------------------------------------------------------------- install / status
def install():
    zshrc = os.path.join(HOME, ".zshrc")
    me = os.path.abspath(__file__)
    block = (f"\n# >>> codex-auto >>>\nalias 开启='python3 \"{me}\"'\nalias kaiqi='python3 \"{me}\"'\n"
             f"alias codex状态='python3 \"{me}\" --status'\n# <<< codex-auto <<<\n")
    text = open(zshrc, encoding="utf-8").read() if os.path.exists(zshrc) else ""
    text = re.sub(r"\n# >>> codex-auto >>>.*?# <<< codex-auto <<<\n", "\n", text, flags=re.S)
    with open(zshrc, "w", encoding="utf-8") as f:
        f.write(text + block)
    if not os.path.exists(QUEUE_FILE):
        save_json(QUEUE_FILE, DEFAULT_QUEUE)
    print(f"✅ 已安装。新开一个终端窗口（或运行 source ~/.zshrc）后，输入「开启」即可。\n   队列配置: {QUEUE_FILE}")


def status():
    rl = read_rate_limits()
    print(f"现在: {now():%Y-%m-%d %H:%M}")
    print("\n".join(quota_report(rl)))
    state = load_json(STATE_FILE, {})
    print(f"\nIB 已完成: {len(state.get('ib', {}).get('done', []))}/{len(IB_TOPICS) + 2}")
    ss = state.get("sessions", {})
    print(f"对话续做: 完成 {sum(1 for v in ss.values() if v.get('status') == 'DONE')}，"
          f"部分 {sum(1 for v in ss.values() if v.get('status') == 'PARTIAL')}，"
          f"需你处理 {sum(1 for v in ss.values() if v.get('status') == 'BLOCKED')}")
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
            tail = [l for l in f.readlines() if l.startswith("[")][-8:]
        print("\n最近日志:\n" + "".join(tail))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="只看时间/额度/队列")
    ap.add_argument("--loop", action="store_true", help="额度用完后等重置继续，直到队列清空")
    ap.add_argument("--install", action="store_true", help="安装「开启」快捷命令")
    ap.add_argument("--status", action="store_true", help="查看额度和进度")
    ap.add_argument("--at", help="手动指定开始时间 HH:MM（不填则自动识别）")
    ap.add_argument("--model")
    ap.add_argument("--codex", help="codex 程序路径")
    ap.add_argument("--preset", help="today = 把今日重点任务放到队列最前面")
    ap.add_argument("--until", help="到这个时间(HH:MM)就停，配合 --loop，例如 23:59")
    args = ap.parse_args()

    if args.preset:
        os.makedirs(BASE, exist_ok=True)
        apply_preset(args.preset)

    if args.install:
        return install()
    if args.status:
        return status()

    os.makedirs(BASE, exist_ok=True)
    if not os.path.exists(QUEUE_FILE):
        save_json(QUEUE_FILE, DEFAULT_QUEUE)
    queue = load_json(QUEUE_FILE, DEFAULT_QUEUE)
    state = load_json(STATE_FILE, {})
    codex = find_codex(args.codex)  # 注意：--preset 已在前面写入 queue.json

    print(f"现在: {now():%Y-%m-%d %H:%M}")
    print(f"Codex 程序: {' '.join(codex) if codex else '未找到'}")
    rl = read_rate_limits()
    print("\n".join(quota_report(rl)))

    start = None
    if args.at:
        hh, mm = map(int, args.at.split(":"))
        start = now().replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start <= now():
            start += dt.timedelta(days=1)
    else:
        b = blocked_until(rl)
        if b:
            start = b[0] + dt.timedelta(minutes=2)
            print(f"→ {b[1]}已用完，将在 {fmt(start)} 自动开始")
        else:
            print("→ 额度可用，立即开始")

    sessions = all_sessions()
    plan = build_queue(queue, state, sessions)
    print("\n队列:")
    for i, (cat, jobs, note) in enumerate(plan, 1):
        print(f"  {i}. {cat['name']} — {len(jobs)} 个任务（{note}）")
        for j in jobs[:6]:
            print(f"       · {j['label']}")
        if len(jobs) > 6:
            print(f"       · …还有 {len(jobs) - 6} 个")
    if args.dry_run:
        return
    if not codex:
        sys.exit("找不到 codex，先安装/登录 Codex CLI。")
    ls = login_status(codex)
    print(f"\nCodex 登录状态: {ls}")
    if "chatgpt" not in ls.lower():
        sys.exit("❌ Codex CLI 没有用 ChatGPT 账号登录，跑起来会 401。\n   请运行:  codex logout; codex login  （选 Sign in with ChatGPT），然后再「开启」。")

    log = Log()
    with KeepAwake():
        log(f"===== 开启（{'循环模式' if args.loop else '单轮模式'}）=====")
        if start:
            sleep_until(start, log, "额度未恢复" if not args.at else "按指定时间")
        cands = [args.model] if args.model else model_candidates()
        log(f"候选模型: {', '.join(cands) if cands else '（没识别到，用 Codex 默认）'}")
        r = Runner(codex, cands[0] if cands else None, log)
        until = None
        if args.until:
            hh, mm = map(int, args.until.split(":"))
            until = now().replace(hour=hh, minute=mm, second=0, microsecond=0)
            if until <= now():
                until += dt.timedelta(days=1)
            log(f"本次最晚运行到 {fmt(until)}")
        attempted = set()  # 本次已经跑过的，先跳过，下次「开启」再回来
        passes = 0
        while True:
            if until and now() >= until:
                log(f"⏰ 到达结束时间 {fmt(until)}，停止。")
                break
            state = load_json(STATE_FILE, {})
            plan = build_queue(queue, state, all_sessions())
            jobs = [(cat, j) for cat, js, _ in plan for j in js if j["key"] not in attempted]
            remaining = [(c, j) for c, js, _ in plan for j in js]
            if not jobs and args.loop and remaining and passes < 2:  # 只剩部分完成的，再补做
                passes += 1
                attempted.clear()
                log(f"🔁 还有 {len(remaining)} 个部分完成的任务，再补做一轮（第 {passes} 轮）")
                continue
            if not jobs:
                log("✅ 队列已全部完成！")
                break
            cat, job = jobs[0]
            log(f"▶ [{cat['name']}] {job['label']}（队列剩余 {len(jobs)}）")
            try:
                st = run_job(r, job)
            except ModelError:
                if r.model in cands:
                    cands.remove(r.model)
                if cands:
                    log(f"⚠️ 模型 {r.model} 不能用 ChatGPT 账号调用，换成 {cands[0]} 重试")
                    r.model = cands[0]
                    continue
                log(f"❌ 模型 {r.model or '默认'} 不能用 ChatGPT 账号调用，也没有别的候选模型。"
                    "请看 Codex App 里选的模型，然后运行：开启 --model <模型名>。已停止，避免空跑。")
                break
            except QuotaHit as q:
                reset = q.reset or (now() + dt.timedelta(minutes=30))
                if not args.loop:
                    log(f"🔋 额度已用完 ✔ 下次重置约 {fmt(reset)}。到时候再说「开启」会从这里继续。")
                    break
                if until and reset >= until:
                    log(f"🔋 额度已用完 ✔ 下次重置 {fmt(reset)} 晚于结束时间，今天到此为止。")
                    break
                sleep_until(reset + dt.timedelta(minutes=2), log, "额度用完")
                continue
            log(f"  结果: {st}")
            attempted.add(job["key"])
            if st == "FAIL":  # 失败不写进进度，下次还会重试
                fails = getattr(r, "fails", 0) + 1
                r.fails = fails
                if fails >= 3:
                    log("❌ 连续 3 个任务失败，停止运行，请查看上面的报错。")
                    break
                time.sleep(20)
                continue
            r.fails = 0
            record(state, job, st)
        log(f"结束。IB 结果: {os.path.join(BASE, 'ib_analysis')}；日志: {LOG_FILE}")


if __name__ == "__main__":
    main()
