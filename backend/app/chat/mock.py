from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from backend.app.care.schemas import CarePathwayLevel
from backend.app.services.dermfm_candidate_sets import display_label_zh


DISCLAIMER = "本系统仅用于辅助筛查和分级转诊，不构成医学诊断。"


def is_medical_definition_question(message: str) -> bool:
    compact = re.sub(r"\s+", "", str(message))
    return any(marker in compact for marker in ("是什么", "什么意思", "介绍一下", "科普一下", "常见表现"))


def _definition_subject(message: str) -> str:
    compact = re.sub(r"[\s？?]", "", str(message))
    for marker in ("是什么", "什么意思", "介绍一下", "科普一下", "常见表现"):
        if marker in compact:
            subject = compact.split(marker, 1)[0].removeprefix("请问").removeprefix("请")
            return subject[-24:] or "这种皮肤表现"
    return "这种皮肤表现"


class ChatProvider(Protocol):
    name: str
    model: str

    def plan(self, payload: dict[str, Any], system_prompt: str) -> str: ...

    def generate(
        self,
        message: str,
        mode: str,
        tool_results: dict[str, dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        detail_level: str = "concise",
    ) -> str: ...


class MockChatProvider:
    name = "mock"
    model = "local-mock"

    def plan(self, payload: dict[str, Any], system_prompt: str) -> str:
        """离线可复现的检索决策；云端提供方使用同一 schema。"""
        message = str(payload.get("user_message", ""))
        lowered = message.lower()
        case_evidence = payload.get("case_evidence") or {}
        clinical_narrative = str(
            (payload.get("public_case_context") or {}).get("clinical_narrative") or ""
        )
        retrievals = payload.get("retrieval_observations") or []

        privacy = any(item in lowered for item in ["原始图片", "base64", "上传到云", "发给云端"])
        explain = any(item in message for item in ["为什么", "为何", "原因", "归因", "依据", "解释", "危险", "什么病", "是不是"])
        next_step = any(item in message for item in ["下一步", "怎么办", "进一步检查", "去哪里"])
        visual_only = any(item in message for item in ["候选分数", "看到了什么"])
        treatment = any(item in message for item in ["药", "治疗", "处方"])
        definition = is_medical_definition_question(message)

        if privacy:
            plan = {"intent": "privacy_question", "evidence_sufficient": True,
                    "reasoning_summary": "隐私问题使用本地审计事实，无需医学检索。"}
        elif definition:
            if retrievals:
                latest = retrievals[-1]
                sufficient = bool((latest.get("evidence_assembly") or {}).get("evidence_sufficient"))
                plan = {
                    "intent": "medical_definition",
                    "evidence_sufficient": sufficient,
                    "retrieval_query": None if sufficient else f"{_definition_subject(message)} 定义 常见表现 危险变化 权威资料",
                    "reasoning_summary": "已检查医学概念解释所需证据。",
                }
            else:
                plan = {
                    "intent": "medical_definition",
                    "retrieval_query": f"{_definition_subject(message)} 定义 常见表现 危险变化 权威资料",
                    "evidence_sufficient": False,
                    "reasoning_summary": "医学概念问题需要先检索本地权威资料。",
                }
        elif visual_only:
            plan = {"intent": "explain_visual_evidence", "evidence_sufficient": True,
                    "reasoning_summary": "当前病例证据足以解释视觉候选。"}
        else:
            if retrievals:
                latest = retrievals[-1]
                sufficient = bool((latest.get("evidence_assembly") or {}).get("evidence_sufficient"))
                plan = {
                    "intent": "evidence_review",
                    "evidence_sufficient": sufficient,
                    "retrieval_query": None if sufficient else f"{message} 权威指南 检查指征 转诊条件",
                    "reasoning_summary": "已检查本轮医学证据是否足以回答。",
                }
            else:
                visual = case_evidence.get("get_visual_evidence", {})
                triage = case_evidence.get("get_triage_result", {})
                labels = " ".join(str(item.get("label", "")) for item in visual.get("top_predictions", [])[:3])
                level = str(triage.get("level", ""))
                plan = {
                    "intent": "care_guidance" if next_step else "treatment_boundary" if treatment else "explain_triage" if explain else "general_case_question",
                    "retrieval_query": f"{message} {clinical_narrative} {labels} {level} 危险征象 鉴别 检查 转诊指南".strip(),
                    "evidence_sufficient": False,
                    "reasoning_summary": "根据当前病例状态生成一条医学检索语句。",
                }
        return json.dumps(plan, ensure_ascii=False)

    def generate(
        self,
        message: str,
        mode: str,
        tool_results: dict[str, dict[str, Any]],
        history: list[dict[str, Any]] | None = None,
        detail_level: str = "concise",
    ) -> str:
        privacy = tool_results.get("get_privacy_report")
        if privacy is not None:
            return (
                "原始病灶图片始终保留在院内本地可信环境，没有发送给云端模型；"
                "患者身份信息也没有发送。对话层只能使用经过隐私检查的结构化视觉证据和指南摘要。"
                f"{DISCLAIMER}"
            )

        triage = tool_results.get("get_triage_result", {})
        care = tool_results.get("get_care_pathway", {})
        visual = tool_results.get("get_visual_evidence", {})
        guidelines = tool_results.get("search_guideline", {}).get("chunks", [])
        clinical = visual.get("clinical_context") or {}
        level = triage.get("level") or care.get("level")

        if any(word in message for word in ["药", "治疗", "处方"]):
            return f"我不能提供用药或治疗方案。请由医生结合病史和现场检查评估。{DISCLAIMER}"

        if any(word in message.lower() for word in ["原始图片", "base64", "忽略之前", "发给云端"]):
            return f"我不能绕过 RAW_IMAGE BLOCK 隐私策略，原始医疗影像不会发送给云端模型。{DISCLAIMER}"

        if is_medical_definition_question(message):
            subject = _definition_subject(message)
            sufficient = [item for item in guidelines if item.get("evidence_status") == "充分"]
            evidence = sufficient or guidelines
            sources = list(dict.fromkeys(str(item.get("title", "本地医学资料")) for item in evidence[:3]))
            if "色素痣" in subject or "黑素细胞痣" in subject:
                answer = (
                    "色素痣就是日常常说的‘痣’，是很常见的色素性皮肤病灶。"
                    "多数普通色素痣会长期稳定，通常不需要治疗。"
                )
                warning = (
                    "如果它近期持续增大，颜色或边界明显变化，或出现瘙痒、自行出血、破溃，"
                    "建议由皮肤科医生结合病史、皮肤镜及必要时的病理检查进一步判断。"
                )
            elif evidence:
                content = re.sub(r"\s+", " ", str(evidence[0].get("content", ""))).strip()
                answer = content[:360].rstrip("，。；") + "。"
                warning = "如果表现持续变化、症状加重或与典型表现不符，建议由皮肤科医生进一步评估。"
            else:
                answer = f"当前本地知识库没有找到足够可靠的“{subject}”定义证据，我不会自行补写。"
                warning = "建议由医生结合实际皮损表现进行解释。"
            source_line = "、".join(sources) if sources else "当前知识库证据不足"
            return "\n\n".join([
                f"## {subject}是什么",
                answer,
                "## 需要注意什么",
                warning,
                f"**参考来源：** {source_line}。",
                DISCLAIMER,
            ])

        if detail_level == "detailed":
            predictions = visual.get("top_predictions", [])
            candidate_lines = [
                f"- {display_label_zh(str(item.get('label', '未知候选')))}：匹配分数 {float(item.get('score', 0)):.4f}"
                for item in predictions
            ] or ["- 当前工具未返回视觉候选。"]
            positive = [
                name for key, name in {
                    "itch": "瘙痒", "hurt": "疼痛", "bleed": "出血",
                    "grew": "近期增大", "changed": "外观变化",
                    "skin_cancer_history": "皮肤肿瘤史", "cancer_history": "其他肿瘤史",
                }.items() if clinical.get(key)
            ]
            references = [
                f"- {item.get('title', item.get('id', '未命名指南'))}（{item.get('source', '本地知识库')}）"
                for item in guidelines
            ] or ["- 当前问题没有检索到足够相关的本地指南。"]
            next_steps = care.get("recommended_next_steps", [])
            next_lines = [f"{index}. {item}" for index, item in enumerate(next_steps, 1)]
            if not next_lines:
                next_lines = [f"1. {care.get('action', '请由医生结合病史和现场检查进一步评估。')}"]
            technical = ""
            if mode == "clinician":
                technical = (
                    f"\n分级策略：`{triage.get('policy_version', 'unknown')}`；"
                    f"分级原因：`{triage.get('reason_codes', [])}`。"
                )
            return "\n".join(
                [
                    "## 直接结论",
                    f"当前本地规则分级为 **{level or '信息不足'}**。这是风险筛查和转诊建议，不是癌症确诊。{technical}",
                    "",
                    "## 视觉证据",
                    *candidate_lines,
                    "这些分数只用于当前候选集合内的相对排序，不是患病概率。",
                    "",
                    "## 结构化病例信息",
                    f"多模态分析已同时使用图像与病例信息。阳性特征：{'、'.join(positive) or '未记录阳性特征'}。",
                    "",
                    "## 本地指南依据",
                    *references,
                    "",
                    "## 不确定性与信息缺口",
                    "单张图片和视觉模型输出不能替代面诊、皮肤镜复核或必要时的病理检查；候选之间可能存在外观重叠。",
                    "",
                    "## 下一步建议",
                    *next_lines,
                    "",
                    DISCLAIMER,
                ]
            )

        if mode == "clinician":
            predictions = visual.get("top_predictions", [])
            candidates = "；".join(
                f"{display_label_zh(str(item.get('label', '未知候选')))}={float(item.get('score', 0)):.4f}"
                for item in predictions
            ) or "工具未返回候选结果"
            refs = ", ".join(str(item.get("id")) for item in guidelines) or "无"
            return (
                f"确定性 TriagePolicy 输出为 {level or '信息不足'}，"
                f"policy={triage.get('policy_version', 'unknown')}，reason_codes={triage.get('reason_codes', [])}。"
                f"本地视觉候选 Top-K：{candidates}。后续路径：{care.get('action', '信息不足')}。"
                f"指南引用：{refs}。候选分数不是校准后的患病概率，也不能替代临床诊断。{DISCLAIMER}"
            )

        if level == CarePathwayLevel.PRIORITY_REFERRAL.value:
            return (
                "本地筛查发现了需要重点排除高风险病变的视觉模式，因此建议优先转诊。"
                "这不是癌症确诊；下一步应由具备皮肤专科能力的医疗机构评估，医生可能结合皮肤镜，"
                f"并在必要时决定是否进行活检或病理检查。{DISCLAIMER}"
            )
        if level == CarePathwayLevel.REFERRAL.value:
            return (
                "当前视觉证据需要进一步专科鉴别，建议转诊至具备皮肤专科能力的医疗机构。"
                f"{care.get('action', '')}{DISCLAIMER}"
            )
        if level == CarePathwayLevel.RETAKE.value:
            return f"当前图片质量不足，建议先重新拍摄清晰、光线均匀的病灶图片。{DISCLAIMER}"
        if level == CarePathwayLevel.LOCAL_REVIEW.value:
            return (
                "当前候选结果未触发优先转诊模式，但这不代表没有疾病或无需就医。"
                f"建议由基层医生继续结合病史和现场检查评估。{DISCLAIMER}"
            )
        return f"当前工具信息不足，我无法判断该病例的分级路径。请由医生进一步评估。{DISCLAIMER}"


def chat_model_catalog() -> list[dict[str, Any]]:
    """返回前端可见的受控模型白名单；密钥和服务地址永不下发。"""
    has_zhipu = bool(os.getenv("ZHIPUAI_API_KEY"))
    has_groq = bool(os.getenv("GROQ_API_KEY"))
    has_gemini = bool(os.getenv("GEMINI_API_KEY"))
    return [
        {
            "id": "glm-5.3-flash",
            "label": "智谱 GLM-5.3-Flash",
            "available": has_zhipu,
            "status": "可用" if has_zhipu else "未配置密钥",
        },
        {
            "id": "glm-4-flash",
            "label": "智谱 GLM-4-Flash",
            "available": has_zhipu,
            "status": "可用" if has_zhipu else "未配置密钥",
        },
        {
            "id": "openai/gpt-oss-120b",
            "label": "Groq·GPT-OSS 120B",
            "available": has_groq,
            "status": "可用" if has_groq else "未配置 Groq 密钥",
        },
        {
            "id": "openai/gpt-oss-20b",
            "label": "Groq·GPT-OSS 20B",
            "available": has_groq,
            "status": "可用" if has_groq else "未配置 Groq 密钥",
        },
        {
            "id": "qwen/qwen3.8-27b",
            "label": "Groq·Qwen3.8 27B",
            "available": has_groq,
            "status": "可用（预览）" if has_groq else "未配置 Groq 密钥",
        },
        {
            "id": "gemini-flash",
            "label": "Gemini Flash",
            "available": has_gemini,
            "status": "可用" if has_gemini else "未配置密钥",
        },
    ]


def create_chat_provider(model_id: str | None = None) -> ChatProvider:
    if model_id and model_id != "auto":
        if model_id == "glm-5.3-flash":
            from backend.app.chat.zhipu import ZhipuChatProvider

            return ZhipuChatProvider(model="glm-5.3-flash")
        if model_id == "glm-4-flash":
            from backend.app.chat.zhipu import ZhipuChatProvider

            return ZhipuChatProvider(model="glm-4-flash")
        if model_id == "gemini-flash":
            from backend.app.chat.gemini import GeminiChatProvider

            return GeminiChatProvider()
        if model_id in {
            "openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"
        }:
            from backend.app.chat.groq import GroqChatProvider

            return GroqChatProvider(model=model_id)
        raise ValueError(f"不支持的模型标识：{model_id}")

    provider = os.getenv("DERMAGUARD_CHAT_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        return MockChatProvider()
    if provider == "groq":
        from backend.app.chat.groq import GroqChatProvider

        return GroqChatProvider()
    if provider in {"zhipu", "zhipu_glm", "glm"}:
        from backend.app.chat.zhipu import ZhipuChatProvider

        return ZhipuChatProvider()
    raise ValueError(f"不支持的对话提供方：{provider}")
