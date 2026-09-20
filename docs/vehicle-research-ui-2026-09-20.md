# 用车研究：第二轮界面设计

基线 `bf20e7a`，独立分支 `codex/vehicle-research-ui`。当前主目录已回到旧 main，保留原目录状态；本轮在独立 worktree 实现。

## 目标与取舍

全部数据已有分析入口，但总览大标题、日期说明、四张统计卡、覆盖说明依次堆叠，1440px 首屏仍看不到字段清单；手机详情同时展示历史、十二条观测、原值分布、场景、边界和实验，难以定位当前任务。

选定“研究工作台”：左侧现有工具目录，右侧将范围、覆盖、字段清单形成紧凑连续结构。保留现有绿灰主题、中文系统字体和数据定义。比较过新的装饰型仪表盘，额外大数字、插画和卡片不能帮助找字段，故采用直接可操作的清单。窄屏默认用带分组的原生工具选择器，完整搜索目录按需展开。

色彩复用现有 token：浅底 #f4f7f8、纸面 #ffffff、正文 #19323b、强调 #20776e、辅助 #50656e；暗色使用已有 #11191d / #1a252b / #e3ecef / #80d4bd / #b8c8ce。标题 22–24px，表格正文 14px，辅助信息 13px，数字等宽；系统中文字体不引入外部字体请求。对齐以左对齐文本、右对齐数值为主；留白 8/12/16/24px；层级靠标题、分隔及真实选中状态表达。

```text
桌面：工具目录 │ 数据利用 + 数据来源
              │ 今日 / 近7天 / 近30天 + 日期范围
              │ 总览 / 场景 / 已选字段
              │ 覆盖摘要 + 可筛选用途 + 折叠统计口径
              │ 字段搜索 / 分类 / 用途 / 排序
              │ 字段 | 返回率 | 有效样本 | 变化
手机：当前工具选择 / 查找
      日期快捷范围 + 按需展开双列自选日期
      覆盖摘要与字段清单
详情：返回清单 + 字段名 / 字典入口
      样本摘要 + 定义折叠
      历史取证 / 分布与场景 / 实验与核实
      图表 + 按需展开前后样本选择
```

## 实施与验收

1. 先补界面验收：快捷日期只有本地研究 GET、搜索与用途联动、排序、清除筛选、从详情回清单保留筛选、详情分区和选样本状态、手机工具切换及草稿保存。
2. 复用研究请求、作用域隔离与结果口径；只改呈现和本地筛选。搜索／排序不新增请求；失败继续显示真实旧结果日期，草稿日期与结果日期分开。
3. 改共享导航的窄屏入口；桌面保留工具名按钮，展开目录支持键盘与搜索。焦点在切换和收起后仍可定位。
4. 字段表桌面使用真实 table 语义；手机每行重排为名称和三项带标签数据。返回率分母为读取次数，空值／无效也属于已返回；无读取显示未知，不伪造 0%。路径及原因保留在详情。
5. 历史保留离散点，不连接缺口；新增数值刻度。观测选择按需展开、每页六条；跨页选样本保留，实验仍由用户填写动作和实际时间。
6. 跑研究完整往返、共享导航、其余受影响工具回归、日夜对比度、320/390/1440px、200% 缩放；目视检查截图后收整样式。

## 外部参考

- [Anthropic frontend-design SKILL.md](https://github.com/anthropics/skills/blob/main/skills/frontend-design/SKILL.md)：先确定任务和视觉方向，再实现并用截图审视；使用既有产品材料与内容。
- [Carbon Data table](https://carbondesignsystem.com/components/data-table/usage/)：搜索与筛选放工具栏，比较数据用表格，次要信息渐进展示。
- [W3C WCAG 2.2 目标尺寸](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)：标准至少 24 CSS px 或满足间距例外；本项目交互控件继续采用至少 44px。

只读取并应用相关公开指导，未安装新的插件、全局 skill 或外部依赖。官方 skill 清单已检索；无须为现有原生 JS 项目引入 Figma、React 或站点生成器。


## 本轮交付与验证结果

实现完成，本地验证通过；交付包含界面代码、回归测试、设计记录与合成数据截图。功能提交 `b77b451` 已按用户授权部署，见[发布记录](vehicle-research-ui-release-2026-09-20.md)；未执行 Git push。工作目录为 `/Users/xinyi/.codex/worktrees/vehicle-research-ui/Zeekr`，原主目录仍保留在 `main` / `25659c9`，未改动其文件。

- 全部 217 个目录字段保留。总览展示实际返回／有效样本，按用途筛选，按变化／样本／名称排序；路径、质量说明、未知值及缺口仍可查看。
- 桌面字段清单进入首屏；手机默认使用分组工具选择器，搜索目录和自选日期按需展开。切换工具保留草稿。
- 字段详情分历史、分布与场景、实验与核实三部分；样本选择按需展开，跨分区保留已选样本，图表使用可读刻度且不连缺口。
- 修复异步导航竞态：字段请求未完成时切回总览，响应不再强制跳回详情。主动打开字段后焦点定位详情入口；返回清单保留搜索、筛选、排序并定位原字段。
- 未修改后端、采集频率、字段定义或研究统计口径；未新增依赖。预览与截图均使用测试夹具合成数据。

验证：

- 26 项研究后端测试通过：`python3 -m unittest discover -s tests -p 'test_vehicle_research*.py'`。
- 16 套 Chromium 脚本通过：`ui_research_workbench`、`ui_vehicle_research`、`ui_insights_navigation`、`ui_insights`、`ui_usage_reports`、`ui_charge_comparison`、`ui_charge_ledger`、`ui_custom_reminders`、`ui_trip_tags`、`ui_parameter_experiments`、`ui_usage_calendar`、`ui_vehicle_life`、`ui_data_quality`、`ui_trip_cards`、`ui_insights_startup`、`ui_field_reviews`（均位于 `tests/`，扩展名 `.cjs`）。最后一次竞态修复后重跑前两套，均通过。
- 新增工作台测试覆盖无归档时返回率未知、筛选排序不追加请求、日期草稿与结果分离、排队请求与焦点、样本选择、账本草稿、日夜主题、320/390/1440px、200% 缩放和主要正文对比度。测试未发出外部请求或研究写入请求。
- 两份生产 JavaScript 的 `node --check`、`git diff --check` 通过。共享导航回归覆盖其余工具；本轮未重跑整个 Python 测试库，也未用生产状态替代本地验证。

浏览器测试环境：`NODE_PATH=/Users/xinyi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules`、`CHROMIUM_EXECUTABLE=/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`。

可重建预览：在本 worktree 执行 `PYTHONDONTWRITEBYTECODE=1 python3 tests/insights_fixture.py --demo`，使用终端返回的本地端口。当前预览为 `http://127.0.0.1:50594/`，进入“用车研究”。演示数据仅来自本地测试夹具，不连接真实车辆。

截图： [桌面总览](vehicle-research-ui-preview/overview-desktop.png) · [手机总览](vehicle-research-ui-preview/overview-mobile.png) · [手机字段详情](vehicle-research-ui-preview/field-mobile.png)。
