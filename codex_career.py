#!/usr/bin/env python3
"""在「实习就业」里追加完整求职流程任务（保留已完成的前 3 个，不重做），并放在 IB 之后、Coding 之前。"""
import json
import os

p = os.path.expanduser("~/codex-auto/queue.json")
q = json.load(open(p, encoding="utf-8"))
C = "~/Desktop/G_Career/Codex_Career"
CTX = ("用户背景：Rutgers 大二学生；方向：金融/投资（IB 持仓分析、量化、VC）、AI 与编程项目（~/Desktop/Project 下的 DAshi、TradingAgents、"
       "HackRU26、VC AgentPro、Breathless 等）。工作目录 `" + C + "` 里已有前面任务的产出：`resume/`（简历各版本）、`opportunities/`"
       "（Opportunities.xlsx、TOP10.md）、`applications/`（申请材料与 FILL_SHEET）。**先读这些已有产出，在其基础上做，不要重做或覆盖**；"
       "改已有文件前先复制到 `backups/`。也可参考 ~/Desktop/G_Career/G_Application 里的历史记录（用户提过“不要犯之前汇丰的错误”）。\n"
       "所有事实只能来自用户的文件；缺的信息写「❓需用户补充」，**绝不编造经历、成绩、数据**。工作授权/签证身份未知时，机会表里单列"
       "「国际生/需工作授权」并标注，不要假设。\n")
NO = ("\n**绝对不要提交申请、不要报名、不要登录任何网站账号、不要在线填表、不要发送邮件/LinkedIn/任何消息。只在本地写草稿；"
      "需要用户亲自做的步骤写进 `NEXT_STEPS.md`。所有给用户确认的内容状态写「⏳ 待确认」，用户会和 Claude 逐条确认后自己提交。**\n")
NEW = [
    ("求职档案总表", 60, """建 `profile/MASTER_PROFILE.md`：把简历、项目、课程、技能、获奖、社团、工作/实习、语言、作品链接等**所有可用事实**汇总成一份结构化总档案
（每条注明出处文件）。另列 `profile/MISSING_INFO.md`：申请必需但缺失的信息（GPA、毕业时间、工作授权/签证、可实习时间、地点偏好、LinkedIn、GitHub 链接等），按重要性排序。"""),
    ("求职定位与时间线", 60, """写 `strategy/TARGETING.md`：根据档案评估各方向（投行/S&T/资管研究/量化/软件与AI/VC/产品）的匹配度与竞争力，给出主攻 2 个 + 备选 2 个方向及理由；
大二能申的项目类型（sophomore/early insight/diversity/fellowship/研究助理/初创公司实习）；2026-10 到 2027-03 的招聘时间线（金融大二项目多在秋冬开放），
每个方向“现在到截止前必须补的短板”。"""),
    ("机会库扩充到 80+ 并核验", 150, """在 `opportunities/Opportunities.xlsx` 基础上扩充到至少 80 个机会（保留原有行，新增行标注“新增”）：
金融大二/insight/diversity 项目、量化 discovery/大二项目、科技公司大一大二项目、VC/创业 fellowship、Rutgers 校内（商学院项目、学生投资基金、研究助理、职业中心活动）、
纽约/新泽西中小型基金与初创公司；竞赛：案例赛、股票推介赛、CFA Research Challenge 类、交易/量化竞赛、黑客松、数据科学/Kaggle 类、创业比赛。
每一行**联网打开官方页面核验**本季状态（开放/未开放/已截止/页面不存在）、截止日期、年级与工作授权要求，写明核验日期和链接；查不到就标“未核验”。
新增列：本季状态、国际生可申、所需材料、预计准备小时数、优先级(P0-P2)。导出 `.csv`，并更新 `TOP10.md` 为 `TOP20.md`。"""),
    ("申请材料第二批", 150, """对 `TOP20.md` 中还没有材料的机会（已做过的跳过），每个建 `applications/<机构_项目>/`：选定简历版本、定制 cover letter、申请问答草稿、
`FILL_SHEET.md`（按官方表单字段顺序：字段/草稿答案/字数/依据/状态「⏳ 待确认」/「❓需用户补充」）、该项目面试重点。更新 `applications/APPLICATION_PLAN.md` 的顺序与截止日。"""),
    ("经历故事库与网申题库", 90, """建 `interview/STORY_BANK.md`：从档案里挖 8-12 个真实经历，写成 STAR 故事（领导力、团队冲突、失败、主动性、分析能力、技术难题等），每个注明可回答哪些问题。
建 `interview/QUESTION_BANK.md`：Why this firm/why this role/Tell me about yourself/Why finance-quant-tech 等高频网申与行为面问题，按方向给出基于真实经历的答案草稿（标「⏳ 待确认」）。"""),
    ("人脉与外联草稿", 90, """建 `networking/`：目标公司/项目的校友与员工画像建议（只写搜索方法和公开信息来源，不抓取个人隐私数据）；冷邮件、LinkedIn 连接请求、
coffee chat 邀约、感谢信、跟进信模板（中英文，按方向定制，全部草稿）；coffee chat 问题清单；`Networking_Tracker.xlsx`（姓名留空由用户填）。**不要发送任何消息。**"""),
    ("金融与市场面试准备", 120, """建 `interview/finance/`：会计三表联动、估值（DCF/可比/先例）、并购与 LBO 基础、市场与宏观近况（截至今天联网核实）、
“最近关注的交易/行业”回答草稿；50 道技术题 + 标准答案；结合用户 IB 持仓研究（~/codex-auto/ib_analysis，只读）准备“你怎么看自己的投资组合/最近的市场”回答。"""),
    ("股票推介材料", 120, """基于 ~/codex-auto/ib_analysis（只读）挑 2 只研究最充分的股票（如 PDD、AVGO），在 `pitch/` 做面试与股票推介比赛用的材料：
一页纸推介（论点、催化剂、估值、风险、反方观点）、3-5 页演示稿大纲（可生成 .pptx 草稿）、2 分钟口述稿、常见追问及回答。数据注明来源与日期，不编造。"""),
    ("量化与技术面试准备", 120, """建 `interview/quant_tech/`：概率与期望、脑筋急转弯、心算与市场做市题（各 30 题带详解）；按目标公司整理编程面试计划
（数据结构/算法分类清单、4 周 LeetCode 计划、Python/SQL 高频题）；基于用户项目的技术追问与回答草稿。"""),
    ("作品集与项目包装", 90, """检查 ~/Desktop/Project 下用户自己的项目（只读，不改代码、不 git 操作），在 `portfolio/` 写：每个项目一段简历/面试用描述（问题-做法-结果，事实必须可在代码中找到依据）、
README 改进建议稿、一页作品集 `PORTFOLIO.md`、LinkedIn 标题与 About 改写建议、GitHub 个人主页 README 草稿。"""),
    ("竞赛参赛准备", 90, """对机会库里的竞赛类（P0/P1），在 `competitions/<比赛>/` 写：赛制与评分、组队要求（是否需要队友、建议找什么背景的人）、报名步骤与截止、
往届题目/获奖作品要点（公开资料）、4 周备赛计划、可复用的已有材料。**不要报名。**"""),
    ("质量自查与补强", 120, """按这份验收标准逐条检查 `Codex_Career/` 全部产出，不达标的直接补做到达标，最后写 `QA_REPORT.md`（每条：达标/补做了什么/仍缺什么）：
1) 机会库 ≥80 行，每行有官方链接、核验日期、本季状态、截止日、年级与工作授权要求；死链/过期的已标注；
2) TOP20 每个都有完整 `FILL_SHEET.md`（字段齐全、字数符合限制）、定制 cover letter、选定简历版本；
3) 每版简历一页、每条 bullet 动词开头且尽量量化、无拼写错误、与目标方向关键词匹配；
4) 故事库 ≥8 个 STAR、题库覆盖各方向高频题；面试准备每个方向题量达到任务要求；
5) 全部内容无编造（逐条可追溯到用户文件或公开来源），缺失信息集中列在 `profile/MISSING_INFO.md`；
6) 没有任何提交、报名、发送或登录行为。"""),
    ("求职总控台与周计划", 60, """汇总全部产出，生成 `Career_Tracker.xlsx`：机会（状态/优先级/截止/材料就绪度/下一步）、申请材料清单、外联记录、面试准备进度、竞赛；
截止日期 14 天内标红。写 `WEEKLY_PLAN.md`（从今天到 2027-03 的每周计划，每周 5-8 小时可执行）和 `START_HERE.md`（用户第一次打开应该看什么、
哪些 FILL_SHEET 优先拿给 Claude 确认、所有「❓需用户补充」汇总）。"""),
]

cats = {c["name"]: c for c in q["categories"]}
career = cats.get("实习就业") or {"name": "实习就业", "kind": "tasks", "tasks": []}
career["enabled"] = True
have = {t["name"] for t in career["tasks"]}
added = 0
for name, mins, body in NEW:
    if name in have:
        continue
    career["tasks"].append({"name": name, "dir": C, "timeout_min": mins, "prompt": CTX + body + NO})
    added += 1
cats["实习就业"] = career
order = ["IB分析", "实习就业", "Coding项目", "今日重点", "生活项目", "其他任务"]
q["categories"] = [cats[n] for n in order if n in cats] + [c for n, c in cats.items() if n not in order]
for c in q["categories"]:
    if c["name"] == "生活项目":
        c["enabled"] = False
json.dump(q, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"✅ 实习就业：新增 {added} 个任务，共 {len(career['tasks'])} 个")
for i, t in enumerate(career["tasks"], 1):
    print(f"   {i:2d}. {t['name']}")
