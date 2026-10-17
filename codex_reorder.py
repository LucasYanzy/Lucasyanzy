import json, os
p = os.path.expanduser("~/codex-auto/queue.json")
q = json.load(open(p, encoding="utf-8"))
C = "~/Desktop/G_Career/Codex_Career"
NOSUBMIT = ("\n**绝对不要提交任何申请、不要登录任何网站账号、不要在线填写表单、不要发邮件或消息。"
            "只在本地准备材料，所有需要用户亲自提交的步骤写进 `NEXT_STEPS.md`。**\n")
ctx = ("用户背景：Rutgers 大二学生；兴趣方向：金融/投资（IB 持仓分析、量化、VC）、AI 与编程项目"
       "（~/Desktop/Project 下的 DAshi、TradingAgents、HackRU26、VC AgentPro、Breathless 等）。"
       "先阅读 ~/Desktop/G_Career（尤其 G_Application）里的已有简历、申请记录和笔记，了解过去申请过什么、"
       "踩过什么坑（用户提到过“不要犯之前汇丰的错误”），避免重复。\n")
career = {"name": "实习就业", "kind": "tasks", "enabled": True, "tasks": [
  {"name": "简历修改", "dir": C, "timeout_min": 90, "prompt": ctx + """
1. 在 ~/Desktop/G_Career、~/Documents、~/Downloads 里找用户的简历（文件名含 resume / CV / 简历，pdf/docx/md），找最新版本。**原文件不要改**。
2. 逐条点评：结构、措辞（动词开头、量化成果）、ATS 友好度、拼写语法、与目标岗位的匹配度。
3. 产出到 `resume/`：一份改进后的通用版（.docx + .md），以及按方向定制的版本：金融（IB/S&T/资管）、量化、软件/AI、VC/创投。
   把 ~/Desktop/Project 里有亮点的项目整理成简历条目备选（`project_bullets.md`），不要编造经历或数据。
4. 写 `resume/REVIEW.md`：主要改动、理由、还需要用户补充的信息。""" + NOSUBMIT},
  {"name": "实习职位与比赛搜索", "dir": C, "timeout_min": 120, "prompt": ctx + """
联网搜索适合大二学生的机会（以公开网页为准，注明链接和查询日期）：
- 实习：2027 暑期实习、大二/早期项目（sophomore / early insight / diversity programs），方向：投行、S&T、资管、量化、科技/AI、VC；优先纽约/新泽西及远程；
- 比赛竞赛：投资/案例比赛、量化与交易比赛、黑客松、数据科学/AI 比赛、创业比赛；
- Rutgers 校内资源（职业中心活动、社团、宣讲会）。
产出到 `opportunities/`：`Opportunities.xlsx`（同时导出 `.csv`），列：名称、机构、类型、方向、地点、资格要求、截止日期、链接、匹配度(1-5)及理由、所需材料、状态(未申请)。
按截止日期排序，标出 30 天内截止的；写 `opportunities/TOP10.md` 推荐最该优先申请的 10 个及原因。""" + NOSUBMIT},
  {"name": "申请材料准备（不提交）", "dir": C, "timeout_min": 120, "prompt": ctx + """
基于 `opportunities/TOP10.md`（如果还没有，先自己挑 5 个最合适的机会）和 `resume/` 里的简历：
1. 为每个机会建一个文件夹 `applications/<机构_项目>/`，里面放：该用哪版简历、定制 cover letter（.docx + .md）、常见申请问答/short answers 的草稿、
   behavioral 与技术面试准备要点、申请清单（需要哪些材料、截止日期、提交链接）。
2. 每个文件夹里写一份 `FILL_SHEET.md`（申请表填写单）：按该申请网站/表单的实际字段顺序列出（先联网查看公开的申请页面或往年申请问题；查不到就按同类项目的常见字段），
   表格列：字段名 / 草稿答案（可直接复制粘贴，注意字数限制）/ 字数 / 依据 / 状态。状态一律写「⏳ 待确认」，不确定的事实写「❓需用户补充」，**不要编造任何个人信息或经历**。
   用户会把填写单拿给 Claude 一起逐条确认，确认后改成「✅ 已确认」，再由用户自己复制到申请网站并亲自提交。
3. 写 `applications/APPLICATION_PLAN.md`：申请顺序、每周时间表、每个申请需要用户亲自完成的步骤，以及所有「❓需用户补充」的问题汇总。
**这些只是草稿，全部由用户检查后自己提交。**""" + NOSUBMIT},
]}
cats = {c["name"]: c for c in q["categories"]}
cats["实习就业"] = career
order = ["IB分析", "实习就业", "Coding项目", "今日重点", "生活项目", "其他任务"]
q["categories"] = [cats[n] for n in order if n in cats] + [c for n, c in cats.items() if n not in order]
json.dump(q, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("✅ 新顺序: " + " → ".join(c["name"] for c in q["categories"]))
