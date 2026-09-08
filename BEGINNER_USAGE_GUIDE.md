# 个性化社交媒体写作 Agent 零基础使用手册

适用版本：当前 GitHub `main` 分支

适用人群：第一次接触 Python、API、RAG 或 Agent 的用户

这份手册按“安装环境、确认能运行、创建角色、投喂文章、生成内容、人工审核、持续改进”的顺序编写。第一次使用时，建议严格按顺序操作。

## 你最终会得到什么

运行成功后，你可以：

1. 为不同账号创建独立角色。
2. 批量上传过去写过的 PDF、TXT 或 Markdown 文章。
3. 自动分析历史文章并建立个人写作画像。
4. 根据主题和事实要点生成符合个人风格的社交媒体内容。
5. 在发布前进行规则审核和人工审批。
6. 用反馈逐步改善后续生成效果。

系统不会替你自动发布内容。最终稿必须经过人工确认，这样更安全。

## 先认识几个概念

### 角色

角色代表一个账号或一种写作身份。例如“我的小红书账号”“公司公众号”“个人 LinkedIn”。每个角色都有独立的身份规则、默认生成参数、历史文章和写作画像。

### RAG

RAG 会在你生成新内容前，从历史文章中找出相关且可信的内容片段，作为写作风格和表达习惯的参考。

历史文章用于参考风格，不应被当作新内容的事实来源。新文章里的事实、数据和结论应通过 `proof_points` 提供。

### Agent

Agent 会依次完成参数合并、历史文章检索、内容生成、规则审核、必要时改写、保存结果和等待人工审批。

### Swagger 页面

Swagger 是项目自带的网页操作界面。你不需要先学习编程，也可以在浏览器里调用所有功能。

## 第一部分 准备 Windows 环境

### 安装 Git

从 Git 官方网站安装 Git for Windows：

`https://git-scm.com/download/win`

安装完成后，重新打开 PowerShell，然后输入：

```powershell
git --version
```

如果能看到版本号，说明 Git 已安装成功。

### 安装 Python

建议安装 Python 3.11 或更高版本：

`https://www.python.org/downloads/windows/`

安装时请勾选 `Add Python to PATH`。安装完成后，重新打开 PowerShell并输入：

```powershell
python --version
```

如果能看到 Python 版本号，说明安装成功。

### 下载项目

打开 PowerShell，依次执行：

```powershell
cd C:\alignment\social
git clone https://github.com/Arvinhh7/SocialPostEditor.git
cd SocialPostEditor
```

如果项目已经下载过，不要再次克隆。进入项目目录后执行：

```powershell
git pull
```

### 创建虚拟环境

虚拟环境用于隔离项目依赖，避免影响电脑上的其他 Python 项目。

```powershell
python -m venv .venv
```

后续命令直接使用虚拟环境中的 Python，这样即使 PowerShell 不允许激活脚本，也能正常运行：

```powershell
.\.venv\Scripts\python.exe --version
```

### 安装项目依赖

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

第一次安装需要联网。等待命令结束，并确认最后没有红色错误信息。

### 创建环境配置文件

```powershell
Copy-Item .env.example .env
```

`.env` 是本机配置文件，可能包含 API 密钥。它不应该上传到 GitHub。

## 第二部分 先用 Mock 模式确认项目能运行

Mock 模式不会调用真实大模型，也不会消耗 API 额度。第一次运行必须先用它测试环境。

打开 `.env`，确认第一行是：

```text
LLM_MODE=mock
```

### 运行自动测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

看到 `OK` 表示自动测试通过。

### 运行快速冒烟测试

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_test
```

这个命令会快速检查角色、文章、画像、检索、生成和反馈等核心流程。

### 启动服务

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

看到类似下面的信息表示服务已启动：

```text
Uvicorn running on http://127.0.0.1:8000
```

这个 PowerShell 窗口需要保持打开。停止服务时按 `Ctrl+C`。

### 打开网页操作界面

在浏览器打开：

`http://127.0.0.1:8000/docs`

也可以打开健康检查地址：

`http://127.0.0.1:8000/health`

在 Swagger 页面中调用接口的统一方法是：

1. 找到需要的接口并点击展开。
2. 点击 `Try it out`。
3. 填写参数或 JSON。
4. 点击 `Execute`。
5. 在 `Response body` 查看结果。

## 第三部分 可选配置真实大模型

只有 Mock 测试成功后，才建议切换真实模型。

### 使用 DeepSeek

在 `.env` 中填写：

```text
LLM_MODE=live
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=在这里填写你的新密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

### 使用 OpenAI

在 `.env` 中填写：

```text
LLM_MODE=live
LLM_PROVIDER=openai
OPENAI_API_KEY=在这里填写你的新密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.6-luna
```

模型名称必须是你的账号当前可以使用的模型。如果模型不存在或没有权限，请改成服务商控制台显示的可用模型。

修改 `.env` 后，需要停止服务并重新启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

安全要求：

- 不要把 API 密钥写进 README、代码或截图。
- 不要把 `.env` 上传到 GitHub。
- 如果密钥曾公开出现，应立即在服务商后台删除并创建新密钥。
- 调试时不要打印完整密钥。

## 第四部分 完整使用流程

推荐按下面的顺序操作：

1. 创建角色。
2. 批量上传历史文章。
3. 检查并修正自动识别的信息。
4. 重建写作画像。
5. 测试检索结果。
6. 生成新内容。
7. 人工审批最终稿。
8. 提交反馈并决定是否准入。

## 创建角色

在 Swagger 找到 `POST /roles`，点击 `Try it out`，填写：

```json
{
  "name": "我的个人账号",
  "description": "用于分享 AI 产品实践的个人账号",
  "identity_rules": "定位：分享真实、可操作的 AI 产品实践。必须：先说明问题，再给出具体做法；保持自然、克制、诚实。禁止：夸大效果、编造数据、使用绝对化承诺。",
  "default_generate_params": {
    "platform": "xiaohongshu",
    "audience": "刚开始学习 AI 工具的职场人",
    "tone": "真诚、清晰、实用",
    "banned_phrases": [
      "百分百有效",
      "无脑冲"
    ],
    "candidates": 1
  }
}
```

执行成功后，记录返回结果中的 `id`。后面所有操作中的 `role_id` 都要使用这个数字。

角色默认参数的作用是减少重复填写。生成时只填写主题和事实要点，系统会自动补上角色的默认平台、受众、语气和禁用词。请求中显式填写的参数会覆盖角色默认值。

如果新账号和已有角色的规则相似，可以调用 `POST /roles/{role_id}/clone`。克隆会复制身份规则和默认生成参数，但不会复制历史文章和写作画像。

## 批量投喂历史文章

### 上传前准备

目前支持 PDF、TXT 和 MD 文件。建议一篇文章一个文件，文件名尽量包含平台、日期或主题，例如：

```text
2026-08-小红书-AI工作流复盘.md
2026-07-公众号-产品迭代总结.txt
```

批量上传限制：

- 每批最多 30 个文件。
- 单个文件最多 10 MB。
- 每批总大小最多 50 MB。

### 执行批量上传

在 Swagger 找到 `POST /posts/bulk-upload`，填写：

- `files`：选择一个或多个文件。
- `role_id`：刚才记录的角色编号。
- `platform`：可选；留空时系统会尝试自动识别。
- `language`：通常填写 `zh-CN`。
- `content_type`：可选，例如 `经验分享`。
- `topic`：可选。
- `tone`：可选。
- `authenticity`：建议先填写 `4`。

系统会自动提取文本、切分内容、推断部分元数据、去重，并返回成功、跳过和失败清单。

`authenticity` 表示这篇文章能多大程度代表你现在的真实风格：

| 分数 | 含义 | 建议用途 |
|---|---|---|
| 5 | 非常代表当前风格 | 优先作为画像和检索参考 |
| 4 | 比较代表当前风格 | 普通历史文章推荐值 |
| 3 | 有一定参考价值 | 可以保存，但默认不用于画像重建 |
| 1 至 2 | 已过时或不代表本人 | 仅留档，不建议用于生成参考 |

### 检查和纠错

自动识别可能出错，上传后应检查平台、主题、语气和真实性评分。

- 修改一篇文章：`PATCH /posts/{post_id}`。
- 同时修改多篇文章：`PATCH /posts/bulk`。

批量修改示例：

```json
{
  "post_ids": [11, 12, 13],
  "role_id": 2,
  "changes": {
    "platform": "wechat",
    "tone": "专业、克制"
  }
}
```

## 重建写作画像

历史文章上传并纠错后，在 Swagger 调用：

`POST /profile/rebuild?role_id=你的角色编号`

画像重建会选取当前有效且真实性评分达到要求的历史文章，提取常用结构、语气、表达偏好和应避免的习惯。当前默认最多分析 30 篇代表性文章。

以下情况建议重新构建画像：

- 第一次上传完历史文章。
- 新增了一批高质量文章。
- 批量修改了平台、语气或真实性评分。
- 写作风格发生了明显变化。

使用 `GET /profile?role_id=你的角色编号` 可以查看当前画像。

## 测试 RAG 检索

正式生成前，可以先调用 `POST /retrieve` 检查系统找到了哪些历史文章。

```json
{
  "role_id": 2,
  "topic": "第一次使用 AI Agent 时容易踩的坑",
  "platform": "xiaohongshu",
  "top_k": 4
}
```

把示例中的 `role_id` 改成你自己的角色编号。

重点检查返回结果中的：

- 命中的历史文章是否与主题相关。
- `reason` 是否合理。
- 文章是否仍代表当前写作风格。
- 是否命中了已经过时的内容。

如果某篇文章不应该被参考，可以在生成记录创建后通过检索反馈标记为不相关；如果它以后都不应参与检索，可以将文章设为停用。

## 生成新内容

在 Swagger 调用 `POST /generate`。

角色已经配置默认参数时，最小请求可以很简单：

```json
{
  "role_id": 2,
  "topic": "第一次使用 AI Agent 时容易踩的三个坑",
  "proof_points": [
    "先用 Mock 模式确认流程，避免一开始消耗模型额度",
    "历史文章只负责风格参考，事实要点由用户明确提供",
    "生成结果需要人工审批后才能使用"
  ]
}
```

如果要临时覆盖角色默认值，可以增加字段：

```json
{
  "role_id": 2,
  "topic": "第一次使用 AI Agent 时容易踩的三个坑",
  "platform": "linkedin",
  "audience": "AI 产品经理",
  "tone": "专业、简洁",
  "banned_phrases": ["颠覆行业"],
  "candidates": 2,
  "proof_points": [
    "先验证流程再连接真实模型",
    "事实与风格必须分开管理"
  ]
}
```

系统按下面的优先级确定最终参数：

1. 系统默认值。
2. 角色默认值。
3. 本次请求中显式填写的值。

返回结果中的 `effective_request` 会显示真正生效的参数。遇到“为什么这次语气不一样”时，先检查它。

### 生成过程内部发生了什么

1. 合并系统、角色和请求参数。
2. 读取当前角色的写作画像。
3. 检索与本次主题相关的历史文章。
4. 把画像、检索片段和事实要点交给写作 Agent。
5. 审核 Agent 检查身份规则、禁用词、事实边界和风格要求。
6. 如果结果需要修改，系统在允许轮数内自动改写。
7. 保存最终候选稿、检索依据、审核意见和改写记录。
8. 将可用结果放入人工审批列表。

常见审核状态：

- `PASS`：自动审核通过。
- `REVISE`：经过改写后仍有需要人工注意的地方。
- `BLOCKED`：缺少关键事实或存在不能安全生成的问题。
- `FAILED`：模型调用或程序执行失败。

自动审核通过不等于已经发布。它只代表可以进入人工审批。

## 人工审批

调用下面的接口查看待审核内容：

`GET /review-inbox?role_id=你的角色编号&status=PENDING_REVIEW&limit=100&offset=0`

列表中会直接显示审核摘要，例如改写轮数和主要原因。选中一个候选稿后，记录它的 `run_id`。

### 直接通过

调用 `POST /generations/{run_id}/review-actions`：

```json
{
  "action": "APPROVE",
  "reason": "事实和表达均已人工确认"
}
```

### 人工修改后通过

```json
{
  "action": "EDIT",
  "edited_text": "把你人工修改后的完整最终稿放在这里",
  "reason": "调整开头并删除过度承诺"
}
```

### 拒绝

```json
{
  "action": "REJECT",
  "reason": "选题方向不合适，需要重新生成"
}
```

使用 `GET /generations/{run_id}` 可以查看完整生成记录，包括检索内容、每轮审核意见和人工操作历史。

## 提交写作反馈

如果人工修改体现了值得长期学习的写作习惯，可以调用 `POST /feedback` 保存反馈。

```json
{
  "role_id": 2,
  "task_summary": "写一篇第一次使用 AI Agent 的避坑文章",
  "draft": "粘贴系统生成的原稿",
  "final_text": "粘贴人工确认后的完整终稿",
  "reason": "开头应直接说明实际问题，减少铺垫",
  "similarity_rating": 4
}
```

新反馈默认是 `CANDIDATE`，不会立刻改变后续生成。这样可以避免一次偶然修改污染长期风格。

确认反馈值得长期使用后，调用：

`POST /feedback/{feedback_id}/admission`

```json
{
  "action": "ADMIT",
  "reason": "这是稳定、可重复使用的写作偏好"
}
```

不适合长期学习时选择 `REJECT`。候选反馈很多时，可以使用 `POST /feedback/admission/bulk` 批量处理。

只有 `ADMITTED` 反馈会参与后续生成。

## 纠正错误检索

如果某次生成引用了一篇不相关的历史文章，调用：

`POST /generations/{run_id}/retrieval-feedback`

```json
{
  "post_id": 11,
  "action": "NOT_RELEVANT",
  "reason": "文章属于旧业务方向，与本次主题无关"
}
```

`NOT_RELEVANT` 会记录本次负反馈，但不会自动删除历史文章。

如果某篇文章已经过时，并且以后都不应该参与检索，可以调用：

`POST /posts/{post_id}/retrieval-status`

```json
{
  "action": "RETIRE",
  "reason": "账号定位已经改变"
}
```

需要恢复时使用 `RESTORE`。这种设计让重要操作可追踪，也避免误删数据。

## 每次生成的推荐操作清单

1. 确认服务正在运行。
2. 选择正确的 `role_id`。
3. 写清楚主题和目标受众。
4. 在 `proof_points` 中提供所有必须准确的事实。
5. 先看 `effective_request` 是否符合预期。
6. 检查命中的历史文章是否相关。
7. 阅读最终稿和审核摘要。
8. 人工修改或批准。
9. 只把稳定、有价值的反馈设为 `ADMITTED`。

## 常见问题排查

| 问题 | 常见原因 | 解决方法 |
|---|---|---|
| `python` 不是可识别命令 | Python 未安装或未加入 PATH | 重新安装 Python 并勾选 Add Python to PATH，然后重开 PowerShell |
| 无法激活 `.venv` | PowerShell 脚本策略限制 | 不必激活，直接使用 `.\.venv\Scripts\python.exe` 执行命令 |
| 安装依赖失败 | 网络问题或 pip 版本旧 | 检查网络，再执行 `.\.venv\Scripts\python.exe -m pip install --upgrade pip` |
| 浏览器打不开 8000 端口 | 服务未启动或已退出 | 回到 PowerShell 重新运行 uvicorn 命令并保持窗口打开 |
| API 返回 422 | JSON 字段缺失或类型错误 | 对照 Swagger 的 Schema 检查字段名、引号、逗号和数字类型 |
| 真实模型返回 401 | API 密钥错误或失效 | 在服务商后台创建新密钥，更新 `.env` 后重启服务 |
| 真实模型返回模型不存在 | 模型名称无权限或已变化 | 使用服务商控制台列出的可用模型名称 |
| 检索不到文章 | 角色不一致、文章已停用或数据太少 | 检查 `role_id`，确认文章状态，并重新构建画像 |
| 生成风格不像本人 | 代表性文章太少或真实性评分不合适 | 补充高质量历史文章，修正元数据和评分，再重建画像 |
| 生成内容事实不准确 | 把历史文章误当成事实来源 | 把准确事实明确写入 `proof_points`，并进行人工审核 |
| 修改 `.env` 后没变化 | 服务仍在使用旧配置 | 按 `Ctrl+C` 停止服务，再重新启动 |

## 数据和安全

项目默认使用 SQLite，数据库文件位于：

```text
data/voice.db
```

建议定期备份这个文件。备份前先停止服务，避免复制到一半时数据库正在写入。

不要把以下文件提交到公开仓库：

- `.env`
- `data/voice.db`
- 含个人隐私或客户机密的原始文章
- 调试日志中的密钥和完整敏感内容

上传 GitHub 前可以执行：

```powershell
git status
git ls-files .env
```

如果第二条命令没有输出，说明 `.env` 当前没有被 Git 跟踪。

## 常用命令速查

### 更新代码

```powershell
git pull
```

### 安装依赖

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 运行测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

### 运行冒烟测试

```powershell
.\.venv\Scripts\python.exe -m scripts.smoke_test
```

### 启动服务

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

### 停止服务

在运行服务的 PowerShell 窗口按 `Ctrl+C`。

## 核心接口速查

| 目标 | 接口 |
|---|---|
| 检查服务 | `GET /health` |
| 创建角色 | `POST /roles` |
| 克隆角色 | `POST /roles/{role_id}/clone` |
| 批量上传文章 | `POST /posts/bulk-upload` |
| 批量修正文章 | `PATCH /posts/bulk` |
| 重建画像 | `POST /profile/rebuild` |
| 查看画像 | `GET /profile` |
| 测试检索 | `POST /retrieve` |
| 生成内容 | `POST /generate` |
| 查看待审批内容 | `GET /review-inbox` |
| 审批或人工编辑 | `POST /generations/{run_id}/review-actions` |
| 查看完整生成记录 | `GET /generations/{run_id}` |
| 提交写作反馈 | `POST /feedback` |
| 批量准入反馈 | `POST /feedback/admission/bulk` |
| 标记错误检索 | `POST /generations/{run_id}/retrieval-feedback` |
| 停用或恢复历史文章 | `POST /posts/{post_id}/retrieval-status` |

## 第一次成功运行的判断标准

如果下面几项都完成，就说明系统已经跑通：

1. 自动测试显示 `OK`。
2. 冒烟测试执行完成且没有报错。
3. 浏览器可以打开 `/docs` 和 `/health`。
4. 能创建角色并获得 `role_id`。
5. 能上传文章并重建画像。
6. `/retrieve` 能返回相关历史内容。
7. `/generate` 能返回候选稿和 `run_id`。
8. 候选稿能在 `/review-inbox` 中看到并完成审批。

完成这些步骤后，再逐步增加真实文章、切换真实模型和积累人工反馈。不要一开始就导入大量资料；先用三至五篇代表性文章验证效果，更容易发现问题。
