# 开发验证

Python 运行期仅用标准库，最低 3.9。前端开发测试使用 Node.js 20+；`package-lock.json` 固定 Playwright 和对应 Chromium。

## 一次安装

在项目目录执行：

```bash
npm ci
npm run browser:install
```

Chromium 仅用于本机合成测试，不作为服务器运行依赖。Linux 首次缺系统库时使用 `npx playwright install --with-deps chromium`。使用既有浏览器可设置 `CHROMIUM_EXECUTABLE`；这属于替代环境，记录其版本，不声称与锁定浏览器相同。

## 按改动选择

```bash
# 新增逻辑及直接相关后端测试，按实际文件调整
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_cost_summary.py -v

npm run check:desktop-manifest # 桌面测试文件逐项归类
npm run check:js       # 第一方 JS 语法
npm run test:unit      # 无浏览器逻辑
npm run test:smoke     # 桌面主要页面
npm test              # 费用、焦点、懒加载、通知展示及相关桌面回归
npm run test:desktop   # smoke + review，按需运行
```

`scripts/test-desktop.cjs` 使用明确的文件清单，并强制 `DESKTOP_ONLY=1`。新增测试先确认只含桌面视口，再放入清单；不要直接批量运行历史混合手机套件。测试使用合成账号与临时数据库，不接真实车辆，不发送真实通知。

### 桌面测试清单自动校验（Z02）

`npm run check:desktop-manifest` 递归扫描 `tests/**/*.cjs`，包含无浏览器逻辑、浏览器脚本、性能工具和共享辅助文件；Python 测试不在本清单范围。扫描范围固化在校验代码中，不能通过修改清单缩小扫描范围。新增子目录也会自动纳入，符号链接拒绝处理。

`scripts/desktop-test-manifest.json` 是执行器与校验器的共同来源：`groups.unit`、`groups.smoke`、`groups.review` 使用完整相对文件路径；`exclusions` 每项只登记一个实际存在的文件，并写明非空 `reason`。未归类、同组/跨组重复、执行和排除重叠、排除重复、路径不存在、目录/通配符/路径别名、错误分组及空理由均失败。`desktop` 是 smoke + review 的派生顺序，不另行重复登记。`ui_overview_dashboard` 仅在 smoke 登记，合并执行仍执行一次；单独 `npm test` 的 review 不再重复执行它，需运行 smoke 或 desktop 获取该覆盖。

所有本地执行组（含 syntax）先校验，失败时不启动测试进程。CI 在安装浏览器前显式运行同一校验，unit 组继续运行校验器的合成 CLI 回归。校验器只读文件名和清单，不执行被排除脚本。

新增测试流程：确认桌面视口与合成数据边界，将文件登记在一个基础执行组；暂不纳入常规执行时，在 exclusions 单独写明当前原因和后续准入条件。删除测试时同时删除对应登记。历史脚本没有因本次登记而通过验证；排除仅说明现存覆盖缺口，不等同退役、运行成功或生产验收。不得使用整个目录的排除项，也不要批量将遗留脚本加入执行组。

校验器回归可单独运行 `node tests/desktop_manifest.cjs`；所有临时夹具在本机临时目录创建，并在 finally 中仅删除自身创建的目录。合成用例涵盖嵌套新增文件、重复项、错误路径、有理由排除和各执行组的运行前阻断。

### 已退役的车辆旧套件

2026-10-19，`tests/ui_car.cjs` 已完成逐条对照并删除，原文件可从 `c7bc7af` 的 Git 历史读取。它依赖已移除的“状态总览”页签与 `.car-art img`；不再作为“排除但待修”的现行套件，也不运行空壳或将排除计作通过。

有效断言由现有清单内的 `ui_status_summary`、`ui_tyre_layout`、`ui_vehicle_parameters` 承接，`ui_overview_dashboard` 补充总览导航/焦点/车型未配置行为。缺少覆盖的旧断言已迁入这三组；保留已有断言。逐条替代关系、退役理由、固定 Chromium 验证及故障注入记录见 [Z11 迁移清单](vehicle-ui-test-retirement-2026-10-19.md)。本项只清理已有 `ui_car` 遗留，不扩展未来测试登记机制（Z02），也不代表其他历史浏览器脚本均已迁移或通过。

后端全面变更可运行 `python3 -m unittest discover -s tests -v`。发布验证遵循 [发布流程](release-workflow.md)：在与生产匹配的最终候选中、以真实服务用户跑一次所需完整后端套件。输入、命令和环境未变化，不因创建 commit 再跑一次。

## 本地交接

当前工作写入本机 `handoff.md`，只保留当前分支／工作副本、改动、验证证据和下一步。长历史另存被忽略的 `private/handoffs/`。凭据只引用本机私有配置路径，不抄到文档、测试输出或聊天；从其他 Mac 接手时先核对当前路径是否存在。

代码、提交、候选发布、活动发布、实车验收分别记录。工作副本里的代码不能标为“已上线”。
