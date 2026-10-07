# 企业微信周期报表资产

六张固定底图：`day` / `week` / `month` × `light` / `dark`。每张为 1068 × 540、三通道 RGB 原始像素，zlib 压缩；只预绘固定标题和指标标签。

两套字形：`glyphs-light.zlib` 与 `glyphs-dark.zlib`。解压后前 4 字节为大端 JSON 索引长度，随后为 UTF-8 索引与按角色预着色的 RGB 字形。索引项记录偏移、宽、高、advance。底色已混入字形，因此主题变化须重建整套资产，不能仅换运行时 palette。

运行时 `zeekr_control/periodic_report.py` 用 Python 标准库解压、按行贴字与生成 PNG；不依赖 Pillow、系统字体、浏览器或网络。缺资产、无支持字形、非法输入或文本溢出均停止出图；投递层保留文字兜底。

## 构建

仅构建阶段需要 Pillow 与指定字体。沿用已有来源的 Noto Sans SC（文件名 `NotoSansSC.ttf` 时采用可变字重 500）；许可证为同目录 `OFL.txt`。

```sh
python3 scripts/build_periodic_report_assets.py --font /tmp/zeekr-wecom-map-preview/NotoSansSC.ttf
```

可用 `--font-index` 指定字体集合索引，`--output` 指定生成目录。字体路径只是本次构建输入，不是运行时依赖。重建前先核对字体来源与许可证；更换字体须更新相应许可。

`manifest.json` 记录资产格式 version、画布尺寸、字体 SHA-256、font index、字形角色与像素大小，以及八个压缩资产各自的 SHA-256。当前 version 为 1。manifest 用于追踪构建输入与校验发布资产；当前渲染器未逐次校验 manifest 哈希，不应宣称运行时有哈希认证。

重建后核对 manifest 与全部资产，一并做亮暗三周期及空数据、部分数据、极大数值的桌面图片验收。改字符集、字级、主题、画布或固定标签均须重建。

## 数据与验收边界

动态文本由本地汇总填充，示例带“演示数据”。`—` 是缺失，`0` 是已知零，“部分”是记录/指标不完整。采样天数不是全天覆盖率；估算能耗与账单实付是不同口径。

12 张样式预览已获独立视觉审查 `ship`；这只覆盖 PNG 样式，不能证明真实推送、后台数据或部署完成。完整口径、CLI、outbox 与验证边界见 `docs/periodic-wecom-reports-2026-10-07.md`。后续已接独立服务器调度，时间与启用状态见报表说明及发布记录。六图在15% CPU/128MiB下约1.2–1.3秒/张；这一资产验收不代表已真实发送。
