# 个性化社交媒体写作 Agent 产品改进报告

> 状态说明：本文是本轮实施前的缺点分析与来源溯源，保留用于解释设计依据。其中评测、运行步骤和人工审批已在当前本地工作区落地；最新实现状态与 GitHub 旧版对比请以 `CHANGE_COMPARISON_REPORT.md` 为准。

## 1. 报告目的

本报告基于当前项目代码、`RAG_DESIGN.md` 以及以下公开项目的可复用经验整理：

- `langchain-ai/social-media-agent`：人工审核与内容状态流转
- `harness/harness-evals`：统一评分、阈值和是否通过
- `agentevals-dev/agentevals`：保存一次运行过程，后续反复评测
- `openai/openai-knowledge-retrieval`：RAG 数据集、检索评测和模块分层
- `confident-ai/deepeval`：分别评测检索与生成
- `langchain-ai/agentevals`：Agent 执行步骤和预期路径评测
- `mateaix/mateclaw`：小红书内容包装、去 AI 痕迹、人工审批
- `blacktwist/social-media-skills`：把平台、任务和写作能力拆成独立模板
- `WesleySmits/agent-skills`：品牌声音、内容日历和内容复用方法
- `EleutherAI/lm-evaluation-harness`：用版本化配置保证评测可复现

报告不追求搭建大型 Agent 平台，而是回答三个现实问题：

1. 当前产品最影响可用性的缺点是什么？
2. 在现有 Python、FastAPI、SQLite 架构内应该如何改进？
3. 如何验证改进确实有效，而不是仅仅增加了功能和代码？

---

## 2. 产品现状

### 2.1 当前定位

当前产品是一个面向个性化社交媒体写作的本地 Agent。用户可以创建角色、导入该角色过去的文章，由系统提取写作画像，并在新任务中检索相关历史文章作为参考，最后生成符合人物风格的内容。

现有主要流程为：

```text
创建角色
  → 导入历史文章
  → 重建角色画像
  → 输入写作任务
  → 检索相关文章和反馈
  → 生成初稿
  → 自动审稿
  → 必要时重写
  → 保存最终结果
```

### 2.2 已具备的能力

当前版本已经具备一个可用原型所需的核心能力：

- 角色之间的数据隔离
- 历史文章上传和保存
- 根据角色历史文章生成写作画像
- 中文小语料场景下的混合检索
- 对检索得分进行解释
- 使用 MMR 避免参考文章过度重复
- 自动生成、审稿和有限轮次重写
- 对没有依据的数字和事实进行约束
- 保存用户反馈和生成记录
- 支持 OpenAI、DeepSeek 和 Mock 模式
- 具备基础单元测试

这些能力说明项目已经完成“能生成”的阶段，下一步应该进入“生成结果可判断、可审核、可持续改进”的阶段。

---

## 3. 当前核心缺点

## 3.1 缺少客观评测，无法证明版本是否变好

当前审稿结果主要是 `PASS` 或 `REVISE`。这种结果适合控制单次写作流程，但不适合产品评估。

目前无法稳定回答：

- 新版本检索是否比旧版本更准确？
- 修改提示词后，人物风格是否更接近？
- DeepSeek 和 OpenAI 哪个更适合当前角色？
- `top_k=4` 是否优于 `top_k=6`？
- 自动重写究竟提高了哪项质量？
- 某次升级是否破坏了原本正常的案例？

如果没有固定样本、评分标准和阈值，产品改进只能依赖主观感觉。

### 改进方案

在项目内部建立一套轻量评测模型，不直接绑定某个外部评测框架。

每个评分至少包含：

```text
metric_name   指标名称
value         0～1 分数
threshold     通过阈值
passed        是否通过
reason        评分原因
evaluator     规则、人工或模型名称
version       评分标准版本
```

第一版只实现五项指标：

| 指标 | 说明 | 第一版实现方式 |
|---|---|---|
| 检索相关性 | 检索文章是否适合当前任务 | 人工标注相关文章 ID，计算 Precision@K |
| 事实有据性 | 内容是否出现资料之外的数字和事实 | 本地规则检查 + 模型审稿 |
| 人物风格 | 是否符合角色画像和历史表达 | 固定评分提示词，输出 0～1 |
| 平台合规 | 是否符合小红书内容结构 | 长度、标题、段落、标签等规则检查 |
| 人工接受度 | 用户是否接受或需要大改 | 审批结果和编辑比例 |

### 有效性验证

- 先人工制作 20 条评测案例，不追求大规模数据集。
- 每次修改检索权重、提示词或模型后运行同一批案例。
- 核心分数下降超过设定范围时，版本不得直接替换当前默认配置。
- 保存每次评测使用的模型、参数、提示词版本和代码提交号。

---

## 3.2 自动审稿不等于人工批准

当前 Agent 可以自动判断内容是否通过，但社交媒体内容最终会公开影响用户形象。模型判断通过，并不代表用户允许发布。

目前还缺少：

- 待审核内容列表
- 人工通过和拒绝
- 用户直接编辑成稿
- 修改前后差异
- 被拒绝的具体原因
- 发布状态

### 改进方案

增加一个简单的内容状态机：

```text
DRAFT
  → AUTO_REVIEWED
  → PENDING_REVIEW
  → APPROVED / REJECTED
  → PUBLISHED
```

新增人工审核记录：

```text
run_id
action          approve / reject / edit
content_before
content_after
reason
created_at
```

第一版只需要提供：

1. 待审核内容列表
2. 查看初稿、终稿、检索依据和自动审稿意见
3. 编辑内容
4. 通过或拒绝

暂时不做自动发布。用户审核后手动复制到小红书，风险更低，也更容易上线。

### 有效性验证

- 所有生成内容必须进入 `PENDING_REVIEW`，不能自动标记为已发布。
- 能完整还原人工编辑前后的文本。
- 能统计一次通过率、拒绝率和平均编辑比例。
- 人工修改后的文本可以转化为后续反馈，但不能未经确认直接污染角色画像。

---

## 3.3 运行记录粒度过粗，无法定位问题发生在哪一步

当前生成记录已经保存请求、检索结果、初稿、终稿和审稿结果，这是良好的基础。但这些信息仍以一次运行的大字段为主。

当内容质量不好时，难以快速区分：

- 用户任务写得不清楚
- 检索到了错误文章
- 角色画像不准确
- 写作提示词有问题
- 自动审稿没有发现问题
- 重写反而使内容变差

### 改进方案

增加轻量的 `run_steps`，不引入完整 OpenTelemetry：

```text
retrieve
build_context
draft
review_1
revise_1
review_2
final
```

每一步保存：

```text
run_id
step_name
input_json
output_json
model
prompt_version
duration_ms
token_usage
status
error_message
created_at
```

这样一次模型调用完成后，可以在不重新消耗 Token 的情况下重新运行新的评分器。

### 有效性验证

- 任意生成记录都能看到完整步骤顺序。
- 评分程序可以直接读取旧记录重新评分，不调用写作模型。
- 失败时能够确定是检索失败、模型失败还是格式解析失败。
- 能统计单次生成耗时、调用次数和大致成本。

---

## 3.4 RAG 可解释，但检索质量没有经过数据验证

当前检索结合字符 n-gram TF-IDF、关键词、平台、语言、语气、真实性和时效性，并使用 MMR 保持多样性。这套方案对小规模中文文章库具有低成本、可解释的优势。

但当前的 `semantic_score` 实际是 TF-IDF 相似度，不是真正的 embedding 语义相似度。遇到“含义相同但用词不同”的文章时，可能无法正确召回。

同时，现有权重属于合理的工程初始值，还没有评测数据证明是最佳配置。

### 改进方案

第一步不替换检索器，先建立检索评测集：

```json
{
  "id": "retrieval_001",
  "role_id": 1,
  "query": {
    "topic": "第一次做 AI Agent 的真实复盘",
    "platform": "xiaohongshu",
    "tone": "真实、克制"
  },
  "relevant_post_ids": [12, 18],
  "irrelevant_post_ids": [25]
}
```

比较以下有限方案：

1. 当前混合检索作为基线
2. 调整各项权重
3. 增加简单查询扩展，例如同义表达和角色常用词
4. 仅在前三项效果不足时，再增加 embedding 召回或 reranker

暂时不引入独立向量数据库。当前数据量可以继续使用 SQLite，embedding 也可以先保存在本地表中。

### 有效性验证

- 使用 Precision@K、Recall@K 和 MRR 比较方案。
- 新方案必须在固定案例上显著优于当前基线才启用。
- 保留每个得分组成和召回原因，不能为了语义能力失去可解释性。
- 严格按 `role_id` 过滤，任何情况下都不能跨角色召回。

---

## 3.5 提示词职责集中，改动影响难以判断

当前写作流程同时依赖角色画像、历史文章、平台、任务目标、事实边界和审稿规则。如果这些内容集中在少量大提示词里，每次修改都可能影响其他能力。

### 改进方案

把提示词拆成四类可组合、可版本化的模板：

```text
角色模板：人物身份、语气、常用结构、禁用表达
平台模板：小红书长度、标题、段落、标签和表达习惯
任务模板：写笔记、改写、生成标题、内容复用
评分模板：事实、人设、平台和整体质量
```

建议目录：

```text
prompts/
├── shared/
├── roles/
├── platforms/
├── tasks/
└── rubrics/
```

每次生成记录对应的模板名称和版本，例如：

```text
role_profile_v1
xiaohongshu_post_v1
groundedness_review_v1
```

### 有效性验证

- 修改平台规则时不需要改角色提示词。
- 每个运行记录能还原使用了哪些模板版本。
- 新旧提示词可以在同一评测集上对比。
- 提示词输出继续使用结构化 JSON，减少解析失败。

---

## 3.6 输出仍是普通文本，没有形成小红书可交付成品

当前 Agent 的主要输出是最终正文。用户实际使用小红书时，还需要自行处理标题、标签、段落结构、封面文案和卡片内容。

### 改进方案

将最终输出改成明确的数据结构：

```json
{
  "title_options": ["标题 A", "标题 B", "标题 C"],
  "body": "最终正文",
  "hashtags": ["AI Agent", "项目复盘"],
  "cover_text": "封面主标题",
  "card_outline": [
    {"page": 1, "heading": "为什么做", "body": "..."},
    {"page": 2, "heading": "遇到的问题", "body": "..."},
    {"page": 3, "heading": "最后结果", "body": "..."}
  ]
}
```

第一版只生成卡片文案，不做自动图片渲染和自动发布。这样可以直接提高用户使用效率，同时避免引入图片模板、字体、存储和发布接口等额外复杂度。

同时增加一个确定性的“机器感提示分数”，只作为写作辅助，不宣传为 AI 检测器。可检查：

- 句子长度是否过度一致
- “首先、其次、最后、综上”等连接词是否过密
- 空洞套话是否过多
- 列表结构是否滥用
- 是否缺少具体人物、地点、时间和第一人称细节

### 有效性验证

- 结构化结果可以稳定通过数据模型验证。
- 标题、正文、标签和卡片文案可以分别复制。
- 规则能指出具体问题位置，而不只是给出一个总分。
- 自动重写前后机器感提示分数有记录，达到最大轮次后必须停止。

---

## 4. 建议的最小改进版本

为保证可行性，建议只实施三个小版本。

## 4.1 版本一：评测和可观察性

### 功能范围

- 增加 `EvalCase`、`EvalScore` 数据结构
- 新增 `eval_cases`、`eval_runs`、`eval_scores` 表
- 新增 `run_steps` 表
- 建立不少于 20 条固定案例
- 支持对历史生成记录重新评分
- 输出简单的 Markdown 或 JSON 评测报告

### 完成标准

- 同一案例可以对比两个模型或两组参数。
- 评测失败能指出具体指标和原因。
- 重新评分不会再次生成文章。
- 现有测试继续通过，并新增评测单元测试。

## 4.2 版本二：人工审批和反馈闭环

### 功能范围

- 增加内容状态机
- 增加待审核列表
- 支持编辑、通过和拒绝
- 保存编辑前后文本及原因
- 统计一次通过率和编辑比例

### 完成标准

- 未经人工确认的内容不能进入 `APPROVED`。
- 每次人工操作都有时间和完整记录。
- 用户最终编辑稿可以被选择性转化为反馈。
- 不同角色的审核记录严格隔离。

## 4.3 版本三：小红书结构化成品

### 功能范围

- 输出三个候选标题
- 输出正文和标签
- 输出封面文案
- 输出至少三页卡片文案
- 增加轻量机器感规则评分
- 在审核页面展示结构化预览

### 完成标准

- 用户无需再次整理即可复制到小红书草稿。
- 每个字段都有长度和格式验证。
- 规则评分不会无限触发重写。
- 不实现自动发布，不保存小红书账号密码。

---

## 5. 明确不做的内容

为了控制项目规模，当前阶段明确不做：

- 不迁移 LangGraph 或其他大型 Agent 框架
- 不建设多 Agent 协作平台
- 不迁移 Spring Boot 或 MateClaw 技术栈
- 不建设可视化工作流画布
- 不部署 OpenTelemetry、Jaeger 等完整观测平台
- 不引入独立向量数据库集群
- 不搭建技能市场或插件系统
- 不实现跨平台自动发布
- 不自动操作小红书账号
- 不做复杂内容日历和团队权限系统
- 不承诺绕过任何 AI 检测器

这些能力并非没有价值，而是当前成本高于收益。只有在用户量、内容量或工作流复杂度确实增长后再重新评估。

---

## 6. 产品指标

第一阶段不使用点赞量作为主要成功标准，因为点赞受账号体量、发布时间和话题热度影响较大。优先关注可控指标：

| 指标 | 建议目标 |
|---|---:|
| 固定检索集 Precision@4 | 不低于当前基线，并持续记录 |
| 无依据事实通过率 | ≥ 95% |
| 结构化输出解析成功率 | ≥ 98% |
| Agent 运行成功率 | ≥ 95% |
| 人工一次通过率 | 首期记录基线，后续逐步提升 |
| 人工文本修改比例 | 首期记录基线，后续逐步下降 |
| 跨角色数据泄漏 | 0 |
| 最大重写轮次 | 不超过配置上限 |

当积累了足够发布数据后，再观察：

- 收藏率
- 评论率
- 完读或停留表现
- 不同选题和内容结构的效果

这些发布指标只能作为优化信号，不能直接覆盖事实安全、角色一致性和人工审批。

---

## 7. 风险与控制

### 7.1 LLM 评分不稳定

控制方式：固定评分提示词和模型版本；关键安全项同时使用本地确定性规则；对边界案例保留人工复核。

### 7.2 用户反馈污染角色画像

控制方式：区分“用户修改稿”“用户意见”和“确认加入角色语料”的文章。只有用户明确确认后才能成为角色长期参考。

### 7.3 竞品内容污染人物风格

控制方式：竞品资料单独存储，只用于选题和结构分析，不能进入角色事实和语气检索库。

### 7.4 为了分数而写作

控制方式：规则分数只用来发现明显问题，最终仍以用户是否接受和编辑量为准，不把所有指标简单合并成一个总分。

### 7.5 密钥和发布安全

控制方式：真实密钥只保存在被 Git 忽略的 `.env`；发布动作必须人工批准；当前阶段不保存社交平台账号密码。

---

## 8. 最终建议

当前产品最合理的方向不是继续增加 Agent 数量，而是把现有单 Agent 做得更可控、更可比较、更接近用户最终交付。

建议按照以下顺序推进：

1. 先建立评测数据和统一分数，解决“是否真的变好”。
2. 再增加运行步骤记录，解决“问题发生在哪里”。
3. 增加人工审批，解决“内容是否允许使用”。
4. 最后增加小红书结构化成品，解决“用户拿到后是否方便发布”。

这四项都能在当前 FastAPI、SQLite 和 Python 代码基础上逐步完成，不要求重写现有系统，也不依赖复杂基础设施。它们能直接提升产品的可靠性、可用性和后续迭代效率，是现阶段投入产出比最高的改进范围。

---

## 9. 缺点、反思与改进来源溯源

本节说明报告中的每项判断来自哪里，避免把外部项目的产品宣传直接当成适合本项目的技术结论。

来源分为三类：

1. **本地证据**：当前项目中能直接证明问题存在的代码或测试。
2. **外部参考**：公开 Git 仓库中提供了可借鉴方法的具体文件。
3. **本项目取舍**：结合当前 Python、FastAPI、SQLite 规模后，决定实际采用到什么程度。

所有外部链接均指向对应 GitHub 仓库中的文件或明确目录。部分项目的能力只在仓库 `README.md` 或 Release 中公开，没有稳定的单文件实现；这类来源会明确标记为“产品设计参考”，不会声称已经复用了源码。

### 9.1 缺少客观评测

#### 本地证据

- [`app/models.py`](app/models.py)：`ReviewResult` 主要表达 `PASS/REVISE`、问题和修改指令，没有统一的数值分数、阈值、评分器版本。
- [`app/agent.py`](app/agent.py)：自动审稿服务于当前生成循环，但没有独立的批量评测 runner。
- [`tests/test_agent.py`](tests/test_agent.py)：主要验证 Mock 端到端、无依据数字和角色隔离，没有固定生成数据集、模型对比和回归阈值。
- [`tests/test_retrieval.py`](tests/test_retrieval.py)：验证了中文字符特征和相关结果排序，但没有 Precision@K、Recall@K、MRR 等数据集评测。

#### 外部参考文件

- `harness/harness-evals`
  - [`src/harness_evals/core/score.py`](https://github.com/harness/harness-evals/blob/main/src/harness_evals/core/score.py)：统一分数、阈值和通过状态的来源。
  - [`src/harness_evals/core/metric.py`](https://github.com/harness/harness-evals/blob/main/src/harness_evals/core/metric.py)：指标抽象和测量接口的来源。
  - [`src/harness_evals/core/eval_case.py`](https://github.com/harness/harness-evals/blob/main/src/harness_evals/core/eval_case.py)：标准评测案例对象的来源。
  - [`src/harness_evals/core/runner.py`](https://github.com/harness/harness-evals/blob/main/src/harness_evals/core/runner.py)：批量运行指标的来源。
- `openai/openai-knowledge-retrieval`
  - [`evals/harness.py`](https://github.com/openai/openai-knowledge-retrieval/blob/main/evals/harness.py)：RAG 评测统一入口和运行组织方式的来源。
  - [`evals/rubrics.py`](https://github.com/openai/openai-knowledge-retrieval/blob/main/evals/rubrics.py)：评分标准独立管理的来源。
  - [`evals/datasets/`](https://github.com/openai/openai-knowledge-retrieval/tree/main/evals/datasets)：固定评测数据集分层的来源。
  - [`evals/metrics/`](https://github.com/openai/openai-knowledge-retrieval/tree/main/evals/metrics)：指标与业务代码分离的来源。
- `confident-ai/deepeval`
  - [`docs/guides/guides-rag-evaluation.mdx`](https://github.com/confident-ai/deepeval/blob/main/docs/guides/guides-rag-evaluation.mdx)：分开评测检索器和生成器，以及 Contextual Precision、Recall、Faithfulness 等指标的来源。
- `EleutherAI/lm-evaluation-harness`
  - [`docs/config_files.md`](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/docs/config_files.md)：用 YAML 保存模型、任务、参数和输出配置的来源。
  - [`lm_eval/evaluator.py`](https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/evaluator.py)：统一评测执行入口的来源。

#### 本项目实际采用

只借鉴 `EvalCase + Metric + Score + Runner` 四个概念，自行使用 Pydantic 和 SQLite 实现。第一版只做 20 条案例和 5 项指标，不安装完整 Harness、DeepEval 或 LM Evaluation Harness，从而避免依赖过重和评测框架锁定。

### 9.2 缺少人工审批

#### 本地证据

- [`app/models.py`](app/models.py)：审稿对象没有人工 `approve/reject/edit` 操作。
- [`app/db.py`](app/db.py)：`generation_runs` 保存生成结果，但没有人工审核事件表和发布状态历史。
- [`app/main.py`](app/main.py)：存在生成和反馈接口，但没有待审核列表、批准、拒绝、编辑接口。

#### 外部参考文件

- `langchain-ai/social-media-agent`
  - [`src/agents/curated-post-interrupt/index.ts`](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/curated-post-interrupt/index.ts)：内容生成后暂停并等待人工操作的直接参考。
  - [`src/agents/curated-post-interrupt/types.ts`](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/curated-post-interrupt/types.ts)：人工中断输入输出类型的参考。
  - [`src/agents/generate-post/generate-post-state.ts`](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/generate-post/generate-post-state.ts)：生成流程状态对象的参考。
  - [`src/agents/generate-post/generate-post-graph.ts`](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/generate-post/generate-post-graph.ts)：把生成节点和状态流转连接起来的参考。
- `mateaix/mateclaw`
  - [`README.md`](https://github.com/mateaix/mateclaw/blob/dev/README.md)：敏感动作经过 approval gate、内容先进入草稿再由人确认的产品设计参考。

#### 本项目实际采用

不采用 LangGraph 中断机制，也不复制 MateClaw 的企业审批系统。只在现有 SQLite 中增加状态字段和 `review_actions` 表，在 FastAPI 中增加待审核、编辑、通过、拒绝四类接口。第一版不接入自动发布。

### 9.3 运行记录粒度过粗

#### 本地证据

- [`app/db.py`](app/db.py)：`generation_runs` 将请求、检索结果、初稿、终稿和审稿结果保存在一次运行记录中，没有独立步骤表。
- [`app/agent.py`](app/agent.py)：`retrieve → draft → review → revise` 在代码中是明确步骤，但每一步没有独立耗时、模型、Token、错误和提示词版本记录。

#### 外部参考文件

- `agentevals-dev/agentevals`
  - [`README.md`](https://github.com/agentevals-dev/agentevals/blob/main/README.md)：从已保存 OpenTelemetry Trace 反复评分、不重新执行 Agent 的思想来源。
  - [`samples/helm.json`](https://github.com/agentevals-dev/agentevals/blob/main/samples/helm.json)：一次实际 Agent Trace 样本的结构参考。
  - [`samples/eval_set_helm.json`](https://github.com/agentevals-dev/agentevals/blob/main/samples/eval_set_helm.json)：轨迹对应 Golden 预期的参考。
- `langchain-ai/agentevals`
  - [`python/agentevals/trajectory/match.py`](https://github.com/langchain-ai/agentevals/blob/main/python/agentevals/trajectory/match.py)：统一轨迹匹配入口的参考。
  - [`python/agentevals/trajectory/strict.py`](https://github.com/langchain-ai/agentevals/blob/main/python/agentevals/trajectory/strict.py)：严格步骤匹配的参考。
  - [`python/agentevals/trajectory/subset.py`](https://github.com/langchain-ai/agentevals/blob/main/python/agentevals/trajectory/subset.py)：必须包含关键步骤但允许额外步骤的参考。
  - [`python/agentevals/trajectory/superset.py`](https://github.com/langchain-ai/agentevals/blob/main/python/agentevals/trajectory/superset.py)：限制多余步骤的参考。
  - [`python/agentevals/trajectory/unordered.py`](https://github.com/langchain-ai/agentevals/blob/main/python/agentevals/trajectory/unordered.py)：不要求顺序的步骤集合匹配参考。

#### 本项目实际采用

只增加轻量 `run_steps` 表，不部署 OpenTelemetry、Jaeger、LangSmith 或轨迹 UI。现有步骤数量少且固定，SQLite 足以支持问题定位和离线重新评分。等未来真正出现联网研究、图片生成和发布工具链后，再评估标准 Trace。

### 9.4 RAG 检索质量未经验证

#### 本地证据

- [`app/retrieval.py`](app/retrieval.py)：当前综合 TF-IDF、关键词、元数据、真实性和时效性，并使用 MMR，但权重是工程初始值，没有基于固定数据集选择。
- [`app/retrieval.py`](app/retrieval.py)：字段名为 `semantic_score`，实际计算来自字符 n-gram TF-IDF 余弦相似度，并非 embedding 语义向量。
- [`tests/test_retrieval.py`](tests/test_retrieval.py)：只证明简单相关案例能够排在前面，不能证明真实角色语料中的整体召回质量。

#### 外部参考文件

- `openai/openai-knowledge-retrieval`
  - [`evals/datasets/`](https://github.com/openai/openai-knowledge-retrieval/tree/main/evals/datasets)：检索问题和期望依据形成固定数据集的来源。
  - [`evals/generator/`](https://github.com/openai/openai-knowledge-retrieval/tree/main/evals/generator)：从已有资料辅助生成评测问题的参考。
  - [`evals/graders/`](https://github.com/openai/openai-knowledge-retrieval/tree/main/evals/graders)：评分器与检索实现分离的参考。
  - [`evals/reporters/`](https://github.com/openai/openai-knowledge-retrieval/tree/main/evals/reporters)：评测结果报告层的参考。
- `confident-ai/deepeval`
  - [`docs/guides/guides-rag-evaluation.mdx`](https://github.com/confident-ai/deepeval/blob/main/docs/guides/guides-rag-evaluation.mdx)：使用 Contextual Precision、Recall、Relevancy 和 Faithfulness 分层评测 RAG 的来源。

#### 本项目实际采用

先保留当前检索器作为基线，手工标注 20 条任务对应的相关文章 ID，计算 Precision@K、Recall@K 和 MRR。只有查询扩展、权重调整或 embedding 在同一数据集上稳定提升后才启用；当前不引入独立向量数据库。

### 9.5 提示词职责集中、版本难以追踪

#### 本地证据

- [`app/agent.py`](app/agent.py)：角色画像、历史参考、反馈、任务、事实边界、平台要求和输出格式在 Agent 调用阶段组合，但没有独立模板注册表和版本记录。
- [`app/db.py`](app/db.py)：生成记录没有明确保存每个角色、平台、任务和评分模板的版本号。

#### 外部参考文件

- `langchain-ai/social-media-agent`
  - [`src/agents/generate-post/prompts/examples.ts`](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/generate-post/prompts/examples.ts)：把少样本写作示例独立保存的参考。
  - [`src/agents/generate-post/prompts/index.ts`](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/generate-post/prompts/index.ts)：集中导出提示词模块的参考。
  - [`src/agents/generate-post/prompts/prompts.langchain.ts`](https://github.com/langchain-ai/social-media-agent/blob/main/src/agents/generate-post/prompts/prompts.langchain.ts)：结构化组织生成提示词的参考。
- `blacktwist/social-media-skills`
  - [`AGENTS.md`](https://github.com/blacktwist/social-media-skills/blob/main/AGENTS.md)：每个能力使用独立 `SKILL.md`、包含输入、步骤、输出和版本的规范来源。
  - [`skills/social-media-context-sms/SKILL.md`](https://github.com/blacktwist/social-media-skills/blob/main/skills/social-media-context-sms/SKILL.md)：把身份、受众、语气、禁用表达和平台偏好保存为共享上下文的参考。
- `WesleySmits/agent-skills`
  - [`.agent/skills/brand-voice-guide-generator/SKILL.md`](https://github.com/WesleySmits/agent-skills/blob/main/.agent/skills/brand-voice-guide-generator/SKILL.md)：声音维度、常用词、禁用词、正反例和渠道差异的参考。
  - [`.agent/skills/content-calendar-planner/SKILL.md`](https://github.com/WesleySmits/agent-skills/blob/main/.agent/skills/content-calendar-planner/SKILL.md)：内容主题与发布计划独立于写作模板的产品方法参考。

#### 本项目实际采用

不把运行时改造成 Agent Skill 市场。只把提示词拆为 `shared/roles/platforms/tasks/rubrics` 五类文本模板，并在生成记录中保存模板名和版本。角色画像仍由当前数据库管理，不复制外部项目的品牌问卷和全部营销流程。

### 9.6 输出没有形成小红书可交付成品

#### 本地证据

- [`app/agent.py`](app/agent.py)：核心结果以 `final_text` 为主，没有稳定输出标题候选、标签、封面文字和卡片页结构。
- [`app/models.py`](app/models.py)：没有小红书成品的数据模型和字段级验证。
- [`app/main.py`](app/main.py)：没有成品预览或按字段复制所需的接口结构。

#### 外部参考文件

- `mateaix/mateclaw`
  - [`README.md`](https://github.com/mateaix/mateclaw/blob/dev/README.md)：Content Studio 的 Topic、Research、Draft、Illustrate、De-AI、Layout、Deliver 七阶段，以及小红书卡片、预览、合规和内容日历的产品设计来源。
  - [`Releases`](https://github.com/mateaix/mateclaw/releases)：`xhs_note`、至少三张 3:4 卡片、`xhs_package` 校验和确定性 `ai_trace_score` 的公开说明来源。这里属于产品设计和行为说明，不作为源码复用依据。
- `WesleySmits/agent-skills`
  - [`.agent/skills/content-repurposing-engine/SKILL.md`](https://github.com/WesleySmits/agent-skills/blob/main/.agent/skills/content-repurposing-engine/SKILL.md)：把同一份内容重组为不同渠道交付格式的方法参考。
  - [`.agent/skills/brand-voice-guide-generator/SKILL.md`](https://github.com/WesleySmits/agent-skills/blob/main/.agent/skills/brand-voice-guide-generator/SKILL.md)：保持人物声音不变、按渠道调整语气和格式的参考。

#### 本项目实际采用

第一版只输出结构化标题、正文、标签、封面文案和三页卡片文案，再增加确定性机器感提示规则。不做 HTML 转图片、模板市场、内容日历、自动发布和账号集成。这样能够直接提升交付效率，同时不扩大到图片渲染和平台自动化工程。

### 9.7 十个参考仓库的采用结论

| 仓库 | 主要参考文件 | 本项目采用程度 | 原因 |
|---|---|---|---|
| `langchain-ai/social-media-agent` | `generate-post-graph.ts`、`generate-post-state.ts`、`curated-post-interrupt/index.ts`、`prompts/` | 部分采用 | 学习审批状态和提示词分层，不迁移 LangGraph |
| `harness/harness-evals` | `core/score.py`、`metric.py`、`eval_case.py`、`runner.py` | 重点采用概念 | 最适合补齐当前评测对象和阈值 |
| `agentevals-dev/agentevals` | `README.md`、`samples/helm.json`、`samples/eval_set_helm.json` | 部分采用 | 学习保存一次、反复评分，不部署完整 OTEL |
| `openai/openai-knowledge-retrieval` | `evals/harness.py`、`rubrics.py`、`datasets/`、`metrics/` | 重点采用结构 | 直接对应当前 RAG 缺少数据集和报告的问题 |
| `confident-ai/deepeval` | `guides-rag-evaluation.mdx` | 采用指标思想 | 先建立内部数据模型，未来再考虑适配库 |
| `langchain-ai/agentevals` | `trajectory/match.py`、`strict.py`、`subset.py` 等 | 少量采用 | 当前不是复杂工具 Agent，只需要步骤断言 |
| `mateaix/mateclaw` | `README.md`、Releases | 采用产品形态 | 学习小红书交付和审批，不复制大型 Java 平台 |
| `blacktwist/social-media-skills` | `AGENTS.md`、`social-media-context-sms/SKILL.md` | 部分采用 | 学习能力、上下文和版本分层 |
| `WesleySmits/agent-skills` | `brand-voice-guide-generator/SKILL.md`、`content-calendar-planner/SKILL.md` | 少量采用 | 只取品牌声音和渠道结构，不扩展完整营销套件 |
| `EleutherAI/lm-evaluation-harness` | `docs/config_files.md`、`lm_eval/evaluator.py` | 少量采用 | 学习版本化配置和可复现 runner，不接入通用模型基准框架 |

### 9.8 溯源结论

本报告中的缺点首先来自当前项目代码，而不是因为外部项目拥有更多功能就判定我们落后。外部仓库只用于寻找经过实践的解决方式。

最终采用原则是：

- 能直接解决当前问题才采用。
- 能在现有 Python、FastAPI、SQLite 中实现才采用。
- 能通过固定案例或人工操作数据验证才采用。
- 只采用必要的数据结构和流程，不复制对方的完整技术栈。
- 产品说明与源码实现分开标记，不能把 Release 宣传等同于可复用代码。
