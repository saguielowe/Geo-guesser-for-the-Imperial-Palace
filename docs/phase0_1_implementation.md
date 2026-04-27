# 阶段 0.1 实施说明（自动采集）

## 目标
- 从官方坐标接口自动获取场景索引。
- 基于锚点 URL 批量抓取 2-3 个场景的最小资源集。
- 同时产出原始归档数据与处理后场景索引。
- 验证脚本可重复执行且不会重复下载已存在文件。

## 当前实现
- 脚本文件：`scripts/phase0_fetch_resources.py`
- 坐标源：`https://pano.dpm.org.cn/api/zh-CN/project/coordinates.json`
- 全局 tour 源：`https://pano.dpm.org.cn/api/zh-CN/project/krpano/tour.xml`
- 锚点样本：
  - `panoramas/47/.../2942_autumn.tiles/...`（午门前）
  - `panoramas/20/.../2038_summer.tiles/...`（太和殿广场前）
  - `panoramas/61/.../3222_summer.tiles/...`（乾清门）

## 目录产物
- 原始数据：`data/raw/`
  - `coordinates.json`
  - `project_tour.xml`
  - `panoramas/{id}/tiles/{pano_stub}/{face}/{level}/01/...jpg`
- 处理后数据：`data/processed/scene_index.phase0.json`
- 运行日志：`logs/phase0-manifest-*.json`、`logs/phase0-summary-*.json`

## 执行命令
在项目根目录运行：

```powershell
C:/Users/23329/.conda/envs/chat/python.exe scripts/phase0_fetch_resources.py --workspace . --sample-size 3 --levels l3
```

## 已验证结果（本次）
- L3 执行：下载成功 19 条，失败 0 条，跳过已存在 1 条。
- 三个场景都完成了 `tour_scene_name` 和 `tour_scene_title` 对齐。
- 说明：统一 tour 源可用，L3 最小集抓取成功。

## 数据字段约定
`scene_index.phase0.json` 每条包含：
- `panorama_id`、`pano_stub`
- `scene_id`、`scene_name`、`scene_title`
- `panorama_name`、`scene_group_name`
- `coordinate`、`x_axis`、`y_axis`
- `seasons`（保留多季节可用性）
- `tile_template`
- `levels_fetched`
- `available_tile_count`、`failed_tile_count`

## 已知限制
- 当前只抓取最小验证 tile（每个面每层 1 张）用于可行性验证，不是完整离线包。

## 目前识别到的规律
1. scene 命名与资源命名高度一致：`scene_{scene_id}_{season}` 与 `{scene_id}_{season}.tiles` 基本可互相映射。
2. tile 路径结构稳定：`panoramas/{panorama_id}/krpano/panos/{pano_stub}.tiles/{face}/{level}/01/{level}_{face}_01_01.jpg`。
3. cubemap 六面固定：`f/b/l/r/u/d`，每个等级可按面批量遍历。
4. 坐标接口中的 `seasons` 字段可直接作为“多季节可用性”标注，不需要预设季节优先级。
5. 全局 tour.xml 可直接作为统一 scene 元数据源，避免逐 panorama 猜路径。

## 下一步（阶段 0.2 前）
1. 在不改主流程的前提下补一个 tour 路径探测策略（可选）。
2. 把锚点从固定 3 个扩展为“从 coordinates 自动抽样 N 个”。
3. 新增失败重试报告聚合，方便判断是否可规模化。
4. 如果要进入 viewer 集成验证，可在后续阶段改为下载每个面多个分块，不只 `01_01`。
