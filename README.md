# 霁肤 · Jiderma

面向基层医生的皮肤病灶辅助决策与病例报告工作台。系统将病灶图像、患者自然语言描述、本地多模态分类、风险分级、本地医学知识检索、受约束 Agent 和报告归档组织为一条完整工作流。

> 本系统用于辅助筛查、医学资料检索和转诊决策参考，不替代医生诊断或病理检查。

## 当前工作流

```text
医生登录
  → 创建患者病例并填写自然语言描述
  → PrivFlow 脱敏与固定字段抽取
  → 医生确认结构化临床信息
  → 病灶图像 + 临床文本进入本地多模态模型
  → 输出疾病 Top-3 与本地风险等级
  → Agent 通过 MCP 检索本地医学知识库
  → 医生查看可追溯证据并综合判断
  → LLM 生成结构化报告字段
  → 本地回填患者身份信息
  → 在线编辑、保存和归档报告
```

系统采用单一医生工作台，必须登录后使用。患者姓名、联系方式、原始图像和本地文件路径不会发送给云端模型；云模型只接收通过 PrivFlow 检查的脱敏结构化文本。

## 系统结构

```text
Streamlit 医生工作台
        ↓ REST
FastAPI 业务服务
        ├─ 病例、认证与报告管理（SQLite）
        ├─ 本地多模态 Provider
        ├─ 确定性风险与照护路径
        ├─ 本地医学 RAG
        └─ 受约束检索 Agent
                  ↓
             MCP ToolRegistry
        ┌─────────┼─────────┐
   病例证据    指南检索    隐私检查
        └─────────┼─────────┘
             Mock / 云端 LLM
```

核心边界：

- 本地多模态模型负责生成候选结果，LLM 不修改或重排 Top-3。
- 风险等级和照护路径由本地确定性逻辑产生，LLM 无权下调风险。
- LLM 主要负责固定字段抽取、检索规划、证据整理和报告语言生成。
- REST API 与 MCP Tools 共用 Service Layer，不复制业务逻辑。
- Dense Retriever 或云端 LLM 不可用时，系统具有本地降级路径。

## 本地动态 RAG 与 Agent

病例分析阶段会根据医生描述、Top-3、阳性症状、风险等级和检索主题自动构造动态 Query，检索本地结构化医学资料。结果按照风险、鉴别、检查、转诊、冲突和信息缺口组织，并保留文档、机构、年份、章节、页面位置和版本信息。

ChatBox 使用有限轮次的 ReAct 风格检索 Agent：

```text
理解医生问题
  → 判断证据缺口
  → 生成检索 Query
  → 调用 search_guideline MCP Tool
  → 检查证据是否充分
  → 必要时改写 Query 再检索
  → 基于证据生成回答
```

本地 Dense Retrieval 使用 `weights/rag/IlhaEmbed/` 中的轻量医学文本编码器。Dense 不可用时自动退化为本地词法检索。低于阈值的结果会标记为“当前知识库证据不足”，不会要求 LLM 自行补充医学事实。

MCP Server 提供 5 个本地工具：

- `get_visual_evidence`
- `get_triage_result`
- `search_guideline`
- `get_care_pathway`
- `get_privacy_report`

工具输出在进入云端前必须通过 EgressGuard；图片字节、Base64、本地路径和患者身份字段会被阻止并写入审计记录。

## PAD-UFES-20 多模态实验

当前业务视觉 Provider 使用冻结的图像与文本编码器，将 RGB 临床图像和经医生确认的 PAD 格式病例文本融合后输出候选结果。实现复用 DermFM-Zero 官方组件，不修改 `third_party/DermFM-Zero`：

```text
224×224 RGB 图像 → 冻结视觉编码器 ───────┐
                                         ├→ 官方融合模块 → 分类头 → 6 类概率
结构化信息 → PAD Prompt → 冻结文本编码器 ─┘
```

三种实验模式使用作者提供的同一组 `train.csv / val.csv / test.csv`，不自行重新划分：

| 模式 | 最佳轮次 | Accuracy | Balanced Accuracy | Macro-F1 |
|---|---:|---:|---:|---:|
| `image_only` | 17 | 0.8000 | 0.7080 | 0.7253 |
| `text_only` | 20 | 0.6957 | 0.5714 | 0.5911 |
| `image_text` | 30 | **0.8348** | **0.8402** | **0.8040** |

最佳 checkpoint 由验证集 Macro-F1 选择，测试集仅在模型选定后评估。作者划分存在跨集合患者 ID 重复，因此该结果用于验证 MVP 链路和同划分模式比较，不直接代表独立患者泛化性能。

训练：

```bash
bash scripts/train_pad_multimodal_mvp.sh \
  --mode all --epochs 30 --batch-size 4 \
  --accumulation-steps 8 --precision bf16 --device cuda
```

单样本推理：

```bash
bash scripts/infer_pad_multimodal_mvp.sh \
  --image data/pad_ufes20/images/PAT_980_1849_295.png \
  --metadata examples/pad_patient_example.json \
  --model-checkpoint artifacts/training/pad_multimodal_mvp/image_text/best.pt \
  --device cuda
```

实验结果、预测 CSV、混淆矩阵、训练曲线、日志与 checkpoint 保存在 `artifacts/training/pad_multimodal_mvp/`。

## HAM10000 视觉线性头归档

项目保留早期视觉 Encoder 下游实验，用于复现冻结视觉特征上的轻量任务头训练；它不属于当前 Web 推理链。

- 冻结视觉 Encoder，只训练 `Linear(768, 7)`。
- 官方下游划分：训练 8,012、验证 500、测试 1,503。
- 可训练参数：5,383。
- 测试 Accuracy：89.29%。
- 测试 Balanced Accuracy：79.34%。
- 测试 Macro-F1：80.98%。

代码和结果：

- `src/dermfm_provider.py`：视觉特征提取。
- `scripts/train_dermfm_linear_head.py`：任务头训练。
- `scripts/visualize_training_results.py`：从日志重绘结果。
- `artifacts/training/ham7_linear_head/`：权重、日志、配置、特征缓存和测试结果。

## 启动项目

依赖环境：

- `dermaguard`：FastAPI、Streamlit、RAG、Agent 与报告服务。
- `dermfm-zero`：本地多模态 Provider 和训练推理。

所有直接依赖已集中在根目录 `requirements.txt`。该文件通过 Python
版本标记适配现有两个环境：Python 3.10+ 安装 Web/API/MCP 依赖，
Python 3.9 安装上游兼容的模型训练依赖。

```bash
conda run -n dermaguard python -m pip install -r requirements.txt
conda run -n dermfm-zero python -m pip install -r requirements.txt
```

一键启动网站：

```bash
cd '/media/lu/CE387FD6387FBC51/科研项目/医疗agent'
bash scripts/run_mock_demo.sh
```

访问地址：

- Streamlit：<http://127.0.0.1:8501>
- FastAPI 文档：<http://127.0.0.1:8000/docs>

独立启动 MCP stdio Server：

```bash
bash scripts/run_mcp_server.sh
```

MCP 标准输出是 JSON-RPC 通道，因此直接运行后安静等待属于正常状态。

## 云端模型配置

不配置 API Key 时可以使用本地 Mock。启用云端模型时，只将密钥保存在本机 `.env`，不要提交到 Git：

```bash
cp .env.example .env
chmod 600 .env
```

支持的 Provider 和模型白名单以 `.env.example` 及 ChatBox 模型列表为准。所有云端请求仍需经过 PrivFlow 和 EgressGuard。

## 测试

```bash
/home/lu/miniforge3/envs/dermaguard/bin/python -m pytest backend/tests/v2 -q
/home/lu/miniforge3/envs/dermfm-zero/bin/python -m pytest tests/test_pad_multimodal_mvp.py -q
```

后端测试覆盖登录与报告、自然语言字段抽取、多模态 Service、风险分级、RAG、Care Pathway、Agent、MCP、隐私出境和端到端业务链。多模态测试使用独立环境验证 Prompt、融合模型和推理接口。

## 目录说明

```text
backend/app/                 FastAPI 业务代码
  api/                       登录与业务接口
  chat/                      检索 Agent 和 LLM Provider
  database/                  SQLite 模型与仓储
  knowledge/rag_documents/  本地医学知识库
  mcp/                       MCP Server、Registry 与 Tools
  services/                  业务服务、RAG 与隐私治理
backend/tests/v2/            后端与 MCP 测试
ui/                          Streamlit 工作台和 ChatBox
pad_multimodal_mvp/          PAD 多模态训练及推理实现
scripts/                     启动、训练、推理与绘图入口
src/dermfm_provider.py       HAM7 实验视觉特征 Provider
artifacts/training/          训练日志、指标、图表与 checkpoint
data/                        本地数据库、病例和数据集
weights/                     本地模型实体权重
third_party/DermFM-Zero/     官方上游代码
```

`backend/app/knowledge/rag_documents/*.md` 是运行时知识库数据，`third_party/DermFM-Zero/**/README.md` 属于上游源码说明；它们不是重复的项目文档，不应删除。
