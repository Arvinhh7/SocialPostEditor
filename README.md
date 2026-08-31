# 个性化社交媒体写作 Agent

这是根据《个性化社交媒体写作 Agent：Python + RAG 项目入门指南》实现的可运行 MVP。它把角色隔离、历史语料检索、双语作者画像、事实边界、生成、独立评审、定向改写和人工反馈串成一条完整链路。

项目支持两种运行模式和两个在线供应商：

- `mock`：默认模式，不需要 API Key，不访问网络，用于跑通接口、数据库、RAG 和反馈闭环。
- `live`：根据 `LLM_PROVIDER` 选择 `deepseek` 或 `openai`。
- DeepSeek 使用 OpenAI 兼容的 Chat Completions；OpenAI 使用 Responses API。

## 快速运行

建议使用 Python 3.11 或更高版本。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.cli demo
uvicorn app.main:app --reload
```

打开 `http://127.0.0.1:8000/docs`，即可在 Swagger 页面操作全部接口。

项目会自动读取工作目录中的 `.env`。也可以用终端环境变量临时覆盖文件配置：

```powershell
$env:LLM_MODE="live"
$env:LLM_PROVIDER="openai"
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_MODEL="gpt-5.6-luna"
uvicorn app.main:app --reload
```

切换到 DeepSeek：

```powershell
$env:LLM_MODE="live"
$env:LLM_PROVIDER="deepseek"
$env:DEEPSEEK_API_KEY="你的 API Key"
$env:DEEPSEEK_MODEL="deepseek-v4-flash"
uvicorn app.main:app --reload
```

如果只想验证程序，不设置任何 Key，保持 `LLM_MODE=mock` 即可。`.env` 已被 `.gitignore` 排除，不能提交到版本库。

## 第一次完整操作

1. `GET /roles`：确认内置角色 `Alignment AI｜GEO 品牌传播` 的 `role_id` 为 `2`。
2. `POST /posts`：逐条导入历史文章；或用 `POST /posts/upload` 上传 PDF、TXT、Markdown。
3. `POST /profile/rebuild?role_id=2`：用真实性为 4–5 的文章生成双语作者画像。
4. `POST /retrieve`：先观察当前任务会取回哪些文章以及每个分数分量。
5. `POST /generate`：生成 1–3 个候选版本，并完成评审和最多两轮定向修改。
6. 本人修改后调用 `POST /feedback`：保存初稿、终稿和修改原因。
7. 后续生成会检索最相关的反馈案例，避免每次把所有修改历史都塞进上下文。

## 生成运行轨迹

每个候选内容从开始生成时就会创建运行记录。`GET /generations/{run_id}` 除了返回检索结果、初稿、审稿和终稿，还会返回按顺序排列的 `steps`：

```text
retrieve → contract → draft → review_1 → revise_1 → review_2 → final
```

每一步包含输入摘要、输出、模型供应商、模型名称、提示词版本、耗时、状态和错误信息。若模型在初稿、审稿或重写阶段失败，运行状态会保存为 `FAILED`，已经完成的步骤和具体失败步骤不会丢失。

`contract` 是程序在写稿前生成的 Evidence Contract，记录本次内容的必写事实、允许出现的数字依据、禁用表达、角色规则、参考文章 ID 和确定性验收阈值。历史文章在合同中被明确限定为“只用于风格与判断方式”，不会自动成为事实来源。Draft、Reviewer 和 Revision 使用同一份合同，合同本身不调用模型。

Reviewer 是独立的只读组件，不持有数据库和人工审批权限。审核模型调用失败、返回空内容或无法解析完整结论时，生成状态会变成 `BLOCKED`，审批状态为 `NOT_APPLICABLE`；系统不会把审核故障降级成 `PASS`，也不会在缺少有效审核结论时继续改稿。

当前轨迹直接保存在 SQLite 中，没有引入 OpenTelemetry 或外部观测平台，适合现阶段固定且较短的 Agent 工作流。

## 人工审批闭环

自动审稿的 `PASS/REVISE` 与人工审批状态相互独立。成功生成后，内容进入：

```text
PENDING_REVIEW → APPROVED
               → REJECTED
```

- `GET /review-inbox?role_id=2`：查看当前角色的待审核内容。
- `POST /generations/{run_id}/review-actions`：编辑、批准或拒绝内容。
- `GET /generations/{run_id}/review-actions`：查看不可覆盖的人工操作历史。

编辑示例：

```json
{
  "action": "EDIT",
  "edited_text": "人工修改后的完整正文",
  "reason": "减少模板表达，补充真实语气"
}
```

批准示例：

```json
{
  "action": "APPROVE",
  "reason": "事实与语气已确认"
}
```

拒绝必须填写原因：

```json
{
  "action": "REJECT",
  "reason": "缺少事实依据，需要重新生成"
}
```

每个动作都会保存操作前文本、操作后文本和统一 diff。编辑已批准内容会使其重新进入 `PENDING_REVIEW`；失败的生成记录为 `NOT_APPLICABLE`，不能进行人工审批。当前系统仍不会自动发布内容。

## 确定性评测

评测只读取已经保存的生成记录，不会重新调用 OpenAI 或 DeepSeek。基本流程：

1. `POST /eval-cases`：创建固定案例，在 `expected_data.relevant_post_ids` 中填写人工确认的相关文章 ID。
2. `POST /eval-runs`：传入案例 ID 和已有的 `generation_run_id`，执行 Precision@K、Recall@K、MRR 和数字事实评分。
3. `GET /eval-runs/{eval_run_id}`：查看各项分数、阈值、是否通过和原因。
4. `POST /eval-runs/compare`：比较同一案例、同一指标版本下的多次评测结果。

创建案例示例：

```json
{
  "role_id": 2,
  "name": "RAG 复盘检索案例",
  "input_data": {
    "topic": "第一次做 RAG 的复盘",
    "platform": "LinkedIn",
    "top_k": 4
  },
  "expected_data": {
    "relevant_post_ids": [1, 2]
  },
  "tags": ["rag", "retrieval"],
  "version": "1.0.0"
}
```

执行评测：

```json
{
  "eval_case_id": 1,
  "generation_run_id": 3
}
```

比较结果：

```json
{
  "run_ids": [1, 2]
}
```

也可以先写入内置演示语料：

```powershell
python -m app.cli seed
python -m app.cli demo
```

## 生成请求示例

```json
{
  "role_id": 2,
  "topic": "品牌能否保证在 ChatGPT 中成为第一推荐？",
  "platform": "LinkedIn",
  "language": "zh-CN",
  "format": "教育型短文",
  "goal": "澄清常见误区并建立可信度",
  "audience": "品牌市场负责人",
  "tone": "克制、教育型、基于证据",
  "length": "300-500字",
  "banned_phrases": ["绝对保证", "颠覆行业"],
  "proof_points": ["模型回答会受到问题表达、上下文和可用信息影响"],
  "cta": "邀请读者分享他们观察 AI 品牌可见性的方式。",
  "candidates": 1
}
```

`proof_points` 是硬事实白名单，不是普通参考资料。程序会先用本地规则拦截白名单之外的数字，再交给独立评审器检查虚构案例、过度承诺、模板感和角色一致性。

## 当前接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 运行状态与当前模式 |
| GET/POST | `/roles` | 查询或创建角色 |
| GET/POST | `/posts` | 查询或新增语料 |
| POST | `/posts/upload` | 上传并拆分 PDF/TXT/Markdown |
| GET | `/profile` | 查看最新作者画像 |
| POST | `/profile/rebuild` | 重建画像版本 |
| POST | `/retrieve` | 单独检查检索结果和评分解释 |
| POST | `/generate` | 执行完整写作 Agent |
| POST | `/feedback` | 保存人工终稿与修改原因 |
| GET | `/generations/{run_id}` | 查看一次生成的检索、逐步轨迹、初稿、评审与终稿 |
| GET | `/review-inbox` | 按角色和状态查看人工审核队列 |
| GET/POST | `/generations/{run_id}/review-actions` | 查看或新增编辑、批准、拒绝动作 |
| GET/POST | `/eval-cases` | 查询或创建固定评测案例 |
| GET | `/eval-cases/{eval_case_id}` | 查看评测案例详情 |
| POST | `/eval-runs` | 对已有生成记录执行确定性评测 |
| GET | `/eval-runs/{eval_run_id}` | 查看评测分数和失败原因 |
| POST | `/eval-runs/compare` | 比较同一案例的多次评测结果 |

## 验证

核心测试不需要 FastAPI 或 API Key：

```powershell
python -m unittest discover -s tests -v
$env:LLM_MODE="mock"
python -m scripts.smoke_test
```

测试覆盖中文字符 n-gram、相关语料排序、画像构建、生成—评审闭环、成功与失败运行轨迹、人工编辑/批准/拒绝、非法审批转换、未经允许的数字拦截、确定性指标、评测 API 和结果比较。

## 重要边界

- 这是写作辅助系统，不会自动发布社交媒体内容。
- 历史文章可能含过时事实；它们默认只作为风格和观点背景，不自动成为新的事实依据。
- 所有角色数据通过 `role_id` 隔离，但 MVP 没有登录与权限系统；多用户上线前必须增加租户和授权检查。
- PDF 文本提取只适用于包含文本层的 PDF；扫描件需要额外 OCR。
- 更完整的设计、权重说明、评测方案和升级路线见 [RAG_DESIGN.md](RAG_DESIGN.md)。

OpenAI 接入遵循官方当前建议，使用 [Responses API](https://developers.openai.com/api/docs/guides/responses)；Embedding 升级可参考 [Vector embeddings](https://developers.openai.com/api/docs/guides/embeddings)。
