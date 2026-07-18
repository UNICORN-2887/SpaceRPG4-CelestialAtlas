"""
SpaceRPG4 场景检测器
- 持续截图（每1秒）
- 鼠标框选一个持续识别区域
- 检测 "Bar"→进入酒吧  "Trade"→进入贸易中心
"""

# 自动安装依赖
import subprocess, os, sys
def _ensure(pkg, imp):
    try: __import__(imp); return
    except: subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])
_ensure('opencv-python', 'cv2')
_ensure('numpy<2', 'numpy')
_ensure('easyocr', 'easyocr')
_ensure('requests', 'requests')
_ensure('Pillow', 'PIL')
_ensure('scikit-image', 'skimage')

import json, time, re, threading
import cv2, numpy as np, easyocr, requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageDraw, ImageFont

# ========== 配置 ==========
# 从配置文件读取（优先），否则使用默认值
def _load_ocr_config():
    import json as _json
    config_path = os.path.join(os.path.dirname(__file__), "_api_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = _json.load(f)
            oc = cfg.get('ocrConfig', {})
            return oc.get('adbPath', ADB_EXE_DEFAULT), oc.get('deviceId', ADB_DEVICE_DEFAULT), oc.get('interval', 1.0), oc.get('port', 8765)
        except: pass
    return ADB_EXE_DEFAULT, ADB_DEVICE_DEFAULT, 1.0, 8765

ADB_EXE_DEFAULT = r"D:\工程\MuMu Player 12\nx_main\adb.exe"
ADB_DEVICE_DEFAULT = "emulator-5554"
ADB_EXE, ADB_DEVICE, SCAN_INTERVAL, HTTP_PORT = _load_ocr_config()

# 自动检测ADB设备
def _auto_detect_device():
    import subprocess as _sp
    try:
        r = _sp.run(f'"{ADB_EXE}" devices', shell=True, capture_output=True, text=True)
        for line in r.stdout.split('\n'):
            line = line.strip()
            if line and 'device' in line and 'List' not in line:
                return line.split('\t')[0].split(' ')[0]
    except: pass
    return None

_auto = _auto_detect_device()
if _auto and not ADB_DEVICE.startswith('127.'):
    # Only override if the configured device doesn't exist but auto-detect found something
    r = subprocess.run(f'"{ADB_EXE}" -s {ADB_DEVICE} shell echo ok', shell=True, capture_output=True, text=True)
    if 'ok' not in r.stdout:
        print(f"⚠️ 配置设备{ADB_DEVICE}不可用，自动切换为 {_auto}")
        ADB_DEVICE = _auto
print(f"📱 ADB设备: {ADB_DEVICE}")
TEMP_SCREENSHOT = os.path.join(os.path.dirname(__file__), "_ocr_temp_scene.png")
REGION_JSON = os.path.join(os.path.dirname(__file__), "_scene_region.json")        # Bar/Trade 检测区
REFUEL_REGION_JSON = os.path.join(os.path.dirname(__file__), "_refuel_region.json")  # REFUEL 检测区
PLANET_REGION_JSON = os.path.join(os.path.dirname(__file__), "_planet_region.json")  # 星球名 OCR 区
OCR_REGIONS_JSON = os.path.join(os.path.dirname(__file__), "_ocr_regions.json")
TRADE_REGION_JSON = os.path.join(os.path.dirname(__file__), "_trade_region.json")
STARMAP_JSON = os.path.join(os.path.dirname(__file__), "spacerpg4_map_data.json")
# 从配置文件读取API密钥（优先），否则使用默认值
def _load_api_key():
    import json as _json
    config_path = os.path.join(os.path.dirname(__file__), "_api_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = _json.load(f)
            return cfg.get('apiKey', '')
        except: pass
    return ''  # 用户需在kb_config.html中导出配置

DEEPSEEK_API_KEY = _load_api_key()
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
SIDEBAR_W = 320

print("🔤 加载 EasyOCR (ch_sim+en)...", end=" ", flush=True)
ocr = easyocr.Reader(["ch_sim", "en"], gpu=True)
print("OK")

# 中文字体
_FONT_PATH = None
for p in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]:
    if os.path.exists(p): _FONT_PATH = p; break

def pil_text(img, text, xy, size, color):
    if not _FONT_PATH: return
    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    font = ImageFont.truetype(_FONT_PATH, size)
    draw.text(xy, text, font=font, fill=color)
    rgb = np.array(pil_img)
    img[:] = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

def capture_screen():
    # 自动连接（支持 IP:port 格式）
    if ':' in ADB_DEVICE and not ADB_DEVICE.startswith('emulator'):
        subprocess.run(f'"{ADB_EXE}" connect {ADB_DEVICE}', shell=True, capture_output=True)
    cmd = f'"{ADB_EXE}" -s {ADB_DEVICE} exec-out screencap -p > "{TEMP_SCREENSHOT}"'
    subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return cv2.imread(TEMP_SCREENSHOT)

def save_region(region):
    with open(REGION_JSON, 'w') as f:
        json.dump(list(region), f)

def save_json_file(path, data):
    with open(path, 'w') as f:
        json.dump(data, f)

def load_region():
    if os.path.exists(REGION_JSON):
        with open(REGION_JSON, 'r') as f:
            return tuple(json.load(f))
    return None

# ========== 全局状态 ==========
watch_region = load_region()     # Bar/Trade 检测区
refuel_region = None             # REFUEL 检测区
planet_region = None             # 星球名 OCR 区
drawing = False
drag_start = (0, 0)
current_scene = "?"
last_ocr_text = ""
last_scan_time = 0
img_raw = None
disp_scale = 1.0
disp_w, disp_h = 0, 0
# 状态机
docked = False             # 是否已停靠（检测到REFUEL）
current_system_id = None   # 当前所在星系的节点ID
bar_triggered = False
trade_triggered = False
sidebar_lines = []
starmap_data = None
ocr_regions_data = []
trade_region_data = None

# 加载 REFUEL/星球名/Trade 区域
def load_json_region(path):
    if os.path.exists(path):
        with open(path, 'r') as f: return json.load(f)
    return None

# 预设区域（所有用户的MuMu模拟器布局一致，可直接使用）
PRESET_REGIONS = {
    'refuel':     [1449, 923, 1561, 971],
    'planet':     [283, 25, 888, 88],
    'scene':      [158, 32, 584, 89],     # Bar/Trade检测
    'news':       [[155, 283, 912, 1019]], # 新闻OCR（Bar场景）
    'trade':      [1632, 20, 1916, 1006], # 价格OCR（Trade场景）
}

def apply_presets():
    global refuel_region, planet_region, watch_region, ocr_regions_data, trade_region_data
    refuel_region = PRESET_REGIONS['refuel']
    planet_region = PRESET_REGIONS['planet']
    watch_region = PRESET_REGIONS['scene']
    ocr_regions_data = PRESET_REGIONS['news']
    trade_region_data = PRESET_REGIONS['trade']
    # 保存到文件（下次启动直接加载）
    with open(REFUEL_REGION_JSON, 'w') as f: json.dump(refuel_region, f)
    with open(PLANET_REGION_JSON, 'w') as f: json.dump(planet_region, f)
    with open(REGION_JSON, 'w') as f: json.dump(watch_region, f)
    with open(OCR_REGIONS_JSON, 'w') as f: json.dump(ocr_regions_data, f)
    with open(TRADE_REGION_JSON, 'w') as f: json.dump(trade_region_data, f)
    print("✅ 已应用预设识别区域")

# 检查是否已有保存的区域
refuel_region = load_json_region(REFUEL_REGION_JSON)
planet_region = load_json_region(PLANET_REGION_JSON)
trade_region_data = load_json_region(TRADE_REGION_JSON)
watch_region = load_region()
ocr_regions_data = load_json_region(OCR_REGIONS_JSON) if os.path.exists(OCR_REGIONS_JSON) else None

has_saved = refuel_region and planet_region and watch_region and trade_region_data

if not has_saved:
    print("\n📐 未检测到识别区域配置")
    print("   [1] 应用预设区域（推荐，MuMu模拟器通用）")
    print("   [2] 手动标定区域（自定义布局）")
    choice = input("   请选择 (1/2): ").strip()
    if choice == '2':
        print("   进入手动标定模式...")
    else:
        apply_presets()
else:
    print(f"📂 已加载保存的区域")
    if refuel_region: print(f"   REFUEL: {refuel_region}")
    if planet_region: print(f"   星球名: {planet_region}")
    if watch_region: print(f"   Bar/Trade: {watch_region}")
    if trade_region_data: print(f"   Trade价格: {trade_region_data}")

# 加载星图
if os.path.exists(STARMAP_JSON):
    with open(STARMAP_JSON, 'r', encoding='utf-8') as f:
        starmap_data = json.load(f)
    print(f"📂 星图: {len(starmap_data.get('nodes',[]))}星系, {len(starmap_data.get('products',[]))}产品")

# 加载新闻OCR区域
if os.path.exists(OCR_REGIONS_JSON):
    with open(OCR_REGIONS_JSON, 'r') as f:
        ocr_regions_data = json.load(f)
    print(f"📂 新闻OCR区域: {len(ocr_regions_data)}个")

# ========== AI 管道 ==========
def build_news_prompt(ocr_texts):
    nodes = starmap_data.get("nodes", [])
    products = starmap_data.get("products", [])
    system_info = []
    for n in nodes:
        fac = n.get('faction', '') or ''
        name = n.get('name', '')
        planets = n.get('planets', []) or []
        trade_prods = []
        for p in planets:
            for item in (p.get('facilities', {}).get('trade', {}).get('products', []) or []):
                pid = item.get('productId') or item
                prod = next((pr for pr in products if pr.get('id') == pid), None)
                if prod: trade_prods.append(f"{prod.get('icon','')}{prod.get('name','')}(ID:{pid})")
        info = f"  {name}(ID:{n.get('id','')})"
        if fac: info += f" [{fac}]"
        if trade_prods: info += f" 贸易: {', '.join(trade_prods)}"
        system_info.append(info)
    ocr_text = "\n".join(f"  框{i+1}: {t}" for i, t in enumerate(ocr_texts))
    return f"""你是 SpaceRPG4 的 AI 助手。根据 OCR 新闻调整星图贸易产品价格波动。

## OCR 新闻
{ocr_text}

## 星图（仅列出有贸易品的星系，括号内为ID）
{chr(10).join(system_info)}

## 任务
1. 模糊匹配 OCR 中的星系名到星图中最相似的星系（如 "Sillil"→"Sillil"）
2. 判断产品价格涨(🔴 trend=1)或跌(🟢 trend=-1)
3. ⚠️ 必须使用星图中**确切的产品ID**！不要编造ID。产品ID在星图信息的括号中。
4. ⚠️ 使用星图中**确切的节点ID和行星ID**！不要编造。

## 输出格式（先简要分析，用 --- 分隔，再逐行输出指令）
spacerpgAPI.setTrend("节点ID", "", "产品ID", trend)
（行星ID留空即可，系统会自动搜索该星系所有行星）"""

def process_ai_response(response):
    """解析AI返回，验证并执行。返回 (display_lines, executed_count)"""
    nodes = starmap_data.get("nodes", [])
    products = starmap_data.get("products", [])
    node_map = {n.get('id',''): n for n in nodes}
    prod_map = {p.get('id',''): p for p in products}
    all_lines = response.split('\n')
    display_lines = []
    sys_updates = {}  # nid -> {name, items:[]}
    executed = 0

    for line in all_lines:
        s = line.strip()
        if not s.startswith("spacerpgAPI.setTrend"):
            display_lines.append(s)
            continue
        # 解析指令
        m = re.match(r"spacerpgAPI\.setTrend\s*\(\s*['\"]?(\w+)['\"]?\s*,\s*['\"]?(\w*)['\"]?\s*,\s*['\"]?(\w+)['\"]?\s*,\s*(-?\d+)\s*\)", s)
        if not m:
            display_lines.append(s)
            continue
        nid, _, prod_id, trend = m.group(1), m.group(2), m.group(3), int(m.group(4))
        node = node_map.get(nid)
        if not node:
            display_lines.append(f"⏭ 星系{nid}不存在")
            continue
        # 搜该星系所有行星找产品
        found = False
        for p in (node.get('planets') or []):
            trade = p.get('facilities', {}).get('trade', {})
            if not trade.get('active'): continue
            for item in (trade.get('products') or []):
                if (item.get('productId') or item) == prod_id:
                    item['trend'] = trend
                    prod = prod_map.get(prod_id, {})
                    icon = prod.get('icon','')
                    name = prod.get('name', prod_id)
                    tl = {1:'🔴涨',-1:'🟢跌',0:'—平'}.get(trend,'—')
                    if nid not in sys_updates:
                        sys_updates[nid] = {"system": node.get('name',nid), "items": []}
                    sys_updates[nid]["items"].append(f"{icon}{name} | {tl}")
                    executed += 1
                    found = True
                    break
            if found: break
        if found:
            display_lines.append(f"✅ {s}")
        else:
            display_lines.append(f"⏭ {node.get('name',nid)}无此产品: {s}")

    # 保存JSON
    if executed > 0:
        with open(STARMAP_JSON, 'w', encoding='utf-8') as f:
            json.dump(starmap_data, f, ensure_ascii=False, indent=2)
        news_log = os.path.join(os.path.dirname(__file__), "_news_log.json")
        log_entry = {"time": time.strftime("%H:%M:%S"), "updates": list(sys_updates.values())}
        with open(news_log, "w", encoding="utf-8") as f:
            json.dump(log_entry, f, ensure_ascii=False)
    return display_lines, executed

# ========== Trade 场景 AI 管道 ==========

def build_trade_prompt(ocr_texts):
    products = starmap_data.get("products", [])
    node = next((n for n in starmap_data.get('nodes',[]) if n['id']==current_system_id), None)
    sys_name = node.get('name','?') if node else '?'
    # 列出该星系的贸易产品
    trade_prods = []
    for p in (node.get('planets', []) or []) if node else []:
        for item in (p.get('facilities', {}).get('trade', {}).get('products', []) or []):
            pid = item.get('productId') or item
            prod = next((pr for pr in products if pr.get('id')==pid), None)
            if prod: trade_prods.append(f"{prod.get('icon','')}{prod.get('name','')}(ID:{pid}) 当前价:{item.get('priceMin',0)}/{item.get('priceMax',0)}")
    ocr_text = "\n".join(f"  行{i+1}: {t}" for i, t in enumerate(ocr_texts))
    return f"""你是 SpaceRPG4 的 AI 助手。根据 OCR 识别的贸易菜单价格更新星图产品价格。

## 当前所在星系
{sys_name} (ID: {current_system_id})
贸易产品: {', '.join(trade_prods) if trade_prods else '无'}

## OCR 价格数据
{ocr_text}

## 任务
1. 匹配 OCR 中的产品名到该星系的贸易产品
2. 从 OCR 中提取价格（纯数字）
3. 同一产品多个价格 → priceMin=最低价, priceMax=最高价；单一价格 → 两者相等
4. ⚠️ 只为星系 {sys_name}(ID:{current_system_id}) 生成指令！

## 输出格式（先简要分析，用 --- 分隔，再输出指令）
spacerpgAPI.setPrice("{current_system_id}", "产品ID", 最低价, 最高价)"""

def process_trade_response(response):
    """解析AI返回的trade价格指令，更新priceMin/priceMax"""
    nodes = starmap_data.get("nodes", [])
    products = starmap_data.get("products", [])
    node_map = {n.get('id',''): n for n in nodes}
    prod_map = {p.get('id',''): p for p in products}
    all_lines = response.split('\n')
    display_lines = []
    sys_updates = {}
    executed = 0

    for line in all_lines:
        s = line.strip()
        if not s.startswith("spacerpgAPI.setPrice"):
            display_lines.append(s)
            continue
        m = re.match(r"spacerpgAPI\.setPrice\s*\(\s*['\"]?(\w+)['\"]?\s*,\s*['\"]?(\w+)['\"]?\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", s)
        if not m:
            display_lines.append(s)
            continue
        nid, prod_id, pmin, pmax = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        node = node_map.get(nid)
        if not node: continue
        for p in (node.get('planets') or []):
            trade = p.get('facilities', {}).get('trade', {})
            if not trade.get('active'): continue
            for item in (trade.get('products') or []):
                if (item.get('productId') or item) == prod_id:
                    oldMin = item.get('priceMin', 0)
                    oldMax = item.get('priceMax', 0)
                    item['priceMin'] = pmin
                    item['priceMax'] = pmax
                    prod = prod_map.get(prod_id, {})
                    icon = prod.get('icon','')
                    name = prod.get('name', prod_id)
                    if nid not in sys_updates:
                        sys_updates[nid] = {"system": node.get('name',nid), "items": []}
                    sys_updates[nid]["items"].append(f"{icon}{name} {oldMin}/{oldMax} → {pmin}/{pmax}")
                    display_lines.append(f"✅ {name}: {oldMin}/{oldMax} → {pmin}/{pmax}")
                    executed += 1
                    break
            else: continue
            break

    if executed > 0:
        with open(STARMAP_JSON, 'w', encoding='utf-8') as f:
            json.dump(starmap_data, f, ensure_ascii=False, indent=2)
        news_log = os.path.join(os.path.dirname(__file__), "_news_log.json")
        log_entry = {"time": time.strftime("%H:%M:%S"), "updates": list(sys_updates.values())}
        with open(news_log, 'w', encoding='utf-8') as f:
            json.dump(log_entry, f, ensure_ascii=False)
    return display_lines, executed

def run_trade_ai(img):
    global sidebar_lines
    if not trade_region_data:
        sidebar_lines = ["⚠️ 未设置Trade OCR区域", "请在场景检测器中框选后按L保存"]
        return
    sidebar_lines = ["📝 正在OCR贸易价格..."]
    x1, y1, x2, y2 = trade_region_data
    roi = img[y1:y2, x1:x2]
    ocr_texts = []
    if roi.size > 0:
        h, w = roi.shape[:2]
        big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
        results = ocr.readtext(big, detail=0)
        text = " | ".join(results) if results else "(未识别)"
        ocr_texts.append(text)
        sidebar_lines.append(f"  OCR: {text}")
    sidebar_lines.append("🤖 正在AI分析...")
    prompt = build_trade_prompt(ocr_texts)
    response = call_deepseek(prompt)
    print("--- AI Trade返回 ---")
    print(response)
    display_lines, executed = process_trade_response(response)
    sidebar_lines.append("─" * 30)
    sidebar_lines.extend(display_lines)
    if executed > 0:
        sidebar_lines.append(f"✅ 已更新 {executed} 个价格")
    else:
        sidebar_lines.append("⚠️ 未执行任何更新")
    print(f"🤖 Trade分析完成，执行:{executed}条")

def ocr_text_only(img, region):
    """对指定区域做OCR，只返回纯文本（无allowlist限制）"""
    if not region: return ""
    x1, y1, x2, y2 = region
    roi = img[y1:y2, x1:x2]
    if roi.size == 0: return ""
    h, w = roi.shape[:2]
    big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    results = ocr.readtext(big, detail=0)
    return " ".join(results) if results else ""

def clean_planet_name(text):
    """只保留字母和空格，去除 OCR 误识别的符号"""
    import re
    return re.sub(r'[^a-zA-Z ]', '', text).strip()

def fuzzy_match_system(name):
    name = clean_planet_name(name)
    print(f"[状态机] 清理后星球名: '{name}'")
    """模糊匹配星球名/星系名到星图中最近的星系"""
    if not name or not starmap_data: return None
    nodes = starmap_data.get('nodes', [])
    best_score = 999
    best_id = None
    q = name.lower().strip()
    for n in nodes:
        # 匹配星系名
        score = _fuzzy(q, n.get('name','').lower())
        if score < best_score: best_score = score; best_id = n['id']
        # 匹配行星名
        for p in (n.get('planets') or []):
            score = _fuzzy(q, p.get('name','').lower())
            if score < best_score: best_score = score; best_id = n['id']
    return best_id if best_score < 100 else None

def _fuzzy(q, t):
    if not q or not t: return 999
    if q == t: return -3
    if t.startswith(q): return -2
    if q in t: return -1
    return 999

def call_deepseek(prompt):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    body = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000, "temperature": 0.3}
    try:
        r = requests.post(DEEPSEEK_URL, headers=headers, json=body, timeout=30)
        if r.status_code == 200: return r.json()["choices"][0]["message"]["content"]
        return f"API错误({r.status_code})"
    except Exception as e:
        return f"请求失败: {e}"

def run_bar_ai(img):
    """酒吧场景：OCR新闻区域 → AI分析 → 验证"""
    global sidebar_lines
    if not ocr_regions_data:
        sidebar_lines = ["⚠️ 未找到新闻OCR区域", "请先在OCR工具中保存区域(L键)"]
        return
    sidebar_lines = ["📝 正在OCR新闻..."]
    ocr_texts = []
    for i, (x1, y1, x2, y2) in enumerate(ocr_regions_data):
        roi = img[y1:y2, x1:x2]
        if roi.size == 0: continue
        h, w = roi.shape[:2]
        big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
        results = ocr.readtext(big, detail=0, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .,:;-()")
        text = " | ".join(results) if results else "(未识别)"
        ocr_texts.append(text)
        sidebar_lines.append(f"  框{i+1}: {text}")

    sidebar_lines.append("")
    sidebar_lines.append("🤖 正在AI分析...")
    prompt = build_news_prompt(ocr_texts)
    response = call_deepseek(prompt)
    sidebar_lines.append("─" * 30)
    # 打印AI原始返回到终端
    print("--- AI原始返回 ---")
    print(response)
    print("--- 结束 ---")
    display_lines, executed = process_ai_response(response)
    sidebar_lines.extend(display_lines)
    if executed > 0:
        sidebar_lines.append("")
        sidebar_lines.append(f"✅ 已执行 {executed} 条更新")
    else:
        sidebar_lines.append("⚠️ 未执行任何更新")
    sidebar_lines.append("─" * 30)
    print(f"🤖 分析完成，执行:{executed}条")

def mouse_callback(event, x, y, flags, param):
    global watch_region, drawing, drag_start
    if x >= disp_w: return  # 侧边栏
    rx, ry = x / disp_scale, y / disp_scale
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True
        drag_start = (rx, ry)
    elif event == cv2.EVENT_MOUSEMOVE and drawing:
        x1, y1 = drag_start
        watch_region = (int(min(x1,rx)), int(min(y1,ry)), int(max(x1,rx)), int(max(y1,ry)))
    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        if watch_region and abs(watch_region[2]-watch_region[0]) > 10:
            print(f"📐 临时框选: {watch_region} (按1-5保存到对应区域)")

def detect_scene(img, region):
    """OCR 识别区域内的文字，检测场景"""
    if not region: return "?", ""
    x1, y1, x2, y2 = region
    roi = img[y1:y2, x1:x2]
    if roi.size == 0: return "?", ""
    h, w = roi.shape[:2]
    big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    results = ocr.readtext(big, detail=0,
        allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ")
    text = " ".join(results) if results else ""
    # 检测关键词
    text_lower = text.lower()
    if "bar" in text_lower: return "Bar", text
    if "trade" in text_lower: return "Trade", text
    return "?", text

def draw_ui():
    global disp_scale, disp_w, disp_h
    h, w = img_raw.shape[:2]
    disp_scale = min(1.0, 1200 / w)
    disp_w = int(w * disp_scale)
    disp_h = int(h * disp_scale)
    disp = cv2.resize(img_raw, (disp_w, disp_h))

    # 绘制所有区域
    regions_to_draw = [
        (refuel_region, (0,200,255), "REFUEL"),
        (planet_region, (255,200,0), "Planet"),
        (watch_region, (0,255,0) if current_scene=="?" else (255,200,0) if current_scene=="Bar" else (0,200,255), "Bar/Trade"),
        (trade_region_data, (200,100,255), "Trade"),
    ]
    for reg, color, label in regions_to_draw:
        if not reg: continue
        x1, y1, x2, y2 = reg
        sx1, sy1 = int(x1*disp_scale), int(y1*disp_scale)
        sx2, sy2 = int(x2*disp_scale), int(y2*disp_scale)
        cv2.rectangle(disp, (sx1,sy1), (sx2,sy2), color, 2)
        pil_text(disp, label, (sx1+2, sy1-16), 12, color)

    # 状态栏
    cv2.rectangle(disp, (0,0), (disp_w,26), (0,0,0), -1)
    status = f"R=截图  M=框选区域  Q=退出  场景:{current_scene}"
    cv2.putText(disp, status, (5,18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200,200,200), 1)

    # 侧边栏
    total_w = disp_w + SIDEBAR_W
    total_h = max(disp_h, 400)
    canvas = np.zeros((total_h, total_w, 3), dtype=np.uint8)
    canvas[:disp_h, :disp_w] = disp
    cv2.rectangle(canvas, (disp_w, 0), (total_w, total_h), (20, 20, 30), -1)

    # 场景指示
    pil_text(canvas, "场景检测", (disp_w+10, 6), 16, (0, 200, 255))
    cv2.line(canvas, (disp_w, 28), (total_w, 28), (60, 60, 80), 1)
    y = 38

    scene_color = (100,255,100) if current_scene == "Bar" else (100,200,255) if current_scene == "Trade" else (120,120,140)
    scene_label = {"Bar":"🍺 进入酒吧", "Trade":"💰 进入贸易中心", "?":"🔍 检测中..."}[current_scene]
    pil_text(canvas, scene_label, (disp_w+10, y), 20, scene_color)
    y += 40

    pil_text(canvas, "最近 OCR:", (disp_w+10, y), 12, (150,150,160)); y += 18
    if last_ocr_text:
        for line in [last_ocr_text[i:i+25] for i in range(0, min(len(last_ocr_text),150), 25)]:
            pil_text(canvas, line, (disp_w+14, y), 11, (180,180,190))
            y += 15
    else:
        pil_text(canvas, "(等待首次识别)", (disp_w+14, y), 11, (100,100,110))
        y += 15
    y += 10

    # AI 结果
    if sidebar_lines:
        cv2.line(canvas, (disp_w, y), (total_w, y), (60,60,80), 1); y += 4
        pil_text(canvas, "AI 分析结果", (disp_w+10, y), 12, (0,200,150)); y += 18
        max_lines = (total_h - y - 30) // 14
        start = max(0, len(sidebar_lines) - max_lines)
        for i in range(start, len(sidebar_lines)):
            ln = sidebar_lines[i]
            c = (180,220,180)
            if ln.startswith("spacerpgAPI"): c = (100,255,150)
            elif ln.startswith("⚠"): c = (200,180,100)
            elif ln.startswith("⏭"): c = (200,150,100)
            pil_text(canvas, ln, (disp_w+10, y), 10, c)
            y += 14
            if y > total_h - 15: break
    else:
        pil_text(canvas, "操作提示", (disp_w+10, y), 12, (150,150,160)); y += 18
        pil_text(canvas, "鼠标拖拽 = 框选监测区域", (disp_w+14, y), 11, (120,120,130)); y += 15
        # 区域设置状态表
        pil_text(canvas, "📐 框选后按数字键保存:", (disp_w+10, y), 12, (255,200,100)); y += 15
        for key, name, region in [
            ("1", "REFUEL检测区", refuel_region),
            ("2", "星球名OCR区", planet_region),
            ("3", "Bar/Trade检测", watch_region),
            ("4", "新闻OCR(Bar)", ocr_regions_data),
            ("5", "Trade价格OCR", trade_region_data),
        ]:
            has = (region and (isinstance(region, list) and len(region)>0)) if key in ('4',) else bool(region)
            status = "✅" if has else "⬜"
            c = (100,220,100) if has else (140,140,100)
            pil_text(canvas, f"{status} 按{key} {name}", (disp_w+10, y), 11, c)
            y += 14
        y += 4
        pil_text(canvas, f"状态: {'🛸停靠' if docked else '🔍搜索中'} 星系:{current_system_id or '?'}", (disp_w+10, y), 11, (120,200,120))

    return canvas

# ========== 微型 HTTP 服务（网页轮询用） ==========
class NewsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/starmap.json':
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
            with open(STARMAP_JSON,'rb') as f: self.wfile.write(f.read())
        elif self.path == '/news.json':
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Access-Control-Allow-Origin','*'); self.end_headers()
            news_log = os.path.join(os.path.dirname(__file__), "_news_log.json")
            if os.path.exists(news_log):
                with open(news_log,'rb') as f: self.wfile.write(f.read())
            else:
                self.wfile.write(b'{}')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, format, *args): pass  # 静默

def start_http_server():
    try:
        server = HTTPServer(('127.0.0.1', HTTP_PORT), NewsHandler)
        print(f"🌐 HTTP服务: http://127.0.0.1:{HTTP_PORT}")
        server.serve_forever()
    except:
        print("⚠️ HTTP服务启动失败（端口可能被占用）")

def main():
    global img_raw, watch_region, current_scene, last_ocr_text, last_scan_time
    global bar_triggered, trade_triggered, docked, current_system_id
    global refuel_region, planet_region, trade_region_data, sidebar_lines

    # 启动微型HTTP服务
    threading.Thread(target=start_http_server, daemon=True).start()

    print("=" * 50)
    print("SpaceRPG4 场景检测器")
    print("=" * 50)
    if watch_region:
        print(f"📂 已加载保存区域: {watch_region}")
    else:
        print("🖱️  请用鼠标拖拽框选一个持续监测区域")
    print("=" * 50)

    img_raw = capture_screen()
    if img_raw is None: print("❌ 截图失败"); sys.exit(1)
    print(f"✅ 截图成功 ({img_raw.shape[1]}x{img_raw.shape[0]})")

    cv2.namedWindow("Scene Detector", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Scene Detector", 1200 + SIDEBAR_W, 780)
    cv2.setMouseCallback("Scene Detector", mouse_callback)
    last_scan_time = time.time()

    while True:
        now = time.time()

        # 每秒截图+OCR
        if now - last_scan_time >= SCAN_INTERVAL:
            last_scan_time = now
            new_img = capture_screen()
            if new_img is not None:
                img_raw = new_img
            # === 状态机 ===
            # Step 1: 检测 REFUEL（仅用于触发停靠，不停靠后不因REFUEL消失而重置）
            if refuel_region:
                refuel_text = ocr_text_only(img_raw, refuel_region)
                refuel_seen = "refuel" in refuel_text.lower()
                if refuel_seen and not docked:
                    docked = True
                    print(f"[状态机] 🛸 停靠! REFUEL OCR: '{refuel_text[:60]}'")
                    sidebar_lines = ["🛸 检测到停靠(REFUEL)"]
                    # Step 2: OCR 星球名 → 匹配星系
                    if planet_region:
                        x1,y1,x2,y2 = planet_region
                        roi = img_raw[y1:y2, x1:x2]
                        if roi.size > 0:
                            h,w = roi.shape[:2]
                            big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
                            results = ocr.readtext(big, detail=0, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ")
                            planet_name = " ".join(results).strip() if results else ""
                        else:
                            planet_name = ""
                        print(f"[状态机] 星球名 OCR: '{planet_name}'")
                        sidebar_lines.append(f"  星球名: {planet_name}")
                        nid = fuzzy_match_system(planet_name)
                        if nid:
                            current_system_id = nid
                            node = next((n for n in starmap_data.get('nodes',[]) if n['id']==nid), None)
                            print(f"[状态机] 匹配星系: {node.get('name',nid) if node else nid}")
                            sidebar_lines.append(f"  匹配星系: {node.get('name',nid) if node else nid}")
                        else:
                            print(f"[状态机] ⚠️ 未匹配到星系")
                            sidebar_lines.append("  ⚠️ 未匹配到星系")
                # 如果出现了新的REFUEL（另一个星球），重新OCR
                elif refuel_seen and docked:
                    if planet_region:
                        x1,y1,x2,y2 = planet_region
                        roi = img_raw[y1:y2, x1:x2]
                        if roi.size > 0:
                            h,w = roi.shape[:2]
                            big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
                            results = ocr.readtext(big, detail=0, allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz ")
                            new_name = " ".join(results).strip() if results else ""
                        else:
                            new_name = ""
                        if new_name:
                            nid = fuzzy_match_system(new_name)
                            if nid and nid != current_system_id:
                                print(f"[状态机] 🔄 切换星球: {new_name} → {next((n for n in starmap_data.get('nodes',[]) if n['id']==nid), {}).get('name',nid)}")
                                current_system_id = nid
                                bar_triggered = False
                                trade_triggered = False
                                sidebar_lines = [f"🔄 切换星球: {new_name}"]

            # Step 3: 检测 Bar/Trade（在停靠状态下持续检测）
            if docked and current_system_id and watch_region:
                current_scene, last_ocr_text = detect_scene(img_raw, watch_region)
                # 每秒打印一次当前状态
                if int(time.time()) != int(time.time()-SCAN_INTERVAL):
                    pass  # 不刷屏
                if current_scene != "?":
                    print(f"[状态机] 🎯 场景='{current_scene}' | bar_ok={not bar_triggered} trade_ok={not trade_triggered} | OCR='{last_ocr_text[:80]}'")
                if current_scene == "Bar" and not bar_triggered:
                    print(f"[状态机] 🍺 触发 Bar AI")
                    bar_triggered = True
                    run_bar_ai(img_raw)
                elif current_scene == "Trade" and not trade_triggered:
                    print(f"[状态机] 💰 触发 Trade AI")
                    trade_triggered = True
                    run_trade_ai(img_raw)

        canvas = draw_ui()
        cv2.imshow("Scene Detector", canvas)

        key = cv2.waitKey(50) & 0xFF
        if key == ord('q') or key == 27:
            break
        elif key == ord('r'):
            img_raw = capture_screen()
            if img_raw is not None:
                print("📸 手动截图")
        elif key == ord('1'):
            refuel_region = list(watch_region) if watch_region else None
            if refuel_region: save_json_file(REFUEL_REGION_JSON, refuel_region); print(f"REFUEL 💾 区域已保存: {refuel_region}")
            sidebar_lines = [f"{'✅' if refuel_region else '⬜'} 1.REFUEL检测区"]
        elif key == ord('2'):
            planet_region = list(watch_region) if watch_region else None
            if planet_region: save_json_file(PLANET_REGION_JSON, planet_region); print(f"星球名 💾 区域已保存: {planet_region}")
            sidebar_lines = [f"{'✅' if planet_region else '⬜'} 2.星球名OCR区"]
        elif key == ord('3'):
            if watch_region: save_json_file(REGION_JSON, list(watch_region)); print(f"Bar/Trade 💾 区域已保存: {watch_region}")
            sidebar_lines = [f"{'✅' if watch_region else '⬜'} 3.Bar/Trade检测区"]
        elif key == ord('4'):
            if watch_region: ocr_regions_data = [list(watch_region)]; save_json_file(OCR_REGIONS_JSON, ocr_regions_data); print(f"新闻OCR 💾 区域已保存: {watch_region}")
            sidebar_lines = [f"{'✅' if watch_region else '⬜'} 4.新闻OCR区(Bar)"]
        elif key == ord('5'):
            trade_region_data = list(watch_region) if watch_region else None
            if trade_region_data: save_json_file(TRADE_REGION_JSON, trade_region_data); print(f"Trade价格 💾 区域已保存: {trade_region_data}")
            sidebar_lines = [f"{'✅' if trade_region_data else '⬜'} 5.Trade价格OCR区"]

    cv2.destroyAllWindows()
    if os.path.exists(TEMP_SCREENSHOT):
        os.remove(TEMP_SCREENSHOT)
    print("👋 已退出")

if __name__ == "__main__":
    main()
