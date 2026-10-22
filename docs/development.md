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
npm run check:js       # 应用、scripts 和 tests 的 JS/CJS 语法
npm run test:unit      # 无浏览器逻辑
npm run test:smoke     # 桌面主要页面
npm test              # unit + smoke + review，完整桌面检查
npm run test:desktop   # smoke + review，按需运行
```

`scripts/test-desktop.cjs` 使用明确的文件清单，并强制 `DESKTOP_ONLY=1`。新增测试先确认只含桌面视口，再放入清单；不要直接批量运行历史混合手机套件。测试使用合成账号与临时数据库，不接真实车辆，不发送真实通知。

### 桌面测试清单自动校验（Z02）

`npm run check:desktop-manifest` 递归扫描 `tests/**/*.cjs`，包含无浏览器逻辑、浏览器脚本、性能工具和共享辅助文件；Python 测试不在本清单范围。扫描范围固化在校验代码中，不能通过修改清单缩小扫描范围。新增子目录也会自动纳入，符号链接拒绝处理。

`scripts/desktop-test-manifest.json` 是执行器与校验器的共同来源：`groups.unit`、`groups.smoke`、`groups.review` 使用完整相对文件路径；`exclusions` 每项只登记一个实际存在的文件，并写明非空 `reason`、生命周期 `kind`（helper / benchmark / manual-artifact / retired-mobile / coverage-debt）和非空复核条件 `review_when`。未归类、同组/跨组重复、执行和排除重叠、排除重复、路径不存在、目录/通配符/路径别名、错误分组及空理由均失败。`desktop` 是 smoke + review，默认 `npm test` 是 unit + desktop，均不另行重复登记。`ui_overview_dashboard` 仅在 smoke 登记，合并执行一次；若只需 review 可执行 `node scripts/test-desktop.cjs review`。

所有本地执行组（含 syntax）先校验，失败时不启动测试进程。执行器默认每文件 180 秒，单项失败仍继续独立脚本，最后任何失败或超时都非零退出；可用 DESKTOP_TEST_TIMEOUT_MS 明确设置 100–1200000 毫秒。按同 UID 与创建时间核对后清理该用例的进程组及已跟踪后代，包括自行脱离进程组的浏览器。结果保存到 test-results/desktop 的 JSON，DESKTOP_RESULT_DIR 可改变结果目录。CI 在安装浏览器前显式运行同一校验，unit 组继续运行校验器的合成 CLI 回归。校验器只读文件名和清单，不执行被排除脚本。

执行器默认解析项目 Playwright 对应 Chromium，尊重显式 CHROMIUM_EXECUTABLE；不要求系统 Chrome。常规产品浏览器测试必须在 finally 销毁页面前捕获失败证据，共享合成 fixture 自动提供 recorder，测试 catch 调用 f.fail；直接 fixture 显式 startEvidence。browser_evidence_coverage 检查接入，browser_failure_evidence 验证真实失败仍非零、PNG/诊断可读和隐私边界。不得用捕获异常后返回成功的方式“生成证据”。

新增测试流程：确认桌面视口与合成数据边界，将文件登记在一个基础执行组；暂不纳入常规执行时，在 exclusions 单独写明当前原因和后续准入条件。删除测试时同时删除对应登记。历史脚本没有因本次登记而通过验证；排除仅说明现存覆盖缺口，不等同退役、运行成功或生产验收。不得使用整个目录的排除项，也不要批量将遗留脚本加入执行组。

校验器回归可单独运行 `node tests/desktop_manifest.cjs`；所有临时夹具在本机临时目录创建，并在 finally 中仅删除自身创建的目录。合成用例涵盖嵌套新增文件、重复项、错误路径、有理由排除和各执行组的运行前阻断。

### 已退役的车辆旧套件

2026-10-19，`tests/ui_car.cjs` 已完成逐条对照并删除，原文件可从 `c7bc7af` 的 Git 历史读取。它依赖已移除的“状态总览”页签与 `.car-art img`；不再作为“排除但待修”的现行套件，也不运行空壳或将排除计作通过。

有效断言由现有清单内的 `ui_status_summary`、`ui_tyre_layout`、`ui_vehicle_parameters` 承接，`ui_overview_dashboard` 补充总览导航/焦点/车型未配置行为。缺少覆盖的旧断言已迁入这三组；保留已有断言。逐条替代关系、退役理由、固定 Chromium 验证及故障注入记录见 [Z11 迁移清单](vehicle-ui-test-retirement-2026-10-19.md)。本项只清理已有 `ui_car` 遗留，不扩展未来测试登记机制（Z02），也不代表其他历史浏览器脚本均已迁移或通过。

后端全面变更可运行 `python3 -m unittest discover -s tests -v`。发布验证遵循 [发布流程](release-workflow.md)：在与生产匹配的最终候选中、以真实服务用户跑一次所需完整后端套件。输入、命令和环境未变化，不因创建 commit 再跑一次。

## 本地交接

当前工作写入本机 `handoff.md`，只保留当前分支／工作副本、改动、验证证据和下一步。长历史另存被忽略的 `private/handoffs/`。凭据只引用本机私有配置路径，不抄到文档、测试输出或聊天；从其他 Mac 接手时先核对当前路径是否存在。

代码、提交、候选发布、活动发布、实车验收分别记录。工作副本里的代码不能标为“已上线”。

### 浏览器失败证据（Z03）

`startEvidence(page, {testId, synthetic:true})` 是显式接入的 CJS 采集器。测试必须在 `catch` 中先 `await evidence.fail(error)`，再重新抛出原异常；在 `finally` 中 `await evidence.finish()`，然后关闭页面/浏览器。不要等进程退出才截图：此时现有测试的 `finally` 已关闭浏览器。共享 fixture 用 `evidenceTestId` 接入，并提供 `f.fail(error)`；fixture 初始化失败也在关闭浏览器前采集。

当前接入五个桌面套件：`ui_smoke`、`ui_status_summary`、`ui_overview_dashboard`、`ui_vehicle_parameters`、`ui_tyre_layout`。覆盖它们的页面创建后、关闭前抛出的断言与浏览器错误；共享 fixture 的初始化错误也覆盖。其余历史脚本没有自动接入，启动浏览器前失败、浏览器崩溃后无法截图、硬超时/强杀/取消不保证完整证据。诊断会标明截图失败。单套件内用测试文件及断言行号定位用例，不为每条旧断言改写测试结构。

默认目录是仓库 `test-results/browser-failures/`，可用 `BROWSER_ARTIFACT_DIR` 或 API 的 `outputDir` 指定。仅失败创建目录，子目录名包含安全化 `testId`、时间、随机运行 UUID 和唯一后缀；不会清空已有目录。每次失败最多保存一张桌面视口 `page.png`（8 MiB）、`diagnostic.json`，可选 `trace.zip`（16 MiB）。超限仅删除本次新目录中对应的新文件并写明原因。截图超时 5 秒。成功路径不保存本采集器的大产物，trace 无路径停止并丢弃；现有套件原有的 `/tmp` 截图行为不在本次迁移范围。

JSON 仅含测试标识、运行标识、时间、错误类别、仓库内测试文件与行列、视口及 console/pageerror/requestfailed 计数、采集错误类别。不保存错误文本、断言 actual/expected、console 文本、URL、响应正文、请求头、cookies、凭据或账号数据。截图只允许显式声明的合成 fixture；不能对真实账户页面使用此 API。现有 `web_fixture.py` 和 `insights_fixture.py` 使用临时合成账号、位置与数据库，不打开用户会话。

默认关闭 trace。Playwright trace 可能含 DOM、网络及响应正文，不能仅凭 `synthetic:true` 开启；还需 `trace:true, reviewedTrace:true`，且调用方必须先审核全部页面与响应。当前只有 `tests/fixtures/browser_failure_probe.cjs` 的静态合成页启用：页面仅有合成标题，网络全部拦截中止，无账户、位置、凭据或响应正文。五个应用套件均不保存 trace。

`tests/browser_failure_evidence.cjs` 在 smoke 组运行，串行启动成功/故意断言失败的子进程；失败子进程必须退出 1，且 PNG/ZIP/JSON 可读。验证正常路径无目录、缺失/自定义输出、原文件保留、路径安全化、采集失败不改原文件、大小限制与隐私门禁。故意失败探针在清单逐项排除，理由为父回归已经运行，不能作为独立成功套件。

CI 只上传上述统一目录内允许的文件名，不上传 stdout/stderr 或历史 `/tmp` 截图。上传步骤使用 `if: ${{ !cancelled() }}`，前置测试失败仍执行；未发现文件时忽略，保留 7 天，artifact 名含 GitHub run ID 和 attempt。未使用 `continue-on-error`，不会把测试失败变成成功。取消任务及服务端上传效果仍需实际 Actions 运行确认；本地检查不能替代远端验证。

官方依据：[状态检查表达式](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions#status-check-functions)、[upload-artifact 配置](https://github.com/actions/upload-artifact/tree/v4.6.2#usage)。

### CI 与发布门禁

工作流四项为 Python tests、Desktop tests、macOS native tests、Workflow checks。macOS 原生读取使用 GitHub 托管环境的合成数据，不接生产账户或通知。actionlint 固定 v1.7.12。主分支必要检查及发布前确切 SHA 规则见 [Mac mini 开发](macos-development.md#ci-与发布前置条件)。
