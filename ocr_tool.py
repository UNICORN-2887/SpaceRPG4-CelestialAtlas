"""
SpaceRPG4 OCR 框选工具 + AI 分析
- 连接 MuMu 模拟器截图
- 鼠标拖拽框选多个绿色区域
- EasyOCR 识别（仅字母）
- DeepSeek AI 分析 → 生成物价波动指令
"""

# 自动安装依赖
import subprocess, os, sys
def _ensure(pkg, imp):
    try: __import__(imp); return
    except: subprocess.check_call([sys.executable, '-m', 'pip', 'install', pkg, '-q'])
_ensure('opencv-python', 'cv2')
_ensure('numpy', 'numpy')
_ensure('easyocr', 'easyocr')
_ensure('requests', 'requests')
_ensure('Pillow', 'PIL')

import json, cv2, numpy as np, easyocr, requests, re
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# ========== 配置 ==========
ADB_EXE = r"D:\工程\MuMu Player 12\nx_main\adb.exe"
ADB_DEVICE = "emulator-5554"
TEMP_SCREENSHOT = os.path.join(os.path.dirname(__file__), "_ocr_temp_screenshot.png")
STARMAP_JSON = os.path.join(os.path.dirname(__file__), "spacerpg4_map_data.json")
REGIONS_JSON = os.path.join(os.path.dirname(__file__), "_ocr_regions.json")

# 从配置文件读取API密钥
def _load_api_key():
    config_path = os.path.join(os.path.dirname(__file__), "_api_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f).get('apiKey', '')
        except: pass
    return ''

DEEPSEEK_API_KEY = _load_api_key()
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

SIDEBAR_W = 420
FONT = cv2.FONT_HERSHEY_SIMPLEX

print("🔤 加载 EasyOCR (ch_sim+en)...", end=" ", flush=True)
ocr = easyocr.Reader(["ch_sim", "en"], gpu=True)
print("OK")

# 中文字体
_FONT_PATH = None
for p in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simsun.ttc"]:
    if os.path.exists(p): _FONT_PATH = p; break
if not _FONT_PATH: print("⚠️ 未找到中文字体"); _FONT_PATH = None

def pil_text(img, text, xy, size, color):
    if not _FONT_PATH: return
    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    font = ImageFont.truetype(_FONT_PATH, size)
    draw.text(xy, text, font=font, fill=color)
    rgb = np.array(pil_img)
    img[:] = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

# ========== 全局状态 ==========
regions = []
drawing = False
start_x, start_y = -1, -1
current_region = None
img_raw = None
sidebar_lines = []
ai_pending = False
last_ocr_texts = []
disp_scale = 1.0
disp_w, disp_h = 0, 0

def capture_screen():
    cmd = f'"{ADB_EXE}" -s {ADB_DEVICE} exec-out screencap -p > "{TEMP_SCREENSHOT}"'
    subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return cv2.imread(TEMP_SCREENSHOT)

def ocr_region(img, x1, y1, x2, y2):
    x1, x2 = sorted([x1, x2])
    y1, y2 = sorted([y1, y2])
    if x2 - x1 < 5 or y2 - y1 < 5: return "(区域太小)"
    roi = img[y1:y2, x1:x2]
    if roi.size == 0: return "(空)"
    h, w = roi.shape[:2]
    big = cv2.resize(roi, (w*2, h*2), interpolation=cv2.INTER_CUBIC)
    results = ocr.readtext(big, detail=0,
        allowlist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .,:;-()")
    return " | ".join(results) if results else "(未识别到文字)"

def load_starmap():
    if os.path.exists(STARMAP_JSON):
        with open(STARMAP_JSON, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def build_context(data, ocr_texts):
    nodes = data.get("nodes", [])
    products = data.get("products", [])
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
                if prod: trade_prods.append(f"{prod.get('icon','')}{prod.get('name','')}")
        info = f"  {name}"
        if fac: info += f" [{fac}]"
        if trade_prods: info += f" 贸易: {', '.join(trade_prods)}"
        system_info.append(info)
    ocr_text = "\n".join(f"  框{i+1}: {t}" for i, t in enumerate(ocr_texts))
    return f"""你是 SpaceRPG4 的 AI 助手，根据 OCR 新闻调整星图贸易产品价格波动。

## OCR 新闻
{ocr_text}

## 星图数据
{chr(10).join(system_info)}

## 任务
1. 模糊匹配 OCR 中的星系名到星图中最相似的星系
2. 判断产品价格涨(🔴 trend=1)或跌(🟢 trend=-1)
3. 只为星系中实际存在的产品生成指令

## 输出格式（先分析，用 --- 分隔，再输出指令）
spacerpgAPI.setTrend("节点ID", "行星ID", "产品ID", trend)"""

def call_deepseek(prompt):
    if not DEEPSEEK_API_KEY: return "⚠️ 未配置API密钥"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
    body = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": 2000, "temperature": 0.3}
    try:
        r = requests.post(DEEPSEEK_URL, headers=headers, json=body, timeout=30)
        if r.status_code == 200: return r.json()["choices"][0]["message"]["content"]
        return f"API错误({r.status_code}): {r.text[:200]}"
    except Exception as e: return f"请求失败: {str(e)}"

def save_regions():
    with open(REGIONS_JSON, 'w') as f: json.dump(regions, f)
    print(f"💾 已保存 {len(regions)} 个区域")

def load_regions():
    if os.path.exists(REGIONS_JSON):
        with open(REGIONS_JSON, 'r') as f: return json.load(f)
    return []

def draw_ui(img):
    global disp_scale, disp_w, disp_h
    h, w = img.shape[:2]
    disp_scale = min(1.0, 1200 / w)
    disp_w = int(w * disp_scale)
    disp_h = int(h * disp_scale)
    disp = cv2.resize(img, (disp_w, disp_h))
    for i, (x1, y1, x2, y2) in enumerate(regions):
        sx1, sy1 = int(x1*disp_scale), int(y1*disp_scale)
        sx2, sy2 = int(x2*disp_scale), int(y2*disp_scale)
        cv2.rectangle(disp, (sx1, sy1), (sx2, sy2), (0, 255, 0), 2)
        pil_text(disp, f"#{i+1}", (sx1+3, sy1+2), 14, (0,255,0))
    if current_region:
        x1, y1, x2, y2 = current_region
        sx1, sy1 = int(x1*disp_scale), int(y1*disp_scale)
        sx2, sy2 = int(x2*disp_scale), int(y2*disp_scale)
        cv2.rectangle(disp, (sx1, sy1), (sx2, sy2), (0, 255, 0), 2)
    cv2.rectangle(disp, (0, 0), (disp_w, 28), (0, 0, 0), -1)
    info = f"R=截图 L=保存区域 C=清除 Enter=OCR+AI T=仅OCR Q=退出  区域:{len(regions)}"
    cv2.putText(disp, info, (5, 19), FONT, 0.4, (200, 200, 200), 1)
    total_w = disp_w + SIDEBAR_W
    total_h = max(disp_h, 600)
    canvas = np.zeros((total_h, total_w, 3), dtype=np.uint8)
    canvas[:disp_h, :disp_w] = disp
    cv2.rectangle(canvas, (disp_w, 0), (total_w, total_h), (20, 20, 30), -1)
    pil_text(canvas, "AI 分析结果", (disp_w+10, 6), 16, (0,200,255))
    cv2.line(canvas, (disp_w, 28), (total_w, 28), (60, 60, 80), 1)
    y = 38
    if ai_pending:
        pil_text(canvas, "等待 AI 返回...", (disp_w+10, y), 13, (200,200,100))
    elif not sidebar_lines:
        if os.path.exists(STARMAP_JSON):
            pil_text(canvas, "星图数据: 已加载 ✓", (disp_w+10, y), 13, (100,200,100)); y += 20
        else:
            pil_text(canvas, "星图数据: 未加载", (disp_w+10, y), 13, (200,100,100)); y += 20
        pil_text(canvas, "框选区域后按 Enter", (disp_w+10, y), 12, (120,120,140)); y += 18
        pil_text(canvas, "自动 OCR + AI 分析", (disp_w+10, y), 12, (120,120,140))
    else:
        max_lines = (total_h - 80) // 16
        start = max(0, len(sidebar_lines) - max_lines)
        for i in range(start, len(sidebar_lines)):
            line = sidebar_lines[i]
            color = (200,220,200)
            if line.startswith("spacerpgAPI"): color = (100,255,150)
            if line.startswith("⚠"): color = (200,180,100)
            pil_text(canvas, line, (disp_w+8, y), 12, color)
            y += 16
            if y > total_h - 10: break
    pil_text(canvas, "L=保存区域配置", (disp_w+10, total_h-22), 11, (80,80,100))
    return canvas

def mouse_callback(event, x, y, flags, param):
    global drawing, start_x, start_y, current_region, regions
    if x >= disp_w: return
    rx, ry = x / disp_scale, y / disp_scale
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing = True; start_x, start_y = rx, ry; current_region = (rx, ry, rx, ry)
    elif event == cv2.EVENT_MOUSEMOVE:
        if drawing: current_region = (start_x, start_y, rx, ry)
    elif event == cv2.EVENT_LBUTTONUP:
        drawing = False
        if current_region:
            x1, y1, x2, y2 = current_region
            if abs(x2-x1) > 5 and abs(y2-y1) > 5:
                regions.append((int(min(x1,x2)), int(min(y1,y2)), int(max(x1,x2)), int(max(y1,y2))))
            current_region = None

def main():
    global img_raw, regions, sidebar_lines, ai_pending, last_ocr_texts
    print("=" * 50)
    print("SpaceRPG4 OCR + AI 分析工具")
    print("=" * 50)
    print("操作: 鼠标框选 | Enter=OCR+AI | T=仅OCR | L=保存区域 | R=截图 | C=清除 | Q=退出")
    print("=" * 50)
    data = load_starmap()
    if data: print(f"📂 星图: {len(data.get('nodes',[]))}星系")
    else: print("⚠️ 未找到星图JSON")
    print("📸 连接 MuMu...")
    img_raw = capture_screen()
    if img_raw is None: print("❌ 无法获取截图"); sys.exit(1)
    print(f"✅ 截图成功 ({img_raw.shape[1]}x{img_raw.shape[0]})")
    saved = load_regions()
    if saved: regions.extend(saved); sidebar_lines = [f"📂 已加载 {len(saved)} 个区域"]
    cv2.namedWindow("SpaceRPG4 OCR + AI", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("SpaceRPG4 OCR + AI", 1200 + SIDEBAR_W, 780)
    cv2.setMouseCallback("SpaceRPG4 OCR + AI", mouse_callback)
    while True:
        canvas = draw_ui(img_raw)
        cv2.imshow("SpaceRPG4 OCR + AI", canvas)
        key = cv2.waitKey(50) & 0xFF
        if key == ord('q') or key == 27: break
        elif key == ord('r'):
            new_img = capture_screen()
            if new_img is not None: img_raw = new_img; regions.clear(); sidebar_lines = ["📸 截图已更新"]
        elif key == ord('c'): regions.clear(); sidebar_lines = ["🗑 框选已清除"]
        elif key == ord('l'): save_regions(); sidebar_lines = [f"💾 已保存 {len(regions)} 个区域"]
        elif key == 13:
            if not regions: sidebar_lines = ["⚠️ 请先框选至少一个区域"]
            else:
                last_ocr_texts = []; sidebar_lines = ["📝 OCR 结果:"]
                for i, (x1, y1, x2, y2) in enumerate(regions):
                    text = ocr_region(img_raw, x1, y1, x2, y2)
                    last_ocr_texts.append(text); sidebar_lines.append(f"  框{i+1}: {text}")
                if data:
                    ai_pending = True; sidebar_lines.append(""); sidebar_lines.append("🤖 正在分析...")
                    cv2.imshow("SpaceRPG4 OCR + AI", draw_ui(img_raw)); cv2.waitKey(1)
                    prompt = build_context(data, last_ocr_texts); response = call_deepseek(prompt)
                    sidebar_lines.append("─" * 30)
                    for line in response.split('\n'): sidebar_lines.append(line.rstrip())
                    sidebar_lines.append("─" * 30); sidebar_lines.append("⚠ 以上为AI建议，未实际执行")
                    ai_pending = False
        elif key == ord('t'):
            if not regions: sidebar_lines = ["⚠️ 请先框选至少一个区域"]
            else: sidebar_lines = ["📝 OCR 结果:"] + [f"  框{i+1}: {ocr_region(img_raw, *r)}" for i, r in enumerate(regions)]
        elif key == ord('s'):
            cv2.imwrite(os.path.join(os.path.dirname(__file__), "_ocr_screenshot.png"), draw_ui(img_raw))
            print("💾 已保存")
    cv2.destroyAllWindows()
    if os.path.exists(TEMP_SCREENSHOT): os.remove(TEMP_SCREENSHOT)
    print("👋 已退出")

if __name__ == "__main__":
    main()
