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
import requests
from email.header import decode_header

# ========== 配置 ==========
IMAP_SERVER = "imap.qq.com"
IMAP_PORT = 993
EMAIL_ADDR = "2198823120@qq.com"
EMAIL_PWD = "bvbgoplsnkijecfb"
KB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "kb_config.html")
# 从 _api_config.json 读取（和 OCR 脚本共用配置）
def _load_key():
    cfg_path = os.path.join(os.path.dirname(__file__), "_api_config.json")
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r') as f:
                return json.load(f).get('apiKey', '')
        except: pass
    return ''
DEEPSEEK_KEY = _load_key()
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# ========== 获取邮件（搜索收件箱+已发送） ==========
def fetch_submissions():
    if not EMAIL_ADDR or not EMAIL_PWD:
        print("❌ 请先填写 EMAIL_ADDR 和 EMAIL_PWD")
        return []

    print(f"📧 连接 {IMAP_SERVER}...")
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL_ADDR, EMAIL_PWD)

    submissions = []
    # 搜索多个文件夹
    for folder in ["INBOX", '"Sent Messages"', '"已发送"', '"Sent"']:
        try:
            mail.select(folder)
        except:
            continue
        print(f"  检查文件夹: {folder}")

        status, messages = mail.search(None, 'ALL')
        if status != "OK":
            continue

        msg_nums = messages[0].split()[-50:]  # 最近50封
        print(f"    共 {len(msg_nums)} 封邮件")

        for num in msg_nums:
            status, data = mail.fetch(num, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(data[0][1])

            subject = ""
            for s, charset in decode_header(msg["Subject"]):
                if isinstance(s, bytes):
                    subject += s.decode(charset or "utf-8", errors="ignore")
                else:
                    subject += s

            print(f"    标题: {subject[:60]}...")

            if "新的知识库提交" not in subject and "知识库提交" not in subject:
                continue

            print(f"    ✅ 匹配到知识库提交！")

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct == "text/plain" or ct == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body += payload.decode("utf-8", errors="ignore")
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="ignore")

            # 调试：打印正文前200字符
            print(f"      正文预览: {body[:200]}...")
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
                    print(f"      解析成功: {len(data.get('toolKB',[]))+len(data.get('gameKB',[]))+len(data.get('customRules',[]))} 条")
                except json.JSONDecodeError:
                    print(f"      JSON解析失败")

    mail.logout()
    return submissions


# ========== AI 预审：去重合并相似条目 ==========
def ai_dedup(entries, defaults):
    """用 DeepSeek 比较新条目和默认条目，合并相似的"""
    if not DEEPSEEK_KEY or not entries:
        return entries, []

    defs_text = "\n".join(f"{i+1}. {d[:80]}" for i, d in enumerate(defaults))
    new_text = "\n".join(f"{i+1}. {e}" for i, e in enumerate(entries))

    prompt = f"""你是知识库审核助手。判断以下新提交条目是否与已有默认条目重复或高度相似。

已有默认条目:
{defs_text}

新提交条目:
{new_text}

对每条新条目，判断是否与某条默认条目"重复/高度相似"或"全新"。
输出JSON数组: [{{"idx": 新条目序号(从1开始), "verdict": "dup"或"new", "reason": "简短原因"}}]
只输出JSON，不要其他内容。"""

    try:
        r = requests.post(DEEPSEEK_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_KEY}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": 500, "temperature": 0},
            timeout=30)
        result = r.json()["choices"][0]["message"]["content"]
        verdicts = json.loads(re.findall(r'\[.*\]', result, re.DOTALL)[0])
        merged = []
        new_only = []
        for v in verdicts:
            idx = v["idx"] - 1
            if idx < len(entries):
                if v["verdict"] == "dup":
                    merged.append({"entry": entries[idx], "reason": v.get("reason", "")})
                else:
                    new_only.append(entries[idx])
        return new_only, merged
    except Exception as e:
        print(f"  ⚠️ AI预审失败: {e}")
        return entries, []


# ========== 终端审核界面 ==========
def review(submissions):
    if not submissions:
        print("\n📭 没有待审核的提交")
        return

    # 收集所有唯一条目
    all_entries = {}
    categories = ["toolKB", "gameKB", "customRules"]
    cat_names = {"toolKB": "工具操作", "gameKB": "游戏机制", "customRules": "自定义规则"}
    all_defaults = _get_defaults()

    for sub in submissions:
        for cat in categories:
            for entry in sub.get(cat, []):
                key = entry.strip()
                if key not in all_entries:
                    all_entries[key] = {"cat": cat, "entry": entry, "authors": []}
                all_entries[key]["authors"].append(sub["author"])

    # AI 预审去重
    if DEEPSEEK_KEY and all_entries:
        entries_list_raw = [v for v in all_entries.values()]
        entries_texts = [v["entry"] for v in entries_list_raw]
        print("\n🤖 AI预审中...")
        new_texts, merged = ai_dedup(entries_texts, all_defaults)
        if merged:
            print(f"  ✅ 自动合并 {len(merged)} 条相似条目:")
            for m in merged:
                print(f"     - {m['entry'][:60]}... → {m['reason']}")
        # 只保留全新条目
        all_entries = {}
        for e in entries_list_raw:
            if e["entry"] in new_texts:
                key = e["entry"].strip()
                all_entries[key] = e
        print(f"  剩余 {len(all_entries)} 条需人工审核\n")

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


def _get_defaults():
    """从 kb_config.html 读取内置默认知识库"""
    if not os.path.exists(KB_CONFIG_PATH):
        return []
    with open(KB_CONFIG_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    defaults = []
    for arr_name in ["_DEF_TOOL", "_DEF_GAME", "_DEF_RULES"]:
        pattern = rf'{arr_name}\s*=\s*\[(.*?)\];'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            # 提取数组中的字符串
            arr_text = match.group(1)
            entries = re.findall(r"'(.*?)'", arr_text)
            defaults.extend(entries)
    return defaults

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
