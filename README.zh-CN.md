# incremental-work-order

[English](README.md) · **中文**

**给长期运行的编码 agent 用的派工流程。**

一个主树调度；每棵子树执行自己那一段工单；批次末打的是 **检视窗口** 而不是停下等审批；合并回主树要你批，
而且 **必须在主树重验**。

## 它解决什么

长期运行的 agent 作业会以几种可预测的方式坏掉：计划只活在聊天里、蒸发掉；执行者替你做产品决策；
门绿了却什么都没证明；并行的工作树只扩不并；"完成了"其实没验过。而这五件事底下压着同一个**人的成本**：
**你会变成机器的人肉推进器**——每走一步都要你回到键盘前，于是你一天里最贵的时间花在"传话"上，而不是决策上。

这套 skill 是一套 **以仓库为权威** 的派工流程，专门修这五件事；它的立意是**把时间还给决策**：
你给目标、拍该拍的板、想什么时候看就挑一个检查点看——然后可以走开，回来也不用交接仪式（见 `SKILL.md` §0c）。

## 模型

```text
用户  ⇄  调度者（主工作树里的主会话）
          │   规划、写单、投递、观察、合并
          └── 调度权威（仓库文件）
              ├── README.md      角色 + 索引 + 流程规则（唯一规则文本）
              ├── manifest.json  派单视图：orders / executors / dispatch_rules
              ├── status.md      汇总账：终态、已知缺口、成本
              ├── rulings.md     裁决账（R-0001… 可引用）
              └── prefs.md       偏好账（你的既定偏好）
              └── 执行者（每棵子树一个长期会话）
                  ├── worktree-charter.md   范围、写权、切片、批次
                  ├── work-orders/**        契约权威
                  ├── status.md             执行账 + 检查点报告
                  └── evidence/**
```

- **树是层级**：父树可写它派出的子树（白名单 `work-orders/**` 与 `worktree-charter.md`）；子树对父树只读；
  子树之间互不写；层级之外的仓只读，**且不派单**。
- **投递即通知**：把单写进子树并在那棵树上提交，就是通知本身——执行者每个阶段边界重读它自己的树与主树的
  规则/队列/账，下次重读自然纳入。会话之间不传消息。
- **执行者不会为检查点停下**：批末它给自己那棵树打 `checkpoint/<批次名>` tag、把检查点报告写进本树 status，
  然后继续干活。那个 tag 是你想验货时用的窗口。
- **升级 ≠ 停下**：需要人拍的部分标成阻塞，其余不受影响的单继续做。
- **批准分档**：产品语义、安全、授权、合同变更、开新树、合并回主树、**放宽**验收 —— 你定；调度者负责派单、
  收紧、观察；执行者只决定单内怎么实现。

## 安装

三条路，都在本机实测过（2026-09-18）；插件清单通过 `claude plugin validate`。

**1. 当插件装**——Claude Code，以及读取同一套 marketplace 格式的 ZCode：

```bash
claude plugin marketplace add mmm-05610/incremental-work-order
claude plugin install incremental-work-order@incremental-work-order
```

`claude plugin details incremental-work-order` 会报 `Skills (1)`。加载保持按需：常驻的只有名称与描述，
触发时才加载完整 `SKILL.md`；`claude plugin update incremental-work-order` 跟新版本。

**2. 安装脚本**——任何 agent，除 git 与 POSIX shell 外无依赖：

```bash
curl -fsSL https://raw.githubusercontent.com/mmm-05610/incremental-work-order/main/install.sh | sh -s -- --tag v0.2.0
```

从克隆目录跑也行：`./install.sh --target ~/.claude/skills`、`./install.sh --from . --copy`、
`./install.sh --update` 快进已有安装。脚本会选第一个存在的技能目录（`~/.agents/skills`，否则
`~/.claude/skills`），并且**拒绝覆盖**已存在的安装。

**3. 手动**——一条命令，钉住一个 release：

```bash
git clone --branch v0.2.0 https://github.com/mmm-05610/incremental-work-order ~/.agents/skills/incremental-work-order
```

只要能读 `SKILL.md`、能跑 git 的 agent 都行；启动提示词假设有 `/goal` 这类长期会话入口。
**只留一份**——项目内的 `<项目>/.agents/skills/incremental-work-order` 会遮蔽用户级那份。

## 快速开始

1. **初始化**（还没有任何单）——让 agent 跑初始化清单：建立 `docs/implementation/{README.md, manifest.json,
   status.md, rulings.md, prefs.md, executor-charter.md}`，`orders` 与 `executors` 留空，status 首条写
   **实测基线**（提交 sha + 跑一次构建/测试的计数与退出码），项目已有计划文档就只记指针，只显式 stage 并提交。
   做完它会停下问你要做什么。
2. **派一件你已经想清楚的小事**——调度者会归类、过可派性判断、切成有序的单，把第一张投递进某棵树。
3. **开树 + 起执行者**（这两步都要你）：批准开树提议，然后把调度者**在回复里给全**的启动提示词，粘进一个
   工作目录设为该子树的新会话。
4. **想验就验**——`git -C <子树> tag -l 'checkpoint/*'`，再看那棵树的 `docs/implementation/status.md`
   （能试什么 / 要你拍的 / 花了什么 / 恢复点）。亲自跑一遍它说能用的东西，新问题就是这么冒出来的。
5. **批次末合并**——调度者提议（必须点明检查点 tag **与你要批的 commit sha**）、你批、按那个 sha `merge --no-ff`，
   然后**在主树重跑门与全量套件**，不沿用执行者的数字。

## 目录

| 文件 | 作用 |
| --- | --- |
| `SKILL.md` | 调度者的规则——整套模型都在这一个文本里 |
| `GETTING-STARTED.md` | 给人看的上手（五步） |
| `assets/work-order-template.md` | 工单骨架（JSON frontmatter、WHEN/THEN 场景、复选框 Stages、门四列） |
| `assets/worktree-charter-template.md` | 每棵树的章程（范围、写权、切片、批次） |
| `assets/executor-charter.md` | 执行者纪律 |
| `assets/executor-goal-prompt.md` | ≤15 行启动提示词 |
| `assets/role-goal-prompts.md` | 可选角色与循环的启动提示词（审阅者/验收/侦察者/调度者循环） |
| `assets/prefs-template.md` | 偏好账（执行模式、批准胃口、节奏、成本上限） |
| `assets/status-template.md` | 执行账格式，含 §Questions 通道 |
| `scripts/validate_order.py` | 结构校验器：`--strict`、`--batch <名>`（批次门要求阶段复选框全勾 + `## Batch report` 齐全）、`--legacy-ok`（旧队列）、`--manifest`（对账） |
| `references/initialization-checklist.md` | 初始化建什么、不建什么 |
| `references/false-green-checklist.md` | 假绿的七种形态 + 三个真实案例 |
| `references/roles-and-loops.md` | 开角色、换循环前的自查清单 |
| `evals/evals.json` | 18 条行为用例（放在仓库里，不随 skill 分发） |
| `examples/` | 合规 / 未完工 / 不合规 三张单，CI 靠它们证明门有牙 |

## 一屏规则

1. 每张单都必须能让"只有仓库、读不到聊天记录"的人独立执行。
2. 事实分三级：实测（带 `文件:行` 或数字）/ 引用（带来源与日期）/ 未验证——**未验证绝不写成实测**。
3. 每道门要写**反例**，也要写**资源缺席时的行为**；缺席必须失败。
4. 按**可验证性与写权面**切活，不按野心切：一处连续 → 一个执行者；多处独立 → 每处一棵树；
   共享契约 → 先定契约再分派。
5. 批次属于执行树；主树不存批次清单。
6. 投递之后靠阶段边界重读取活。不传消息、不留副本、不做漂移合并。
   投递用 **pathspec 形式**提交（`git commit -- <路径>`，新文件先 `git add -N`）——**绝不 `git add` 后裸 `git commit`**：
   执行者与你共用同一个暂存区，裸提交会把对方暂存的文件带走。
7. 修订必须留回执（`已纳入 work order <N> 修订 @<sha>`），让"改向有没有生效"成为事实。
8. **人的时间是最稀缺的资源**：需要拍板的攒在一处，每条给「选项 / 代价 / 我的建议 / 不拍的后果」，
   调度者能自己拍的绝不问（`SKILL.md` §0c）；汇报默认一屏，细节留在文件里。
9. PARTIAL 是可敬的、也可以合——只要该树回归绿、待合部分可验证、未验部分登记为已知缺口。
10. 合并一次一个、在主树重验，批准人、冲突、摘要、回滚路径都要写下来。**批准绑定检查点的 commit sha**
   而不是它所在的分支——执行者不会停，分支会往前跑，而批准不会。若批准之后主树自己动过，先重新核集成条件。
11. 规则只有一份，别处只引用。
12. 每张单都**必须显式声明并行度**：给非空的 `parallel_units` 列表，或写 `parallelism: "none"` 加理由
    （空列表/缺省曾静默等于单线程——真实队列上量到 81 张单里 64 张是空列表）。执行者**只能在声明出来的单元**之间
    开子代理：**深度 ≤1、同时在跑不超过项目记录的上限**，而且**子代理不是写者**——它们只产出改动，不碰契约、
    不碰账本、不跑 git；提交、勾阶段、跑门、记账都由执行者本人完成（同一 worktree 多写者，正是这套流程
    已经修掉的暂存区交错缺陷）。
13. 调度侧的规则是**默认值**不是镣铐：先查 `prefs.md`，问一次就记下来，偏离要写 `waive` 理由；
    执行侧相反要**严**——固定工单格式、WHEN/THEN 场景、复选框阶段、结构校验器，因为没人跟执行者直接对话。

## 明确不做

- **不替用户开会话**：agent 开不了会话，启动提示词由你粘贴。（如果你的环境提供创建会话入口且你授权，那是你的扩展。）
- **不往不受你调度的仓派单**：要么先纳入层级，要么只当只读资料。
- **不自动合并、不自动发布、不悄悄放宽验收**。
- **不声称"全绿"本身有任何意义**——见反假绿清单。

## 贡献与社区

| 文件 | 为什么有它 |
| --- | --- |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 两条底线（规则只有一份；每道门都要被证明能拒绝东西）与提 PR 的方式 |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Contributor Covenant v2.1 |
| [SECURITY.md](SECURITY.md) | 这里什么算安全 bug（危险的规则、抓不到东西的门）以及私密报告渠道 |
| [SUPPORT.md](SUPPORT.md) | 提问去哪、报 bug 去哪 |
| [MAINTAINERS.md](MAINTAINERS.md) | 谁维护、决定怎么产生 |
| [AGENTS.md](AGENTS.md) | 给被派来改这个仓库的 agent 的指令 |
| [CHANGELOG.md](CHANGELOG.md) | Keep a Changelog；版本语义跟随 skill 契约 |
| [CITATION.cff](CITATION.cff) | 引用方式 |
| [examples/](examples/) | 三个样例单，CI 全部跑 |
| [.github/workflows/validate.yml](.github/workflows/validate.yml) | CI：元数据、eval 集、校验器编译、合规通过、未完工批次被拦、不合规被拒 |

`python3 scripts/validate_order.py <路径> --strict` 就是 CI 跑的那套，提 PR 前先本地跑一遍。

## 许可

MIT —— 见 [LICENSE](LICENSE)。
