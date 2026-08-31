# 本地未上传改动对比与审核报告

## 1. 对比基线与结论

- GitHub 仓库：`Arvinhh7/SocialPostEditor`
- 远端基线：`origin/main`，提交 `6fba32f`（`feat: build personalized social writing RAG agent`）
- 本地状态：所有改动仍在工作区，尚未提交、尚未上传
- 审核结论：核心链路可运行，数据库旧版本可迁移，人工审批和评测边界有效；适合进入下一次提交前整理

旧版解决的是“能够按角色检索并生成内容”；本地新版进一步解决“生成过程可追踪、结果可评测、自动审核不可冒充人工批准、审核失败不会错误放行”。

## 2. 核心变化对比

| 模块 | GitHub 旧版 | 本地新版 | 修改原因 |
|---|---|---|---|
| 生成流程 | 检索后直接生成，结束时一次性保存 | `retrieve → contract → draft → review/revise → final` 逐步保存 | 失败时能定位具体环节，避免整次运行信息丢失 |
| 事实边界 | `proof_points` 只存在于任务和 Prompt | 新增 Evidence Contract，统一必写点、数字依据、禁用词、角色规则、参考文章和阈值 | 让 Draft、Reviewer、Revision 使用同一验收边界 |
| Reviewer | 与 WritingAgent 混在同一类；解析失败可能降级为 PASS | 独立只读 Reviewer；异常、空输出、非法结论统一 `BLOCKED` | 生成者不能给自己兜底放行，审核故障不能被当作内容合格 |
| 人工审批 | 自动审稿结束即保存，没有人工状态机 | `PENDING_REVIEW → APPROVED / REJECTED`，支持 EDIT、diff 和动作历史 | 公开内容必须由人最终确认 |
| 运行记录 | 只保存请求、检索、初稿、终稿和总审核结果 | 每步保存输入、输出、模型、Prompt 版本、耗时、状态、错误 | 支持定位回归和离线复盘 |
| 评测 | 无固定案例、指标和版本比较 | 增加 Eval Case、Eval Run、Eval Score 和多运行对比 | 修改 RAG 权重或 Prompt 后可以用同一基准判断是否变好 |
| 失败状态 | 主要是 PASS/REVISE，调用异常直接抛出 | 增加 `FAILED` 与 `BLOCKED`，两者均不可审批 | 区分执行失败与审核无法完成 |
| 测试 | 6 个测试 | 35 个测试 | 覆盖失败轨迹、审批状态机、数据库迁移、评测与 Reviewer 异常 |

## 3. 文件级修改与原因

- `app/agent.py`：增加 Evidence Contract、逐步轨迹、失败落盘、独立 Reviewer 调用和 `BLOCKED` 分支。原因是旧版只能看到最终结果，无法判断错误发生在哪一步。
- `app/reviewer.py`：新增无数据库权限的只读 Reviewer。原因是旧版审核和生成耦合，格式解析失败时存在错误放行风险。
- `app/db.py`：增加运行步骤、人工审核动作、评测案例/运行/分数，以及旧库增量迁移。原因是需要可审计、可比较、可恢复的数据基础。
- `app/evals/metrics.py`：增加检索 Precision/Recall/MRR、数字事实支持度和小红书结构规则。原因是减少只依赖 LLM 主观评分。
- `app/evals/runner.py`：只读取已保存的完整生成结果进行评分，不重新生成内容。原因是评测必须可重复且不额外消耗模型费用。
- `app/evals/reporting.py`：比较同一案例、同一指标版本下的多次运行。原因是防止把不同口径的分数错误比较。
- `app/main.py`：增加评测、审批队列和审核动作接口。原因是把新能力暴露为可实际操作的 API。
- `app/models.py`：增加 Evidence Contract、评测与人工审核数据模型。原因是约束输入、状态和指标范围。
- `tests/`：新增审批、评测 API、评测规则、Reviewer 和数据库迁移测试。原因是保护状态机和关键边界。
- `README.md`：补充运行轨迹、人工审批、评测和接口说明。原因是让代码行为与使用文档一致。
- `PRODUCT_IMPROVEMENT_REPORT.md`：记录改进来源、当前缺点和小步实施路线，属于设计依据，不参与运行。

## 4. 各 Agent/组件当前运行逻辑

### 4.1 Profile Agent

1. 读取当前 `role_id` 下真实性不低于 4 的历史文章。
2. 最多选取 30 篇样本，文章内容截断后交给模型。
3. 只总结中英文价值观、语气、开头、节奏、CTA 和避用表达，不推测身份经历。
4. 每次重建生成新的画像版本，并记录样本文章 ID。

### 4.2 RAG Retriever

1. 只读取当前角色的文章，保持角色数据隔离。
2. 查询由主题、格式、语气、目标、受众、平台和语言组成。
3. 混合分数保持旧版算法：字符 n-gram TF-IDF 60%、关键词 18%、元数据 14%、真实性 6%、时效性 2%。
4. 元数据内部继续比较平台、语言、内容格式和语气。
5. 使用 MMR：相关性 82%、重复惩罚 18%，避免近似文章占满全部位置。
6. 返回每个分数组成和命中原因；本次没有引入向量数据库或 embedding。

RAG 排序算法本身没有改动，变化发生在“如何使用和验证检索结果”：参考文章 ID 被写入 Evidence Contract 和运行轨迹；历史文章被明确限定为风格与判断参考，不自动成为事实依据；新增固定相关文章 ID 的 Precision@K、Recall@K、MRR 评测。

### 4.3 Evidence Contract Builder

1. 去重并保存 `proof_points`，形成 `required_points`。
2. 只把含数字的 proof point 记入允许数字依据。
3. 保存禁用表达、角色身份规则、平台、语言、格式和参考文章 ID。
4. 固定要求：无依据数字为 0、禁用词为 0、与单篇历史文章的整体相似度不超过 0.72。
5. 合同由本地规则生成，不增加模型调用。

### 4.4 Draft Agent

1. 接收任务、角色、画像、RAG 文章、相关人工反馈和 Evidence Contract。
2. 历史文章只学习判断方式、节奏和语气，不允许逐句仿写。
3. 不允许增加合同之外的数字、客户、案例、结果或亲历。
4. 输出正文后立即把调用结果、模型、Prompt 版本和耗时写入运行轨迹。

### 4.5 Independent Reviewer

1. 先接收本地确定性问题：无依据数字、禁用词、复制风险和正文过短。
2. 再由只读模型审核角色一致性、任务完成度、模板感、事实、宣传强度和 CTA。
3. 本地确定性问题优先级高于模型；模型返回 PASS 也不能覆盖规则问题。
4. 有问题返回 `REVISE`；无问题返回 `PASS`。
5. 模型失败、空输出、非法 JSON、非法 verdict 或模型自行返回 BLOCKED 时，由程序生成可信的 `BLOCKED`。
6. Reviewer 不持有数据库和人工审批权限，不能修改正文或批准发布。

### 4.6 Revision Agent

1. 只在 Reviewer 返回 `REVISE` 时运行。
2. 只修复列出的问题，保留原稿中合格的观点和语气。
3. 继续受同一 Evidence Contract 约束，不得在改稿时引入新事实。
4. 最多执行配置允许的重写轮数；`PASS` 或 `BLOCKED` 都会停止循环。

### 4.7 Deterministic Eval Runner

1. 只评测已保存且状态为 PASS/REVISE 的完整生成，不评测 FAILED/BLOCKED 半成品。
2. 根据人工标注的相关文章 ID 计算 Precision@K、Recall@K 和 MRR。
3. 按数字 token 精确检查正文数字是否出现在 proof points 中，避免旧版字符串包含判断的误放行。
4. 小红书结构评分读取真实生成正文，而不是 expected_data 中的示例：标题 1–40 字、正文 80–2000 字、至少两段、1–10 个标签，四项通过三项即达 0.75 阈值。
5. 比较功能只允许同一 Eval Case、同一指标集合和版本，输出相对基线差值。

### 4.8 Human Approval

1. PASS 或达到最大改稿轮数后的 REVISE 内容进入 `PENDING_REVIEW`。
2. 人可以 EDIT、APPROVE 或 REJECT；每次操作保存修改前后文本、diff、原因和时间。
3. 编辑已批准内容会重新进入待审核。
4. REJECTED、FAILED、BLOCKED 内容不能直接批准；被拒绝内容不能通过 EDIT 绕过拒绝状态。
5. 当前系统仍不自动发布社交媒体内容。

## 5. 审核中发现并修复的问题

1. 小红书评测曾可能读取期望示例正文，造成生成内容很差但结构分仍通过；已改为只评分真实 `final_text`。
2. REJECTED 内容曾可通过 EDIT 重新进入待审核；已收紧状态转换。
3. 模型自行返回 `BLOCKED` 曾可能被后处理改成 PASS；已改为程序控制的阻塞结论。
4. FAILED/BLOCKED 生成曾可进入离线评测；已限制为只评测完整输出。
5. 新增旧版数据库迁移测试，确认旧终稿不会丢失，并正确进入待审核状态。

## 6. 测试与安全结果

- 单元测试：35 项通过
- 端到端 Mock 冒烟：通过，画像、RAG、生成、审核和保存完整跑通
- Python 编译检查：通过
- FastAPI OpenAPI 构建：通过，25 条路由、12 个 Schema
- `git diff --check`：通过
- `.env`：本地和 GitHub 均未被 Git 跟踪，且受 `.gitignore` 保护
- API Key 扫描：未在待上传代码和文档中发现疑似明文密钥
- 未执行真实 OpenAI/DeepSeek 在线调用，避免产生费用；上线前仍应单独进行一次受控 live smoke test

## 7. 仍未解决的限制

- Reviewer 已实现程序权限隔离，但当前仍与 Draft 共用同一模型供应商，尚未验证异构模型复核收益。
- 人工反馈仍会作为高真实性示例参与后续检索，尚未实现 Candidate/Admitted/Rejected 经验准入。
- RAG 的“语义分”仍是字符 n-gram TF-IDF，不是真正 embedding；应先积累固定评测集，再决定是否升级。
- 当前确定性评测覆盖检索、数字事实和小红书结构，尚未实现稳定的人物风格评分与人工接受度统计。
- 运行步骤记录模型、Prompt 和耗时，但尚未记录 token 与估算费用。
- 当前只有 `role_id` 隔离，没有用户登录和租户授权，不适合直接作为多用户公网服务。

## 8. 上传前建议

建议把本批改动作为一个可回滚的功能提交，提交信息可使用：

```text
feat: add evidence-bound review, evals, traces, and human approval
```

提交前无需继续扩大功能范围；下一步应优先实现反馈经验准入，避免未经确认的单次人工修改长期影响后续生成。
