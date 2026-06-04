# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

「寻迹故宫」(Tracing the Forbidden City) — 基于故宫官方数字全景 (pano.dpm.org.cn) 的 GeoGuessr 风格 Web 定位游戏。用户观察 360° 全景，在离线故宫平面图上点击猜测位置，按误差计分，搭配知识问答。清华大学通识课「故宫学」课程项目。

## 常用命令

```bash
# 启动开发服务器（Windows）
start_server.bat

# 启动开发服务器（macOS/Linux）
./start_server.sh

# 直接启动
python backend/server.py

# 编译 LaTeX 报告
xelatex -interaction=nonstopmode -file-error-line report.tex

# Electron 开发运行（需要先 npm install）
npm start

# PyInstaller 打包后端
pyinstaller --onefile --name server backend/server.py
```

启动后访问：
- 游戏：`http://127.0.0.1:8000/`
- 报告演示模式：`http://127.0.0.1:8000/?report=1`
- 锚点采集模式：`http://127.0.0.1:8000/?debug=anchors`

## 技术架构

```
浏览器 ──HTTP──▶ Python ThreadingHTTPServer (backend/server.py, 端口 8000)
                    │
                    ├── 静态文件服务（frontend/ + data/）
                    ├── REST API（/api/scenes, /api/config, /api/resources/*）
                    └── 资源管理（resource_manager.py：下载/预取/清理/统计）
```

**核心依赖零外部框架**：后端使用 Python 标准库 `http.server` + `ThreadingHTTPServer`，无需 pip install。前端为 Vanilla JS（非 React），通过 `<script>` 标签直接加载 Leaflet 和 krpano。

## 目录与关键文件

```
backend/
├── server.py              # HTTP 服务器 + 全部 API 路由（~58KB，约1400行）
└── resource_manager.py    # 后台下载队列、预取策略、占用统计、清理逻辑
frontend/
├── index.html             # 唯一页面，含所有 UI 面板
├── app.js                 # 全部前端逻辑（~1320行）：krpano/Leaflet 联动、计分、问答
└── styles.css             # 全局样式
data/
├── raw/
│   ├── panoramas/{pid}/tiles/{stub}/{face}/{level}/{row}/{col}.jpg  # 立方体全景瓦片
│   ├── leaflet/tiles/{z}/tile_{x}_{y}.png     # 宫图底图瓦片
│   ├── vendor/krpano.js, leaflet.js           # 前端运行时（本地化）
│   ├── project_tour.xml                       # krpano tour 定义（原始全层级版）
│   └── map_transform.json                     # 全局 + per-panorama 仿射变换参数
├── processed/
│   ├── scene_catalog.demo_anchors.local.json  # 可玩场景清单（主数据源）
│   ├── map_anchor_points.captured.json        # 锚点真值（captured + manual9）
│   ├── scene_knowledge.json                   # 建筑知识问答
│   ├── local_tiles_inventory.json             # 本地瓦片库存清单
│   └── played_scenes.json                     # 已玩记录
scripts/                  # 离线工具脚本（数据采集/校准/审计）
├── phase0_fetch_resources.py   # 批量下载全景资源
├── calibrate_map_transform.py  # 拟合仿射变换（全局 + per-pano）
├── audit_local_tiles.py        # 审计本地瓦片完整性
├── fetch_leaflet_map_resources.py  # 下载宫图瓦片
└── ...
electron/
├── main.js                # Electron 主进程：启动 Python 后端 + 创建窗口
└── preload.js             # contextBridge 暴露 electronAPI
docs/                      # 阶段文档（phase0_1~4 开发记录）
report.tex                 # 课程报告 LaTeX 源文件
anchor.json                # 锚点数据副本
需求.md                    # 原始需求文档
RULES.md                   # 开发规则（资源层级/路径映射/性能/调试/变更回归）
```

## API 路由一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查 + 场景/库存计数 |
| GET | `/api/config` | 系统配置（bounds, default_scene, 锚点等） |
| GET | `/api/scenes` | 全部场景列表 |
| GET | `/api/scenes/{name}` | 单场景详情（含 viewer 配置、瓦片清单） |
| GET | `/api/scenes/random` | 随机场景 |
| GET | `/api/knowledge` | 知识题库 |
| GET | `/api/resources/status` | 资源占用统计（MB、已缓存/未玩/已玩数） |
| GET | `/api/resources/config` | 资源管理配置（下载模式等） |
| GET | `/api/resources/prefetch` | 触发预下载 5 景 |
| GET | `/api/resources/prune?max_mb=N` | 按容量清理 |
| GET | `/api/resources/refresh` | 刷新资源统计 |
| GET | `/api/debug/scenes` | 锚点采集模式场景列表 |
| GET | `/api/debug/mapping` | 路径映射调试信息 |
| POST | `/api/resources/played` | 标记场景已玩 |
| POST | `/api/resources/config` | 更新资源管理配置 |
| POST | `/api/debug/anchor` | 保存锚点坐标 |

## 坐标系统

存在三层坐标概念，优先级如下（`app.js:getSceneTruthCoord`）：

1. **per-pano affine 真值**（`click_pixel_xy` → 仿射逆变换 → user 坐标）— 最精确
2. **锚点 `user_x/user_y`** — 采集模式直接记录的 user 坐标
3. **catalog 回退坐标**（`x_axis/y_axis`）— 官方 JSON 的原始值，存在系统偏差

**变换链**：`user 坐标 ←→ 宫图像素 ←→ Leaflet latLng`
- `map_transform.json` 存储全局 affine + per-panorama 分区 affine
- 全局 RMSE ≈ 39.5，per-pano RMSE ≈ 27.0（user 坐标单位）

## 关键设计约定

- **仅 l3 层级**：本地只缓存最高细节层级，`project_tour.xml` 运行时自动过滤非 l3 level，避免 krpano 发起 404 请求
- **瓦片缓存策略**：图片 `max-age=86400`，JSON API `no-store`
- **随机出题只从本地已下载场景抽取**，避免进入未缓存资源
- **懒下载**：玩过的场景标记 played，未玩本地场景 < 5 时自动触发预下载
- **资源清理保护已锚点场景**，优先删除未锚点 + 已玩场景的瓦片
- **报告模式**（`?report=1`）：隐藏设置面板、关闭预下载、显示六景快捷导航

## 数据格式

场景元数据核心字段（`scene_catalog.*.json` 中每条记录）：
- `scene_name`, `scene_title`, `panorama_id`, `pano_stub`
- `x_axis`, `y_axis` — 官方坐标（回退用）
- `user_x`, `user_y` — 锚点坐标（优先）
- `click_pixel_xy` — 宫图像素坐标（用于仿射反算）
- `local_tile_count` — 本地已缓存瓦片数
- `season_hint` — 季节标注（spring/summer/autumn/winter）
