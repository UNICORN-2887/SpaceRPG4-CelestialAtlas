"""
SpaceRPG4 知识库审核工具
- IMAP扫描QQ邮箱 → AI预审去重 → 终端勾选 → 更新公共知识库
"""
import imaplib, email, json, re, os, requests
from email.header import decode_header

IMAP_SERVER = "imap.qq.com"
EMAIL_ADDR = "2198823120@qq.com"
EMAIL_PWD = "bvbgoplsnkijecfb"
KB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "kb_config.html")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

def _load_key():
    cfg = os.path.join(os.path.dirname(__file__), "_api_config.json")
    if os.path.exists(cfg):
        try:
            with open(cfg) as f: return json.load(f).get('apiKey','')
        except: pass
    return ''
DEEPSEEK_KEY = _load_key()

def fetch_submissions():
    if not EMAIL_ADDR or not EMAIL_PWD:
        print("Missing EMAIL_ADDR/EMAIL_PWD"); return []
    print(f"Connecting {IMAP_SERVER}...")
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ADDR, EMAIL_PWD)
    submissions = []
    for folder in ["INBOX", '"Sent Messages"', '"Sent"']:
        try: mail.select(folder)
        except: continue
        print(f"  Folder: {folder}")
        status, msgs = mail.search(None, 'ALL')
        if status != "OK": continue
        for num in msgs[0].split()[-30:]:
            status, data = mail.fetch(num, "(RFC822)")
            if status != "OK": continue
            msg = email.message_from_bytes(data[0][1])
            subject = ""
            for s, cs in decode_header(msg["Subject"]):
                subject += s.decode(cs or "utf-8", errors="ignore") if isinstance(s, bytes) else s
            # 快速过滤
            if not subject.startswith("新的知识库提交"):
                continue
            print(f"  MATCH: {subject[:50]}")
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ct = part.get_content_type()
                    if ct in ("text/plain", "text/html"):
                        p = part.get_payload(decode=True)
                        if p: body += p.decode("utf-8", errors="ignore")
            else:
                p = msg.get_payload(decode=True)
                if p: body = p.decode("utf-8", errors="ignore")
            # 清理HTML
            body = re.sub(r'<[^>]+>', '', body)
            # 括号匹配找JSON
            start = body.find('{"toolKB"')
            if start < 0: start = body.find('{\n"toolKB"')
            if start >= 0:
                depth = 0; end = -1
                for i in range(start, len(body)):
                    if body[i] == '{': depth += 1
                    elif body[i] == '}':
                        depth -= 1
                        if depth == 0: end = i; break
                if end >= 0:
                    raw = body[start:end+1]
                    try:
                        data = json.loads(raw)
                        submissions.append({
                            "author": data.get("author","?"), "note": data.get("note",""),
                            "toolKB": data.get("toolKB",[]), "gameKB": data.get("gameKB",[]),
                            "customRules": data.get("customRules",[]), "subject": subject,
                        })
                        n = len(data.get('toolKB',[]))+len(data.get('gameKB',[]))+len(data.get('customRules',[]))
                        print(f"    Parsed: {n} entries")
                    except Exception as e:
                        print(f"    JSON error: {e}")
                        print(f"    Raw[100:200]: {raw[100:200]}")
    mail.logout()
    return submissions

def ai_dedup(entries, defaults):
    if not DEEPSEEK_KEY or not entries: return entries, []
    dtext = "\n".join(f"{i+1}. {d[:80]}" for i,d in enumerate(defaults))
    ntext = "\n".join(f"{i+1}. {e}" for i,e in enumerate(entries))
    prompt = f"判断新条目是否与默认重复。\n默认:\n{dtext}\n新:\n{ntext}\n输出JSON: [{{\"idx\":序号,\"verdict\":\"dup或new\",\"reason\":\"原因\"}}]"
    try:
        r = requests.post(DEEPSEEK_URL,
            headers={"Content-Type":"application/json","Authorization":f"Bearer {DEEPSEEK_KEY}"},
            json={"model":"deepseek-chat","messages":[{"role":"user","content":prompt}],"max_tokens":500,"temperature":0}, timeout=30)
        verdicts = json.loads(re.findall(r'\[.*\]', r.json()["choices"][0]["message"]["content"], re.DOTALL)[0])
        merged, new = [], []
        for v in verdicts:
            idx = v["idx"]-1
            if idx < len(entries):
                (merged if v["verdict"]=="dup" else new).append({"entry":entries[idx],"reason":v.get("reason","")})
        return [m["entry"] for m in new], merged
    except Exception as e:
        print(f"  AI error: {e}")
        return entries, []

def _get_defaults():
    if not os.path.exists(KB_CONFIG_PATH): return []
    with open(KB_CONFIG_PATH, encoding="utf-8") as f: content = f.read()
    defaults = []
    for arr in ["_DEF_TOOL", "_DEF_GAME", "_DEF_RULES"]:
        m = re.search(rf'{arr}\s*=\s*\[(.*?)\];', content, re.DOTALL)
        if m: defaults.extend(re.findall(r"'(.*?)'", m.group(1)))
    return defaults

def review(submissions):
    if not submissions: print("\nNo submissions"); return
    all_entries = {}
    cats = {"toolKB":"工具操作","gameKB":"游戏机制","customRules":"自定义规则"}
    for sub in submissions:
        for cat in ["toolKB","gameKB","customRules"]:
            for entry in sub.get(cat,[]):
                k = entry.strip()
                if k not in all_entries: all_entries[k] = {"cat":cat,"entry":entry,"authors":[]}
                all_entries[k]["authors"].append(sub["author"])

    all_defs = _get_defaults()
    if DEEPSEEK_KEY and all_entries:
        raw = list(all_entries.values())
        print("\nAI dedup...")
        new_texts, merged = ai_dedup([v["entry"] for v in raw], all_defs)
        if merged:
            print(f"  Merged {len(merged)} similar:")
            for m in merged: print(f"    - {m['entry'][:60]}...")
        all_entries = {}
        for e in raw:
            if e["entry"] in new_texts:
                all_entries[e["entry"].strip()] = e
        print(f"  {len(all_entries)} remaining for review")

    entries_list = list(all_entries.items())
    print(f"\n{'='*60}\n{len(entries_list)} entries from {len(submissions)} emails\n{'='*60}")
    for i, (k, info) in enumerate(entries_list):
        e = info["entry"][:80] + ("..." if len(info["entry"])>80 else "")
        print(f"[{i+1}] [{cats.get(info['cat'],info['cat'])}] {e}")
        print(f"    By: {', '.join(set(info['authors']))}")

    choice = input("\nApprove (1,3,5 / all / q): ").strip()
    if choice == "q": return
    selected = list(range(len(entries_list))) if choice == "all" else []
    if not selected:
        for p in choice.split(","):
            p = p.strip()
            if "-" in p:
                a,b = p.split("-",1); selected.extend(range(int(a)-1,int(b)))
            elif p.isdigit(): selected.append(int(p)-1)
    if not selected: return
    if input(f"Add {len(selected)} entries? (y/n): ").strip() != "y": return
    update_config([entries_list[i][1] for i in selected])

def update_config(approved):
    if not os.path.exists(KB_CONFIG_PATH): return
    with open(KB_CONFIG_PATH, encoding="utf-8") as f: content = f.read()
    for cat, arr_name in [("toolKB","_DEF_TOOL"),("gameKB","_DEF_GAME"),("customRules","_DEF_RULES")]:
        entries = [info["entry"] for info in approved if info["cat"]==cat]
        if not entries: continue
        m = re.search(rf'{arr_name}\s*=\s*\[', content)
        if not m: continue
        start = m.end()
        depth = 1; end_pos = start
        for i in range(start, len(content)):
            if content[i] == '[': depth += 1
            elif content[i] == ']':
                depth -= 1
                if depth == 0: end_pos = i; break
        parts = []
        for e in entries:
            esc = e.replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"\n    '{esc}',")
        insert = "".join(parts)
        content = content[:end_pos] + insert + content[end_pos:]
    with open(KB_CONFIG_PATH, "w", encoding="utf-8") as f: f.write(content)
    print("Updated. git commit && git push to deploy.")

if __name__ == "__main__":
    print("="*60 + "\nSpaceRPG4 Admin Review\n" + "="*60)
    subs = fetch_submissions()
    review(subs)
