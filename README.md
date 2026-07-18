# 🚀 SpaceRPG4 Celestial Atlas

> 一款为 SpaceRPG4 打造的交互式星图工具 —— 包含 265 个星系、BFS 寻路、Voronoi 领域地图、AI 对话助手和 OCR 场景检测。

[![GitHub](https://img.shields.io/badge/GitHub-UNICORN--2887%2FSpaceRPG4--CelestialAtlas-blue)](https://github.com/UNICORN-2887/SpaceRPG4-CelestialAtlas)

---

## ✨ 功能总览

| 模块 | 说明 |
|------|------|
| 🗺️ **交互式星图** | 265 个星系，6 种派系/颜色，拓扑通道网络 |
| ✏️ **编辑器模式** | 添加星系/行星，配置设施（酒吧/船坞/贸易中心等），管理 NPC、舰船、产品 |
| 🧭 **地图模式** | BFS 最短路径、无补给最短路径、途径点、空间站 |
| 🎨 **领域地图** | 基于 Delaunay 三角剖分的 Voronoi 图，按派系填色 |
| 🤖 **Arkitect AI** | 基于 DeepSeek 的智能对话助手，支持路径查询、NPC 查找、产品搜索、贸易建议 |
| 📰 **新闻 OCR** | EasyOCR + MuMu 模拟器截图 → AI 识别新闻 → 自动设置价格趋势 |
| 💰 **贸易系统** | 最低/最高价、涨跌趋势、AI 辅助价格更新 |
| ⚙️ **知识库配置** | 自定义 AI 知识库、API 密钥、回答规则 |

---

## 🚀 快速开始

### 1. 星图工具（零依赖）

直接双击打开 `spacerpg4_map.html` 即可使用完整星图功能。

- **编辑器模式**：双击画布添加星系 → 拖拽移动 → Shift+点击建立通道
- **地图模式**：单击设起点 → 再单击设终点 → 绿色显示最短路径
- **领域地图**：点击 🗺️ 领域按钮查看派系势力范围

### 2. AI 对话助手

1. 打开 `kb_config.html` → 填入你的 DeepSeek API Key → 保存
2. 刷新 `spacerpg4_map.html` → 右侧 **"遇事不决？问问Arkitect"** 按钮
3. 点击打开对话面板，尝试提问：
   - "从 Sol 到 Dima 怎么走？"
   - "Ryan 在哪里？"
   - "哪里可以买到最便宜的 Metal？"
   - "Pethylon 有哪些舰船？"

### 3. OCR 场景检测器（需要 Python）

```bash
# 安装依赖
pip install -r requirements.txt

# 启动场景检测器（需先启动 MuMu 模拟器）
python ocr_scene_detector.py
```

按 `1-5` 键标定识别区域，进入游戏后自动检测 Bar/Trade 场景并触发 AI 分析。

---

## 📂 文件说明

```
spacerpg4_map.html         # 主星图工具（双击打开）
kb_config.html             # 知识库 & API 配置页面
ocr_tool.py                # OCR 框选工具（截图+框选+AI分析）
ocr_scene_detector.py      # 场景检测器（REFUEL→Bar/Trade自动识别）
requirements.txt           # Python 依赖
README.md                  # 本文件
```

---

## 🎮 使用技巧

| 场景 | 操作 |
|------|------|
| 查看星系详情 | 地图模式 → 切换到"查看"子模式 → 单击星系 |
| 规划省油路径 | 导航模式 → 切换到"无补给最短" → 输入 FTL |
| 搜索 NPC | 🔎 搜索 → 👤 NPC 标签 → 输入名字 |
| 找最便宜商品 | 🔎 搜索 → 📦 资源标签 → 选"最近距离"+排序 |
| 布置空间站 | 地图模式 → 单击灰色星域 → 左侧栏勾选 |
| 测试贸易价格 | 编辑器模式 → 🎲 随机生成 |

---

## 🔍 管理员审核工具

当用户通过配置页提交知识库后，管理员可以用 `admin_panel.py` 审核批准：

```bash
python admin_panel.py
```

浏览器自动打开管理面板，功能：

| 功能 | 说明 |
|------|------|
| 📧 自动扫描邮箱 | IMAP 连接 QQ 邮箱，拉取"新的知识库提交"邮件 |
| 🎚️ 阈值滑块 | 拖动调整相似度过滤阈值（30%-95%），实时查看原始/过滤计数 |
| 🤖 AI 去重 | 自动调用 DeepSeek 合并语义重复的条目 |
| ✅ 勾选批准 | 浏览器中勾选 → 一键写入 `kb_config.html` |
| 🚀 批准并部署 | 自动复制到博客仓库 + git push → Cloudflare 部署 |

首次使用需在项目目录放置 `_api_config.json`（从配置页导出）以启用 AI 去重。

---

## 🔧 技术栈

- **前端**：Vanilla HTML/CSS/JS + SVG 渲染
- **AI**：DeepSeek Chat API（函数调用 + 知识库）
- **OCR**：EasyOCR（中文 + 英文）
- **模拟器**：MuMu Player 12 + ADB 截图
- **算法**：BFS 寻路、Delaunay 三角剖分、Voronoi 图

---

## 📝 License

MIT
