# 资源整理说明（停止新增下载）

## 结论
- 已停止新增下载，仅整理现有本地资源。
- 现有资源主要集中在 `data/raw/panoramas/20/`，另有少量在 `47/`、`61/`。
- 官方坐标数据里的 panorama 大分组总数为 29（不是 2000+；2000+ 是 scene 规模）。

## 为什么在 panoramas/20，而不是 2038/？
- `20` 是 **panorama_id（景区/大分组）**。
- `2038` 是 **scene_id（具体场景）**。
- 路径里同时会出现两者：
  - `panoramas/20/.../2038_summer.tiles/...`
- 所以 `20` 和 `2038` 不需要相等，它们属于不同层级编号。

## 你提到的 01-06 文件夹规律
- 在当前可用 L3 资源里，绝大多数场景每个面的 row 目录是 `01..06`。
- 这对应每面 6x6 = 36 张，六个面共 216 张。

## 已生成的整理产物
- 本地资源盘点：`data/processed/local_tiles_inventory.json`
- 本地 MVP 20 场景：`data/processed/scene_catalog.mvp20.local.json`

## 现有规模（已落地）
- 已下载 scene stub：42
- 已下载 jpg：8337
- panorama_id 分布：20、47、61

## 集中度检查
- 本地已下载 stub 分布：20 占 40/42（95.24%），确实偏集中。
- 已将本地 MVP 清单重排为多分组优先：
  - `scene_catalog.mvp20.local.json` 分布为 20:18, 47:1, 61:1。

## 后续执行约束
- 不再执行全量下载。
- MVP 仅使用 `scene_catalog.mvp20.local.json` 中的 20 个场景。
- 下一阶段目标转为 viewer 接入与题库玩法闭环，不再扩充抓取范围。

## 2026-05-01 review 补充
- 发现 `scene_3170_summer` 在 `scene_catalog.phase0.json` 中缺失坐标字段（`coordinate/x_axis/y_axis` 为空），无法用于地图真值定位。
- 处理策略：不再强行保留该点，已从 `scene_catalog.mvp20.local.json` 中替换为 `scene_2826_summer`（有完整坐标，且已下载对应 l3 tiles）。
- 结果：MVP 20 场景当前均可用于地图定位显示。
