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
| GET | `/generations/{run_id}` | 查看一次生成的检索、初稿、评审与终稿 |

## 验证

核心测试不需要 FastAPI 或 API Key：

```powershell
python -m unittest discover -s tests -v
$env:LLM_MODE="mock"
python -m scripts.smoke_test
```

测试覆盖中文字符 n-gram、相关语料排序、画像构建、生成—评审闭环、运行记录和未经允许的数字拦截。

## 重要边界

- 这是写作辅助系统，不会自动发布社交媒体内容。
- 历史文章可能含过时事实；它们默认只作为风格和观点背景，不自动成为新的事实依据。
- 所有角色数据通过 `role_id` 隔离，但 MVP 没有登录与权限系统；多用户上线前必须增加租户和授权检查。
- PDF 文本提取只适用于包含文本层的 PDF；扫描件需要额外 OCR。
- 更完整的设计、权重说明、评测方案和升级路线见 [RAG_DESIGN.md](RAG_DESIGN.md)。

OpenAI 接入遵循官方当前建议，使用 [Responses API](https://developers.openai.com/api/docs/guides/responses)；Embedding 升级可参考 [Vector embeddings](https://developers.openai.com/api/docs/guides/embeddings)。
