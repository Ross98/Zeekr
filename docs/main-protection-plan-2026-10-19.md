# Z04：main 保护最小建议（配置待用户确认）

本项仅完成只读核查与本地方案。未改规则、权限、令牌或 GitHub 配置；未 push、开 PR、触发/重跑工作流、部署或发起故意失败的远端提交。以下均为建议，保护尚未生效。

## 本次证据

2026-10-19 使用既有 GitHub 连接执行 GET，15:26:02 UTC 汇总。精简响应及准确端点保存在本 worktree 忽略目录 `private/local-work-audit/z04-protection-plan-20261019/evidence.json`。没有读取秘密或 Codex sessions。

- [仓库](https://api.github.com/repos/Ross98/Zeekr)：个人、public、默认 main；permissions.admin=true、push=true。PR 开启，creation policy=all；merge/squash/rebase 均允许，auto-merge=false。该权限响应不等于集成具有 Administration API 权限。
- [main](https://api.github.com/repos/Ross98/Zeekr/branches/main)：`c7bc7afa8402f0c643c1f5706c064e7e31d92233`，protected=false，protection.enabled=false，必需 contexts/checks 为空。本次新读，未复用旧状态。
- [rulesets（包含父级）](https://api.github.com/repos/Ross98/Zeekr/rulesets?includes_parents=true)：`[]`。
- [保护详情](https://api.github.com/repos/Ross98/Zeekr/branches/main/protection)：403，`Resource not accessible by integration`。无法读取详情及管理员绕过字段；不能把 403 当作 404 或无保护证明。
- `/repos/Ross98/Zeekr/rules/branches/main` 被连接器白名单拒绝，400 `INVALID_ARGUMENT`，未送达 GitHub。有效规则独立核验未完成，未绕过连接器重试。
- [真实 check-runs](https://api.github.com/repos/Ross98/Zeekr/commits/c7bc7afa8402f0c643c1f5706c064e7e31d92233/check-runs)：`Python tests`（118113813764）、`Desktop tests`（118113813940），均 completed/success；app slug=`github-actions`，id=`15368`。
- [Tests 第 56 次运行](https://github.com/Ross98/Zeekr/actions/runs/39268365480)：push 事件，main 上述 SHA，completed/success。jobs 读取确认名称及步骤，未下载日志或产物。该成功不覆盖未 push 的 Z11/Z02/Z03。

本地基线 `0f863c067e411374c53acc7ae33be2f33c9364f4` 是远端 main 的后代，多 3 个提交：Z11 `3f6e4af`、Z02 `4cd0eae`、Z03 `0f863c0`。本地工作流保留两检查名，新增清单核查及失败证据上传；远端 main 尚无这两项。两版本工作流均有 push、pull_request、workflow_dispatch，无路径/分支过滤；两 job 无跳过条件、依赖或 continue-on-error。仅 desktop，未添加移动端检查。基线仅找到根 AGENTS.md，无 `.agents`。前项 `handoff.md` 是未跟踪本地交接，已在 Z03 源 worktree 读取，不当作基线跟踪内容。

## 推荐配置：PR 合入，零强制人工审批

目标：正常 main 更新经过两项 CI；个人维护者可自行开 PR 并合入，避免自审死锁。建议一条 branch ruleset：`main-required-tests`，精确包含 `refs/heads/main`，无排除；用户确认后才设 Active。branch ruleset 与套餐受限的 push ruleset 不是同一功能。[官方规则及可用性](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)。

| 项目 | 拟配置 |
| --- | --- |
| Require a pull request before merging | 开启；required approvals=0 |
| Require status checks to pass before merging | 开启：`Python tests`、`Desktop tests` |
| 检查来源 | GitHub Actions，实读 app id 15368；保存后回读确认绑定 |
| Require branches to be up to date before merging | 开启（strict） |
| Bypass list | 空；管理员、机器人均不例外 |
| Block force pushes / Restrict deletions | 开启 |
| 其他要求 | 不加签名、线性历史、CODEOWNERS 审批、最近推送审批、部署前置、merge queue 或 restrict updates |

`Tests` 是工作流名；`python`/`desktop` 是 job id。它们及步骤/artifact 名均不是必需 context。不要配置成 `Tests / Python tests`。UI 核对准确名称与来源；若来源无法绑定，保持待确认，不静默接受 any source。近期成功满足七天发现窗口；配置晚于窗口时用正常授权的分支工作刷新检查。[检查名称与来源](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)。

推送正常集成分支并开 PR；无需他人审批，不依赖 auto-merge。核对最新 head/test merge SHA 检查；main 前进时更新分支并等新结果。检查 pending、缺失、失败、取消、来源错误或 SHA 过旧时不合入。GitHub 可将 neutral/skipped 视为满足；不能宣称任何未运行都会被拦。发布关卡只接受两项实际 success，保持 job 无跳过条件。[检查与跳过语义](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)。

## 直接 push 备选

若用户坚持个人直推 main，另选仅必需检查规则，关闭 PR 必需项，保留 strict、两检查、来源绑定及无绕过。不能同时要求 PR 又承诺直推。

先把准确候选提交推到普通暂存分支，等待 push 事件两项 success；确认 main 仍是候选祖先，再 fast-forward main 到同一 SHA。不得 rebase、amend 或新建合并提交后复用旧 SHA 检查。main 前进则重新整合并检查新候选。不能先推未经检查的新提交到 main，再依赖该 push 触发的 CI 放行。本项仅依据官方机制判断可行，未实际验证远端接收；规则拒绝时停止核查，不加管理员绕过解决。

## 权限与管理员边界

public 个人仓库可用 GitHub Free 的分支保护/branch ruleset，无需迁移组织或购买团队功能。实际套餐、UI 保存能力、来源选择、权限委派及保护详情未完整核实，均“配置待用户确认”。现有集成 Administration 读取受限；不索取、更换或扩权令牌。

ruleset 空 bypass list；管理员若列入，即使设 For pull requests only，仍可绕过检查合入。[官方绕过语义](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/creating-rulesets-for-a-repository)。管理员仍能编辑/停用规则，无绕过不等于无法改政策。若用户改选经典 branch protection，额外启用 Do not allow bypassing the above settings（API enforce_admins），否则管理员默认可绕过。不要叠加两套未核实规则。

## 对统一 push 与发布的影响

本批继续串行、仅本地提交，本项不启动下一项。未来获 push/合入授权时，从本批最终提交形成一个集成分支 PR，包含 Z11/Z02/Z03/Z04 及后续授权内容；不用根目录落后且混有改动的 main。建议先由正常集成分支 CI 确认检查名/来源，再启用规则、合入 PR。统一 push 将变成“push 集成分支 + PR 合入”。启用前 CI 成功没有提供历史失败拦截证明。

已读 Z03 `handoff.md`、`docs/release-workflow.md`、`scripts/release/client.py`、`workflow.py`，并定位 server/stage/cutover/verify/rollback 的入口与保护步骤。工具通过 `git show <40位SHA>:<路径>` 覆盖生产公开快照并校验候选哈希；不读取 GitHub CI 状态、不要求提交在远端 main、不自动 push。因此规则不自动拦现有 SSH 发布，CI 成功也不证明生产候选通过。

建议发布前新增人工记录关卡：重读 main/规则，记录 PR、合入 SHA 及两项实际 success；确认 release commit 为最终获准合入版本，逐项核对 paths 文件内容。合入生成新 SHA 时使用最终合入 SHA；main push 检查仍运行则等待，不能将旧 PR SHA 成功算到新 SHA。

候选仍按既有生产匹配快照与已提交 overlay；纯前端跑相关桌面浏览器及准确哈希，后端/auth/未知由真实服务用户在最终候选跑一次全量，不因提交再重复。保留锁、备份、原子切换、回滚、服务与认证检查。本项未访问生产，未重新确认线上版本；实际发布前按原流程对账。

## 后续验证与回退（未执行）

用户确认后，由有权限者保存配置及变更前快照；回读 rule id、Active、main 目标、两 context/来源、strict、PR 零审批、bypass=[]、禁止 force push/删除；排查其他重叠规则。

使用下一次正常获授权 PR：CI 运行期间观察不能合入，两项 success 后观察可合入，记录 head/test merge SHA 与 UI 判定。自然失败时核对拦截；无自然失败则记“失败拦截行为未实证”。不制造远端失败、不试越权 push；push dry-run 不能证明服务器保护生效。workflow_dispatch 成功不能代替 PR 必需事件检查；不开 merge queue，当前工作流无 merge_group。

误配置先暂停合入与发布。另获授权后由管理员修正 context/来源，或仅将本次新增 ruleset Disabled 并恢复事前快照；记录失去保护的窗口，不开放全员 bypass。规则回退不改 Git 历史或生产。已合入代码用普通 revert PR；生产回退沿用 `scripts/release/client.py rollback` 与原服务/认证验证，须单独授权，不以旧业务库覆盖新数据。

审批对象为推荐 PR 路径与准确配置。配置保存、管理员约束实测、失败拦截、本批 hosted CI、生产及真实用户验收均未完成。
