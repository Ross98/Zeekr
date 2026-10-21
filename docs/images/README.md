# README 截图

这些 PNG 来自项目当前桌面界面，全部使用隔离的合成数据。截图不是实车记录，也不是用户的真实行程、账目或地点。

- `local-trips.png`：连续出行链与 24 小时出行节奏。
- `charging-review.png`：月度充电回顾与费用分析。
- `charging-ledger.png`：统一补账与账单管理。
- `expense-ledger.png`：生活支出分类图与流水。
- `trip-tags.png`：标签分布、逐趟标注与分析。

## 重新生成

在仓库根目录完成浏览器测试依赖安装后运行：

```bash
npm ci
npm run browser:install
node scripts/capture-readme.cjs
```

脚本启动临时本地测试服务，不读取真实账号会话或生产数据库，不请求车辆云端，不打开定位与地图。图片固定为 1440 × 1500 的桌面视口，并标注合成数据来源。可通过 `CHROMIUM_EXECUTABLE` 指定已安装的 Chromium。

生成前会检查可见文字中的手机号、车牌、凭据样式、精确坐标及测试专用隐私占位符；仍需人工查看每张图，核对没有隐私内容、布局裁切或加载错误。PNG 不附带浏览器地址栏或账号登录表单。
