# 霁肤 · Jiderma 医生辅助决策与病例报告工作台

面向基层医生的本地隐私保护皮肤病灶辅助分析、风险核验与病例报告工作台。

> 本系统仅用于辅助筛查和分级转诊，不构成医学诊断。

霁肤将成熟的本地视觉能力、确定性分级策略、本地知识检索、隐私出境治理和可交互 Agent 组织为医生可使用的病例工作流。DermFM、MCP 协议本身均不是本项目的模型或协议创新。

## 医生工作台

系统访问必须先登录。当前版本采用单一医生工作流，不再提供患者/医生界面切换：

```text
医生登录 → 患者建档 → 上传病灶图像 → 辅助分析与症状核验
        → 脱敏结构化信息进入可选 LLM → 本地回填身份信息
        → 在线编辑报告 → 报告正文与输入图像关联归档
```

- 患者姓名、门诊号、联系方式、原始图像和本地路径不会发送给云端模型。
- LLM 只能返回固定的结构化报告字段，最终报告正文由本地模板生成。
- 报告库支持搜索、打开、在线编辑、保存版本、下载和安全删除。
- 删除报告时保留患者病例和原始输入图像，避免误删医疗记录。
- 当前医生账号已经初始化在本地 SQLite 中；全新数据库可通过 `.env.example` 中的 `JIDERMA_ADMIN_*` 变量初始化。

## 架构原则

```text
Decision Plane（不可被 LLM 改写）
Image -> Vision Provider -> Baseline Risk -> Red-Flag Escalation -> Case State

Interaction Plane
User -> Iterative Retrieval Agent -> MCP ToolRegistry -> Medical Dense Retriever
                  |                                      |
          PrivFlow EgressGuard                        Evidence
                  |                                      |
             Mock / Cloud LLM <--------------------------+
```

- Decision Plane 负责安全关键结果；最终风险为视觉基线与明确红旗规则中的较高等级。
- 云模型只能在本地白名单问题中排序追问，不诊断、不开药、不修改视觉分数、不决定分级。
- 二次校准同时保留视觉原始分级与结合症状后的分级，后者只能维持或上调风险。
- MCP 是 Agent 与本地能力之间的标准工具接口，不提高医疗准确率。
- REST API 与 MCP Tools 共用 Service Layer，不复制视觉或分诊逻辑。

## V2 业务路径

Care Pathway 仅有四级：

- `RETAKE`：图像质量不足，重新拍摄。
- `LOCAL_REVIEW`：未提示明确高风险模式，由基层医生继续评估。
- `REFERRAL`：建议皮肤专科进一步鉴别。
- `PRIORITY_REFERRAL`：值得优先排除恶性或其他高风险病变，但不等于确诊。

当前 Demo 使用冻结 DermFM-Zero 图像编码器和本地 HAM 监督线性头。质量 `< 0.4` 为 `RETAKE`；任务头低于拒识阈值时进入人工复核；Top-1 为 melanoma/BCC/SCC 时为 `PRIORITY_REFERRAL`；Top-1 为 actinic keratosis 时为 `REFERRAL`；其余为 `LOCAL_REVIEW`。任务头分数经过温度缩放，但仍不等于临床确诊概率。

## MCP-native Tool Orchestration

官方 Python MCP SDK 暴露 6 个本地 Tool：

- `get_visual_evidence`
- `get_triage_result`
- `search_guideline`
- `get_care_pathway`
- `get_privacy_report`
- `get_contextual_assessment`

Tool 输出若要进入 Cloud LLM，必须先通过 `EgressGuard`。bytes、`data:image/`、图片 base64、本地图片路径和图像对象序列化都会被 P0 规则拦截并记入审计。

## 结构化症状二次校准

图片分析完成后，页面会引导用户填写病程、疼痛、瘙痒、发热、快速扩散和系统性红旗症状。本地 RAG 检索指南后，可由云模型对预定义问题排序；云端不会收到原始图片。用户回答后，本地 `visual-baseline-redflag-v2` 规则按 `R_final = max(R_visual, R_redflag)` 生成二次分级和 RAG 引用。结果可通过 REST、MCP 和悬浮对话 Agent 共享。

## 本地 RAG 与公开示例

本地 RAG 使用结构化章节切块、动态病例查询和轻量医学 Dense Retrieval，直接保留必要 Top-K。召回结果按风险、鉴别、检查、转诊、冲突和信息缺口组织，并绑定文档、机构、年份、章节、页码/网页位置和版本；低于阈值时明确返回“当前知识库证据不足”。Dense 不可用时才启用词项重叠的本地降级，不再默认堆叠 BM25、RRF 或多重精排。本地医学嵌入实体权重位于 `weights/rag/IlhaEmbed/`（约 147 MB，Apache-2.0）。

`data/public_examples/isic/` 保存 5 张来自 ISIC Archive 官方 API 的 CC-0 示例图，共约 1 MB；完整来源、许可证与校验值见该目录的 `manifest.json`。模型审计、覆盖、冒烟测试与任务头训练见 `docs/视觉模型与训练.md`。

## 本地运行

依赖已安装在 `dermaguard` Conda 环境，冻结视觉 Provider 使用独立的 `dermfm-zero` 环境。一键启动：

```bash
cd '/media/lu/CE387FD6387FBC51/科研项目/医疗agent'
bash scripts/run_mock_demo.sh
```

然后打开：

- Streamlit UI: <http://127.0.0.1:8501>
- FastAPI Docs: <http://127.0.0.1:8000/docs>

### 悬浮智能助手

聊天助手默认收起，仅在页面右下角显示圆形按钮。点击后打开独立浮窗，不占用或挤压病例分析页面。桌面端支持拖拽、缩放、最小化；移动端自动变为底部弹窗。

浮窗支持：

- 智谱 GLM、Groq GPT-OSS 120B/20B、Groq Qwen3.8 27B 和 Gemini Flash 模型目录；未配置密钥的模型会显示为不可用。
- 切换模型时保留当前病例的对话上下文，前端只发送受控模型标识，由后端白名单统一分发。
- 支持“简明回答 / 详细归因”双档；详细归因会组合视觉、分级、症状校准、动态 RAG 和照护路径证据。
- 每轮回答可展开查看 MCP 工具、调用耗时、PrivFlow 检查结果和实际解释模型。
- 本地保存和滚动加载病例聊天历史、清空历史、复制回答及 Cypher 代码块。
- 深浅色切换、请求加载动画、错误提示、Enter 发送与 Shift+Enter 换行。
- 回答逐字呈现；所有云端请求继续经过 MCP 工具取数和 PrivFlow 出境检查。

Mock Chat 不需要额外的大模型账号或 API Key，但仍需登录霁肤医生工作台。对话、报告和病例接口使用同一登录会话。

### 智谱模型（当前启用）

当前 `.env` 已选择账户赠送额度所覆盖的 `glm-5.3-flash`：

```dotenv
DERMAGUARD_CHAT_PROVIDER=zhipu_glm
ZHIPUAI_API_KEY=你的本地密钥
ZHIPUAI_MODEL=glm-5.3-flash
```

请求使用智谱官方 `https://open.bigmodel.cn/api/paas/v4/chat/completions` 端点。遇到短时限流时最多重试 3 次；仍失败则自动切换为本地模拟解释，不影响视觉和分级主流程。

若账户中的赠送额度到期，可在 `.env` 中将 `ZHIPUAI_MODEL` 改回官方免费模型 `glm-4.7-flash`；实际额度、有效期与扣费顺序以智谱控制台为准。

### 可选的 Groq 免费接口

先在 Groq Console 注册、创建项目和 API Key，并在 Data Controls 中开启零数据保留。密钥只写入本机 `.env`，不要发到聊天或提交到 Git：

```bash
cp .env.example .env
chmod 600 .env
```

编辑 `.env`：

```dotenv
DERMAGUARD_CHAT_PROVIDER=groq
GROQ_API_KEY=你在本机保存的密钥
GROQ_MODEL=openai/gpt-oss-120b
GROQ_REASONING_EFFORT=low
GROQ_MAX_TOKENS=1400
```

前端可在 `openai/gpt-oss-120b`、`openai/gpt-oss-20b` 和预览型
`qwen/qwen3.8-27b` 之间切换，对话上下文保留。免费档的准确限额以
Groq Console 的 Limits 页面为准。

然后重新运行 `bash scripts/run_mock_demo.sh`。云端提供方只能收到经过 PrivFlow 检查的结构化文本，不会收到原始图片、本地路径或患者身份信息。

## MCP Server

stdio 服务器独立启动：

```bash
cd '/media/lu/CE387FD6387FBC51/科研项目/医疗agent'
bash scripts/run_mcp_server.sh
```

其标准输出是 MCP JSON-RPC 通道，不是交互式命令行。

## 测试

```bash
cd '/media/lu/CE387FD6387FBC51/科研项目/医疗agent'
/home/lu/miniforge3/envs/dermaguard/bin/python -m pytest backend/tests/v2 -q
/home/lu/miniforge3/envs/dermfm-zero/bin/python -m pytest tests/test_dermfm_provider.py -q
```

V2 E2E 覆盖上传、质量检测、视觉 Service、分级、RAG、Care Pathway、三类问答、Tool Trace、PrivFlow、Cloud Payload 和审计。测试中使用注入的确定性视觉 runner 保证可重复；真实 DermFM 单图集成可通过 UI 或 API 运行。

## 数据与权重

- SQLite 只保存结构化结果、脱敏对话、Tool Call 和 Audit，不保存图片 BLOB。
- 图片保存于 `data/cases/{case_id}/`，数据库仅保存本地路径与 SHA-256。
- 冻结权重实体文件：`weights/DermFM-Zero-Open/open_clip_pytorch_model.bin`。
- 当前 HAM 示例工作流实际加载监督任务头：`artifacts/training/ham7_linear_head/ham7_linear_head.pt`。
- 本地医学嵌入实体权重：`weights/rag/IlhaEmbed/model.safetensors`。

## 目录

```text
backend/app/care/          CarePathway Provider 与 schemas
backend/app/contextual/    结构化症状与二次校准 schemas
backend/app/chat/          有限轮次检索 Agent 与 Mock Provider
backend/app/mcp/           MCP Server、ToolRegistry 和 6 个 Tools
backend/app/services/      REST/MCP 共用 Service Layer 与 PrivFlow
backend/app/knowledge/     本地分级转诊知识
backend/tests/v2/          单元、MCP smoke、安全与 E2E 测试
ui/streamlit_app.py        Local Edge Web UI
src/dermfm_provider.py     冻结视觉 Provider（V2 未修改）
weights/                   本地永久权重（不入 Git）
```
