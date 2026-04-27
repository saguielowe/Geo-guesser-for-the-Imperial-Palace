# 阶段 0.2 自动发现与全量 Tile 下载

## 你提出的目标
- 不再手工给 URL，由脚本自动发现 scene。
- 自动建立“图片资源 <-> 场景位置坐标”的对应关系。
- 支持把 tile 批量下载到本地，方便后续 viewer 接入。

## 已完成实现
- 新增脚本：`scripts/phase0_bulk_tiles.py`
- 自动输入源：
  - `https://pano.dpm.org.cn/api/zh-CN/project/coordinates.json`
  - `https://pano.dpm.org.cn/api/zh-CN/project/krpano/tour.xml`
- 自动产物：
  - `data/processed/scene_catalog.phase0.json`（scene 元数据 + 坐标映射）
  - `logs/phase0-bulk-summary-*.json`
  - `logs/phase0-bulk-manifest-*.json`

## 核心能力
1. 从 tour.xml 自动枚举全部 scene（当前识别到 2140 个）。
2. 从 preview URL 自动提取 `panorama_id`。
3. 从 `scene_name` 自动提取 `pano_stub`（如 `scene_2038_summer` -> `2038_summer`）。
4. 通过 `scene_name` 与 coordinates 对齐，得到 `coordinate/x_axis/y_axis/seasons`。
5. 支持 `--download-mode none|full`：
   - `none`：仅发现与估算。
   - `full`：按 level 全量枚举并下载 tile。
6. 支持并发下载 `--workers`。

## 已验证结果
### 1) 全量估算（不下载）
命令：

```powershell
C:/Users/23329/.conda/envs/chat/python.exe scripts/phase0_bulk_tiles.py --workspace . --levels l3 --download-mode none
```

结果摘要：
- `scene_count_total = 2140`
- `estimated_total_tiles(l3) = 461754`

对应日志：`logs/phase0-bulk-summary-20260424-145530.json`

### 2) 全量下载抽检（3 个 scene）
命令：

```powershell
C:/Users/23329/.conda/envs/chat/python.exe scripts/phase0_bulk_tiles.py --workspace . --levels l3 --download-mode full --scene-limit 3 --workers 16
```

结果摘要：
- scene_1_summer: skipped 216 / failed 0（已下载过）
- scene_2_summer: downloaded 216 / failed 0
- scene_3_summer: downloaded 216 / failed 0

对应日志：`logs/phase0-bulk-summary-20260424-145542.json`

## 发现的关键规律
1. scene 与 tile 命名一致：`scene_{id}_{season}` <-> `{id}_{season}.tiles`。
2. tile 路径模板稳定：

```text
/panoramas/{panorama_id}/krpano/panos/{pano_stub}.tiles/{face}/{level}/{row}/{level}_{face}_{row}_{col}.jpg
```

3. 六面固定：`f/b/l/r/u/d`。
4. 对该站点常见 4 级宽度（5184/2624/1280/640），实际发布文件的等级映射是：
   - `l3 -> 2624`
   - `l2 -> 1280`
   - `l1 -> 640`
5. 这条映射修正后，full 下载抽检失败降为 0。

## 直接跑全量下载（L3）

```powershell
C:/Users/23329/.conda/envs/chat/python.exe scripts/phase0_bulk_tiles.py --workspace . --levels l3 --download-mode full --workers 16
```

说明：
- 不加 `--scene-limit` 即默认全量 scene。
- 过程较长，建议先开一个专用终端执行。
- 已支持断点续跑（已存在文件会 `skipped_exists`）。

## 后续对 viewer 的价值
- `data/processed/scene_catalog.phase0.json` 已给出 scene 与坐标关系，可直接做题库。
- 本地 tile 文件结构已经符合 URL 模板，后续可以通过本地静态服务或路径映射接入 viewer。
