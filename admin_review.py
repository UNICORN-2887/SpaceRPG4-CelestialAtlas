"""
SpaceRPG4 知识库审核工具
- 自动扫描 QQ 邮箱中标题为"新的知识库提交"的邮件
- 解析 JSON 内容，列出所有待审核条目
- 勾选通过 → 一键更新到公共知识库
"""

import imaplib
import email
import json
import re
import os
import sys
from email.header import decode_header

# ========== 配置 ==========
IMAP_SERVER = "imap.qq.com"
IMAP_PORT = 993
EMAIL_ADDR = ""  # 你的QQ邮箱
EMAIL_PWD = ""   # QQ邮箱授权码（不是密码）
KB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "kb_config.html")

# ========== 获取邮件 ==========
def fetch_submissions():
    if not EMAIL_ADDR or not EMAIL_PWD:
        print("❌ 请先填写 EMAIL_ADDR 和 EMAIL_PWD")
        return []

    print(f"📧 连接 {IMAP_SERVER}...")
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL_ADDR, EMAIL_PWD)
    mail.select("INBOX")

    # 搜索标题包含"新的知识库提交"的邮件
    status, messages = mail.search(None, 'SUBJECT', '"新的知识库提交"')
    if status != "OK":
        print("❌ 搜索失败")
        return []

    submissions = []
    for num in messages[0].split():
        status, data = mail.fetch(num, "(RFC822)")
        if status != "OK":
            continue
        msg = email.message_from_bytes(data[0][1])

        # 解码标题
        subject = ""
        for s, charset in decode_header(msg["Subject"]):
            if isinstance(s, bytes):
                subject += s.decode(charset or "utf-8", errors="ignore")
            else:
                subject += s

        # 提取正文
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        else:
            body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")

        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*"toolKB"[\s\S]*\}', body)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                submissions.append({
                    "author": data.get("author", "?"),
                    "note": data.get("note", ""),
                    "toolKB": data.get("toolKB", []),
                    "gameKB": data.get("gameKB", []),
                    "customRules": data.get("customRules", []),
                    "subject": subject,
                })
            except json.JSONDecodeError:
                pass

    mail.logout()
    return submissions


# ========== 终端审核界面 ==========
def review(submissions):
    if not submissions:
        print("\n📭 没有待审核的提交")
        return

    # 收集所有唯一条目
    all_entries = {}
    categories = ["toolKB", "gameKB", "customRules"]
    cat_names = {"toolKB": "工具操作", "gameKB": "游戏机制", "customRules": "自定义规则"}

    for sub in submissions:
        for cat in categories:
            for entry in sub.get(cat, []):
                key = entry.strip()
                if key not in all_entries:
                    all_entries[key] = {"cat": cat, "entry": entry, "authors": []}
                all_entries[key]["authors"].append(sub["author"])

    # 显示所有条目
    entries_list = list(all_entries.items())
    print(f"\n{'='*60}")
    print(f"📋 共 {len(entries_list)} 条待审核知识库条目（来自 {len(submissions)} 封邮件）")
    print(f"{'='*60}\n")

    for i, (key, info) in enumerate(entries_list):
        cat = cat_names.get(info["cat"], info["cat"])
        authors = ", ".join(set(info["authors"]))
        entry_text = info["entry"][:80] + ("..." if len(info["entry"]) > 80 else "")
        print(f"[{i+1}] [{cat}] {entry_text}")
        print(f"    提交者: {authors}")
        print()

    # 用户选择
    print(f"{'='*60}")
    print("输入要通过的编号（逗号分隔，如 1,3,5），输入 all 全部通过，输入 q 退出")
    choice = input("> ").strip()

    if choice.lower() == "q":
        return
    elif choice.lower() == "all":
        selected = list(range(len(entries_list)))
    else:
        selected = []
        for part in choice.split(","):
            part = part.strip()
            if "-" in part:
                a, b = part.split("-", 1)
                selected.extend(range(int(a) - 1, int(b)))
            elif part.isdigit():
                selected.append(int(part) - 1)

    if not selected:
        print("❌ 未选择任何条目")
        return

    # 确认
    print(f"\n将添加 {len(selected)} 条到公共知识库，确认？(y/n)")
    if input("> ").strip().lower() != "y":
        return

    # 更新 kb_config.html
    update_config([entries_list[i][1] for i in selected])

    print(f"✅ 已更新 {len(selected)} 条到公共知识库！")
    print("现在 git commit && git push 即可部署。")


def update_config(approved):
    if not os.path.exists(KB_CONFIG_PATH):
        print(f"❌ 找不到 {KB_CONFIG_PATH}")
        return

    with open(KB_CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # 分类条目
    new_tool = []
    new_game = []
    new_rules = []
    for info in approved:
        entry = info["entry"]
        if info["cat"] == "toolKB":
            new_tool.append(entry)
        elif info["cat"] == "gameKB":
            new_game.append(entry)
        elif info["cat"] == "customRules":
            new_rules.append(entry)

    # 在 DEFAULTS 的对应数组中追加
    for cat_name, new_entries in [("toolKB", new_tool), ("gameKB", new_game), ("customRules", new_rules)]:
        if not new_entries:
            continue
        # 找到数组的最后一个元素，在 ] 前插入新条目
        pattern = rf"(config\.{cat_name}\s*=\s*\[)"
        # 找到匹配位置
        match = re.search(pattern, content)
        if not match:
            continue
        # 找到对应数组的结束 ]
        start = match.end()
        # 找到匹配的 ]
        depth = 1
        end_pos = start
        for i in range(start, len(content)):
            if content[i] == "[":
                depth += 1
            elif content[i] == "]":
                depth -= 1
                if depth == 0:
                    end_pos = i
                    break

        # 在 ] 前插入
        insert_str = ""
        for entry in new_entries:
            escaped = entry.replace("\\", "\\\\").replace("'", "\\'")
            insert_str += f"\n    '{escaped}',"

        content = content[:end_pos] + insert_str + content[end_pos:]

    with open(KB_CONFIG_PATH, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"  工具: +{len(new_tool)}  游戏: +{len(new_game)}  规则: +{len(new_rules)}")


# ========== Main ==========
if __name__ == "__main__":
    print("=" * 60)
    print("SpaceRPG4 知识库审核工具")
    print("=" * 60)

    subs = fetch_submissions()
    review(subs)
