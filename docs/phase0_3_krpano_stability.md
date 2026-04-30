# 阶段 0.3：krpano 本地稳定性与性能收敛

## 阶段目标
- 在本地 MVP 中完成从 Pannellum 到 krpano 的可用切换。
- 让 debug 合成场景与真实实景场景都可稳定渲染。
- 收敛黑块、闪烁、加载抖动问题，形成可复用排障方法。

## 当前完成状态
- krpano 运行时已接入：`frontend/index.html` + `frontend/app.js`。
- 后端已支持 krpano URL 到本地 tiles 的路径映射：`backend/server.py`。
- `scene_debug_tiles` 已可用，6x6x6 显示正确。
- 实景已切到 l3-only 策略（通过 `/assets/project_tour.xml` 的服务端裁剪），避免请求本地不存在层级。
- 过渡黑屏已减轻（场景切换使用 `BLEND(0)`）。
- viewer 已用图统计已适配 krpano 请求路径格式。

## 本阶段关键问题与修复
1. **黑块与“偶尔出现又消失”**
   - 现象：某些角度短暂显示后黑块回退。
   - 根因：XML 宣告层级与本地可用层级不一致（本地只有 l3）。
   - 修复：实景改为 l3-only XML 供给，禁止客户端拉 l4/l2/l1。

2. **debug 场景初始不可渲染**
   - 现象：前端拦截提示“不在 tour.xml 内”。
   - 修复：新增最小 `debug_krpano_tour.xml`，debug 场景独立装载。

3. **拖动后半秒再清晰**
   - 现象：重复拖动时同位置仍有明显等待。
   - 根因：静态文件统一 `no-store`，浏览器无法复用已下载 tile。
   - 修复：图片资源改为可缓存（`Cache-Control: public, max-age=86400`）。

## 阶段结论（是否达标）
- **功能达标**：可以稳定进入实景与 debug 场景，基础交互可用。
- **性能基本达标**：在本地开发环境下，拖动后的重复请求延迟明显下降。
- **工程达标**：形成了“先路径一致、再层级一致、最后缓存策略”的排障流程。

## 建议的 Phase 1 起步事项
- 补一个“场景切换 + 5 秒拖拽”的自动回归脚本（记录 404、平均首块时间）。
- 给 `/assets/project_tour.xml` 增加开关参数，便于比较 full/l3-only 行为。
- 若后续做发布版，细化缓存策略（ETag / Last-Modified / immutable）。
