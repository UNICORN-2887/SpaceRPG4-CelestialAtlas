"""
SpaceRPG4 管理面板 — 浏览器中审核知识库提交
运行后打开 http://127.0.0.1:8888
"""
import json, re, os, imaplib, email, threading, webbrowser, time
from email.header import decode_header
from http.server import HTTPServer, BaseHTTPRequestHandler

IMAP_SERVER = "imap.qq.com"
EMAIL_ADDR = "2198823120@qq.com"
EMAIL_PWD = "bvbgoplsnkijecfb"
KB_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "kb_config.html")
PORT = 8888

# 全局缓存
_cached_subs = []
_cache_time = 0

def fetch_submissions():
    global _cached_subs, _cache_time
    if time.time() - _cache_time < 30 and _cached_subs:
        return _cached_subs

    submissions = []
    mail = imaplib.IMAP4_SSL(IMAP_SERVER)
    mail.login(EMAIL_ADDR, EMAIL_PWD)
    for folder in ["INBOX", '"Sent Messages"', '"Sent"']:
        try: mail.select(folder)
        except: continue
        status, msgs = mail.search(None, 'ALL')
        if status != "OK": continue
        for num in msgs[0].split()[-30:]:
            status, data = mail.fetch(num, "(RFC822)")
            if status != "OK": continue
            msg = email.message_from_bytes(data[0][1])
            subject = ""
            for s, cs in decode_header(msg["Subject"]):
                subject += s.decode(cs or "utf-8", errors="ignore") if isinstance(s, bytes) else s
            if not subject.startswith("新的知识库提交"): continue
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
            body = re.sub(r'<[^>]+>', '', body)
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
                    try:
                        data = json.loads(body[start:end+1])
                        submissions.append({
                            "author": data.get("author","?"), "note": data.get("note",""),
                            "toolKB": data.get("toolKB",[]), "gameKB": data.get("gameKB",[]),
                            "customRules": data.get("customRules",[]),
                        })
                    except: pass
    mail.logout()
    _cached_subs = submissions
    _cache_time = time.time()
    return submissions

def get_defaults():
    if not os.path.exists(KB_CONFIG_PATH): return []
    with open(KB_CONFIG_PATH, encoding="utf-8") as f: c = f.read()
    defaults = []
    for arr in ["_DEF_TOOL", "_DEF_GAME", "_DEF_RULES"]:
        m = re.search(rf'{arr}\s*=\s*\[(.*?)\];', c, re.DOTALL)
        if m: defaults.extend(re.findall(r"'(.*?)'", m.group(1)))
    return defaults

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.serve_page()
        elif self.path == "/api/entries":
            self.serve_json(self.get_all_entries())
        elif self.path == "/api/defaults":
            self.serve_json(get_defaults())
        elif self.path.startswith("/approve"):
            self.handle_approve()
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        if self.path == "/approve":
            self.handle_approve()
        else:
            self.send_response(404); self.end_headers()

    def get_all_entries(self):
        subs = fetch_submissions()
        all_entries = {}
        for sub in subs:
            for cat in ["toolKB", "gameKB", "customRules"]:
                for entry in sub.get(cat, []):
                    k = entry.strip()
                    if k not in all_entries:
                        all_entries[k] = {"cat": cat, "entry": entry, "authors": []}
                    all_entries[k]["authors"].append(sub["author"])
        return list(all_entries.values())

    def handle_approve(self):
        content_len = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_len).decode()
        data = json.loads(body)
        approved = data.get("approved", [])
        if approved:
            self.update_config(approved)
        self.serve_json({"ok": True, "count": len(approved)})

    def update_config(self, approved):
        if not os.path.exists(KB_CONFIG_PATH): return
        with open(KB_CONFIG_PATH, encoding="utf-8") as f: content = f.read()
        for cat, arr_name in [("toolKB","_DEF_TOOL"),("gameKB","_DEF_GAME"),("customRules","_DEF_RULES")]:
            entries = [e["entry"] for e in approved if e.get("cat")==cat]
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
            insert = ""
            for e in entries:
                esc = e.replace("\\", "\\\\").replace("'", "\\'")
                insert += f"\n    '{esc}',"
            insert += "\n"
            content = content[:end_pos] + insert + content[end_pos:]
        with open(KB_CONFIG_PATH, "w", encoding="utf-8") as f: f.write(content)

    def serve_page(self):
        html = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><title>SpaceRPG4 Admin</title>
<style>
:root{--bg:#0a0e17;--panel:#111827;--border:#1e293b;--t:#cbd5e1;--a:#3b82f6;--g:#10b981;--r:#ef4444;--y:#f59e0b}
body{font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--t);margin:0;padding:20px}
h1{color:#fff;font-size:20px}h1 span{color:var(--a)}
.section{margin:16px 0;padding:12px;border-radius:8px}
.section h2{font-size:14px;margin:0 0 10px}
.tool{background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.2)}.tool h2{color:var(--a)}
.game{background:rgba(16,185,129,.08);border:1px solid rgba(16,185,129,.2)}.game h2{color:var(--g)}
.rules{background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.2)}.rules h2{color:var(--y)}
.item{display:flex;align-items:flex-start;gap:10px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:13px}
.item:last-child{border:none}
.item input[type=checkbox]{margin-top:2px;accent-color:var(--a);transform:scale(1.1)}
.item .text{flex:1;line-height:1.4}
.item .authors{font-size:10px;color:#64748b}
.empty{color:#64748b;font-style:italic;padding:10px 0}
.btn{padding:8px 20px;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600;margin:8px 8px 0 0}
.btn-approve{background:var(--a);color:#fff}.btn-approve:hover{opacity:.9}
.btn-refresh{background:transparent;border:1px solid var(--border);color:var(--t)}
.status{font-size:12px;color:var(--g);margin-left:10px}
#loading{display:none;color:var(--y)}
</style></head><body>
<h1>SpaceRPG4 <span>Admin Panel</span></h1>
<p style="font-size:12px;color:#64748b">勾选通过 → 点击批准 → 自动写入 kb_config.html → git push 部署</p>
<button class="btn btn-refresh" onclick="load()">🔄 刷新</button>
<span id="loading">处理中...</span>
<span id="status" class="status"></span>
<div id="content"></div>
<script>
async function load(){
  document.getElementById("loading").style.display="inline";
  var r=await fetch("/api/entries");var entries=await r.json();
  var r2=await fetch("/api/defaults");var defaults=await r2.json();
  var defSet=new Set(defaults);
  var cats={toolKB:{name:"工具操作知识库",cls:"tool"},gameKB:{name:"游戏机制知识库",cls:"game"},customRules:{name:"自定义规则",cls:"rules"}};
  var grouped={toolKB:[],gameKB:[],customRules:[]};
  for(var e of entries){
    if(!defSet.has(e.entry)) grouped[e.cat].push(e);
  }
  var h="";
  for(var c in cats){
    var list=grouped[c];
    h+='<div class="section '+cats[c].cls+'"><h2>'+cats[c].name+' ('+list.length+'条)</h2>';
    if(!list.length) h+='<div class="empty">无新增条目</div>';
    for(var i=0;i<list.length;i++){
      var e=list[i];
      h+='<div class="item"><input type="checkbox" id="chk_'+c+'_'+i+'" data-cat="'+c+'" data-entry="'+e.entry.replace(/"/g,"&quot;").replace(/'/g,"&#39;")+'"><label for="chk_'+c+'_'+i+'"><div class="text">'+e.entry+'</div><div class="authors">提交者: '+[...new Set(e.authors)].join(", ")+'</div></label></div>';
    }
    h+='</div>';
  }
  document.getElementById("content").innerHTML=h;
  document.getElementById("loading").style.display="none";
}
async function approve(){
  var checks=document.querySelectorAll("input[type=checkbox]:checked");
  var approved=[];
  for(var c of checks){
    approved.push({cat:c.dataset.cat,entry:c.dataset.entry});
  }
  if(!approved.length){alert("请先勾选条目");return}
  if(!confirm("确认批准 "+approved.length+" 条条目？")) return;
  document.getElementById("loading").style.display="inline";
  var r=await fetch("/approve",{method:"POST",body:JSON.stringify({approved})});
  var data=await r.json();
  document.getElementById("status").textContent="✅ 已批准 "+data.count+" 条！现在 git commit && git push 即可部署。";
  document.getElementById("loading").style.display="none";
  load();
}
load();
</script>
<button class="btn btn-approve" onclick="approve()">✅ 批准选中条目</button>
</body></html>'''
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def log_message(self, *args): pass

if __name__ == "__main__":
    print(f"Admin Panel: http://127.0.0.1:{PORT}")
    webbrowser.open(f"http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
