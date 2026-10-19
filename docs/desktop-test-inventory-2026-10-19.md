# Z02 桌面测试执行清单校验

## 基线与范围

本项从 `c7bc7afa8402f0c643c1f5706c064e7e31d92233` 建立独立 worktree。Z11 原工作区只有约定七路径的改动，逐文件 SHA-256、删除状态以及完整 tracked diff 核对一致后，承接为本地提交 `3f6e4af555bdf9cf6da80477f5316f0838446c8a`。原工作区、原审计记录、主目录 index 和 main HEAD 均保持不变。

Z02 仅修改测试执行基础设施、清单、CI 和开发文档，不修改应用运行逻辑。递归扫描范围为 `tests/**/*.cjs`。当前 110 文件中，55 文件登记在基础执行组，55 文件逐项排除并说明原因。辅助文件、基准实现与手工文档生成器也必须登记；被排除的 `benchmark_overview` 会由已登记的 `ui_overview_benchmark` 间接调用，不重复登记为独立执行项。

清单移入 `scripts/desktop-test-manifest.json`，执行器直接读取同一来源。新增 `tests/desktop_manifest.cjs` 到 unit；从 review 删除与 smoke 重复的 `ui_overview_dashboard` 登记。既有 desktop 合并执行覆盖不变。单独 review 命令的总览覆盖由 smoke/desktop 获取，详见开发说明。

## 校验与回归

- 首次 RED：合成嵌套新增文件未归类时，尚未实现的校验器错误返回 0，测试按预期失败；实现后返回 1。
- 20 个真实 CLI 合成用例通过：未归类、同组/跨组重复、错误路径、执行/排除重叠、重复排除、空理由、失效排除、目录/路径别名、错误分组、错误 exclusions 结构、有效排除、范围外 Python 文件、desktop 执行顺序和 `DESKTOP_ONLY=1`，以及五种执行组启动前阻断。临时夹具均由 finally 删除，仅清理本用例自己创建的目录。
- `npm run check:desktop-manifest` 通过，110 文件全部归类。
- `npm run test:unit` 通过，20 个文件。
- `npm run check:js` 通过，32 个应用 JS 文件；新增执行器、校验器及测试文件另外完成 `node --check`。
- `npm run test:desktop` 通过，35 个文件，184.5 秒，串行执行；包含 Z11 四组承接专项。Playwright / playwright-core 均为锁文件中的 1.62.1，显式指定对应 Chromium 151.0.7922.34。通过 NODE_PATH 复用本机已安装的匹配依赖，没有修改依赖或锁文件。首次沙箱内浏览器 SIGABRT、夹具无法启动；提升执行权限后完整桌面套件正常退出 0。
- `git diff --check` 通过；已检查改动范围及合成数据，无真实车辆数据、会话或凭据写入提交。

## 边界与后续

CI 配置已经接入，但本轮不 push，未在 GitHub 运行 CI。55 个排除项不代表通过；其逐文件原因在清单中，后续准入须单独验证当前选择器、合成夹具和桌面执行路径。扫描范围不包括 Python、其他扩展名和 tests 之外的文件。理由校验只保证非空，理由是否充分仍需代码审查。

本轮不运行无关后端全量，不合并 main、不部署、不进行实车验收，也不启动 Z03。Z03 应从包含 Z11 承接与 Z02 的最终本地提交建立新分支；准确 SHA 见本次交接结果。

完整桌面日志、源文件哈希和主目录 index 哈希保存在本 worktree 被忽略的 `private/local-work-audit/z02-desktop-manifest-20261019/`。Z11 原审计目录保持原处。
