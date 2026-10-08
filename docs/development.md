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

npm run check:js       # 第一方 JS 语法
npm run test:unit      # 无浏览器逻辑
npm run test:smoke     # 桌面主要页面
npm test              # 费用、焦点、懒加载、通知展示及相关桌面回归
npm run test:desktop   # smoke + review，按需运行
```

`scripts/test-desktop.cjs` 使用明确的文件清单，并强制 `DESKTOP_ONLY=1`。新增测试先确认只含桌面视口，再放入清单；不要直接批量运行历史混合手机套件。测试使用合成账号与临时数据库，不接真实车辆，不发送真实通知。

后端全面变更可运行 `python3 -m unittest discover -s tests -v`。发布验证遵循 [发布流程](release-workflow.md)：在与生产匹配的最终候选中、以真实服务用户跑一次所需完整后端套件。输入、命令和环境未变化，不因创建 commit 再跑一次。

## 本地交接

当前工作写入本机 `handoff.md`，只保留当前分支／工作副本、改动、验证证据和下一步。长历史另存被忽略的 `private/handoffs/`。凭据只引用本机私有配置路径，不抄到文档、测试输出或聊天；从其他 Mac 接手时先核对当前路径是否存在。

代码、提交、候选发布、活动发布、实车验收分别记录。工作副本里的代码不能标为“已上线”。
