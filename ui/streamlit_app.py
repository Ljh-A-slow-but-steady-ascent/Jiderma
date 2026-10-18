from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
import streamlit as st

from backend.app.services.dermfm_candidate_sets import DISPLAY_LABELS_ZH, display_label_zh
from ui import visuals as V


API_URL = os.getenv("DERMAGUARD_API_URL", "http://127.0.0.1:8000")
DISCLAIMER = "本系统仅用于辅助筛查和分级转诊，不构成医学诊断。"
LEVEL_LABELS = {
    "RETAKE": "请重新拍摄",
    "LOCAL_REVIEW": "基层继续评估",
    "REFERRAL": "建议专科转诊",
    "PRIORITY_REFERRAL": "建议优先转诊",
}
LEVEL_ORDER = {"RETAKE": 0, "LOCAL_REVIEW": 1, "REFERRAL": 2, "PRIORITY_REFERRAL": 3}
DURATION_VALUES = {
    "24小时内": "within_24h",
    "1—3天": "1_3_days",
    "4—7天": "4_7_days",
    "1—4周": "1_4_weeks",
    "超过1个月": "over_month",
    "不清楚": "unknown",
}
DISEASE_LABELS = DISPLAY_LABELS_ZH
st.set_page_config(page_title="霁肤 · Jiderma 医生工作台", page_icon="霁", layout="wide")
st.markdown(V.theme_css(), unsafe_allow_html=True)


def inject(html: str, height: int = 380) -> None:
    """嵌入隔离的展示组件，并统一使用浅色主题。"""
    st.iframe(V.iframe_wrap(html), height=height)


def api(method: str, path: str, **kwargs) -> Any:
    headers = dict(kwargs.pop("headers", {}))
    token = st.session_state.get("auth_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, f"{API_URL}{path}", timeout=240, headers=headers, **kwargs)
    if not response.ok:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        raise RuntimeError(f"服务请求失败（{response.status_code}）：{detail}")
    return response.json()


for key, default in {
    "auth_token": "",
    "auth_user": None,
    "case_id": None,
    "analysis": None,
    "mode": "clinician",
    "image_bytes": None,
    "verification_plan": None,
    "contextual_assessment": None,
    "patient": None,
    "active_report": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def login_screen() -> None:
    st.markdown("<div style='height:7vh'></div>", unsafe_allow_html=True)
    left, center, right = st.columns([1, 1.15, 1])
    with center:
        st.markdown("# 霁肤 · Jiderma")
        st.caption("医生辅助决策与病例报告工作台")
        with st.form("jiderma-login"):
            username = st.text_input("账号")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录医生工作台", type="primary", width="stretch")
        if submitted:
            try:
                result = api("POST", "/v1/auth/login", json={"username": username, "password": password})
                st.session_state.auth_token = result["access_token"]
                st.session_state.auth_user = result["user"]
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
    st.stop()


if st.session_state.auth_token and not st.session_state.auth_user:
    try:
        st.session_state.auth_user = api("GET", "/v1/auth/me")
    except Exception:
        st.session_state.auth_token = ""

if not st.session_state.auth_token:
    login_screen()

with st.sidebar:
    st.markdown("### 霁肤 · Jiderma")
    st.write(f"**{st.session_state.auth_user['full_name']}**")
    st.caption("医生账号 · 本地病例工作台")
    if st.button("病例报告库", width="stretch"):
        st.switch_page("pages/1_病例报告库.py")
    if st.button("退出登录", width="stretch"):
        try:
            api("POST", "/v1/auth/logout")
        except Exception:
            pass
        st.session_state.clear()
        st.rerun()


inject(V.render_hero(), height=188)

st.markdown('<div class="dg-section-label">新建患者病例</div>', unsafe_allow_html=True)
st.caption("患者身份信息仅保存在本地，不会发送给云端模型。")
with st.container(border=True):
    p1, p2, p3, p4 = st.columns([1.25, .75, .75, 1.25])
    with p1:
        patient_name = st.text_input("患者姓名 *")
    with p2:
        patient_sex = st.selectbox("性别 *", ["男", "女", "其他"])
    with p3:
        patient_age = st.number_input("年龄 *", min_value=0, max_value=130, value=30)
    with p4:
        outpatient_no = st.text_input("患者编号 / 门诊号 *")
    p5, p6 = st.columns(2)
    with p5:
        patient_phone = st.text_input("联系方式（选填）")
        lesion_site = st.text_input("病灶部位 *", placeholder="例如：左前臂、面部")
        medical_history = st.text_area("既往史（选填）", height=76)
    with p6:
        chief_complaint = st.text_area("主诉与病程 *", height=76, placeholder="例如：发现色素性病灶约2年，近2个月增大并偶有出血")
        allergy_history = st.text_area("过敏史（选填）", height=76)

st.markdown('<div class="dg-section-label">病灶图像</div>', unsafe_allow_html=True)

st.markdown(
    '<div class="dg-upload-note"><i></i><span>支持 JPG、PNG 与 WEBP；建议使用光线均匀、对焦清晰的皮肤镜图像</span></div>',
    unsafe_allow_html=True,
)
uploaded = st.file_uploader(
    "上传皮肤病灶图像",
    type=["jpg", "jpeg", "png", "webp"],
    label_visibility="collapsed",
)
if uploaded is not None:
    st.session_state.image_bytes = uploaded.getvalue()
    if st.button("开始本地 AI 分析", type="primary", width="stretch"):
        if not all([patient_name.strip(), outpatient_no.strip(), lesion_site.strip(), chief_complaint.strip()]):
            st.warning("请先完整填写患者姓名、患者编号、病灶部位和主诉。")
            st.stop()
        progress = st.status("正在院内本地完成 AI 分析", expanded=True)
        try:
            patient = api("POST", "/v1/patients", json={
                "name": patient_name.strip(), "sex": patient_sex, "age": int(patient_age),
                "outpatient_no": outpatient_no.strip(), "phone": patient_phone.strip(),
                "medical_history": medical_history.strip(), "allergy_history": allergy_history.strip(),
            })
            st.session_state.patient = patient
            progress.write("✓ 原始医疗影像保持在本地可信域")
            created = api(
                "POST",
                "/v1/cases",
                files={"image": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                data={
                    "mode": "clinician", "retention_mode": "local",
                    "patient_id": patient["patient_id"], "lesion_site": lesion_site.strip(),
                    "chief_complaint": chief_complaint.strip(),
                },
            )
            st.session_state.case_id = created["case_id"]
            st.session_state.verification_plan = None
            st.session_state.contextual_assessment = None
            st.session_state.active_report = None
            progress.write("✓ 图片质量检查与图像特征分析")
            st.session_state.analysis = api(
                "POST", f"/v1/cases/{st.session_state.case_id}/analyze"
            )
            progress.write("✓ 确定性分级策略与后续医疗路径已生成")
            progress.update(label="本地分析完成", state="complete", expanded=False)
        except Exception as exc:
            progress.update(label="分析失败", state="error")
            st.error(str(exc))


analysis = st.session_state.analysis
left, right = st.columns([1.85, 1], gap="large")

with left:
    st.markdown('<div class="dg-section-label">分析结果</div>', unsafe_allow_html=True)
    if analysis is None:
        st.markdown(V.render_empty_state(), unsafe_allow_html=True)
    else:
        image_col, status_col = st.columns([1, 1])
        with image_col:
            st.image(st.session_state.image_bytes, caption="病灶图片", width="stretch")
        with status_col:
            st.markdown(V.render_case_status(analysis), unsafe_allow_html=True)

        level = analysis["triage"]["level"]
        card_class = "priority" if level == "PRIORITY_REFERRAL" else "retake" if level == "RETAKE" else ""
        technical_level = f"<b>{level}</b>" if st.session_state.mode == "clinician" else ""
        st.markdown(
            f'<div class="path-card {card_class}"><small>分级结果</small><h2>{LEVEL_LABELS[level]}</h2>{technical_level}<p>{analysis["care_pathway"]["action"]}</p></div>',
            unsafe_allow_html=True,
        )
        inject(V.render_risk_gauge(level, float(analysis["visual"].get("image_quality", 0))), height=142)
        inject(V.render_triage_tree(level), height=142)
        st.markdown("#### 视觉候选参考")
        st.caption("不能替代医生检查或病理诊断。")
        if analysis["visual"].get("abstained"):
            st.warning("本次结果低于模型可信阈值，请由专业人员复核，不应依据首位候选自行判断。")
        inject(V.render_candidate_radar(analysis["visual"]["top_predictions"], DISEASE_LABELS), height=278)
        st.markdown("#### 建议的下一步")
        for index, item in enumerate(analysis["care_pathway"]["recommended_next_steps"], 1):
            st.write(f"{index}. {item}")

        with st.expander("查看本次证据链", expanded=False):
            inject(V.render_evidence_graph(analysis, DISEASE_LABELS), height=178)

        st.markdown("#### 指南依据")
        for item in analysis["guidelines"]:
            evidence_label = item.get("evidence_type", "医学依据")
            with st.expander(f"{evidence_label} · {item['title']}"):
                st.write(item["content"])
                st.markdown(f"[查看原始来源]({item['source']})")
                if item.get("evidence_status") == "当前知识库证据不足":
                    st.warning("当前知识库证据不足，请勿据此作出确定性判断。")
                if st.session_state.mode == "clinician":
                    citation = item.get("citation", {})
                    st.caption(
                        f"证据编号：{item['id']} · 机构：{citation.get('organization', '未标注')} · "
                        f"年份：{citation.get('year', '未标注')} · 章节：{citation.get('section', '未标注')} · "
                        f"位置：{citation.get('page', '未标注')} · 版本：{citation.get('version', '未标注')} · "
                        f"检索分数：{item['score']:.4f}"
                    )

        if st.session_state.mode == "clinician":
            st.markdown("#### 临床技术视图")
            predictions = [
                {
                    "候选类别": display_label_zh(item["label"]),
                    "匹配分数": f'{float(item["score"]):.4f}',
                }
                for item in analysis["visual"]["top_predictions"]
            ]
            st.markdown(
                V.render_data_table(
                    predictions,
                    [("候选类别", "候选类别"), ("匹配分数", "匹配分数")],
                ),
                unsafe_allow_html=True,
            )
            with st.expander("分级依据"):
                st.write(analysis["care_pathway"]["action"])
                st.write(analysis["care_pathway"]["recommended_next_steps"])
            with st.expander("医学知识检索"):
                st.markdown(
                    V.render_json_block({"guidelines": analysis["guidelines"]}),
                    unsafe_allow_html=True,
                )
            with st.expander("MCP 工具与服务状态"):
                st.markdown(
                    V.render_json_block({
                        "mcp_server": "official Python SDK · stdio",
                        "tools": [
                            "get_visual_evidence",
                            "get_triage_result",
                            "search_guideline",
                            "get_care_pathway",
                            "get_privacy_report",
                            "get_contextual_assessment",
                        ],
                        "decision_plane_mutable_by_agent": False,
                    }),
                    unsafe_allow_html=True,
                )

with right:
    st.markdown('<div class="dg-section-label">隐私与助手</div>', unsafe_allow_html=True)
    st.caption("聊天助手位于页面右下角，病例图像不会发送给云端模型。")
    if analysis is None:
        st.info("完成图片分析后，可在悬浮窗口询问分级依据和下一步安排。")
    else:
        try:
            privacy = api("GET", f"/v1/cases/{st.session_state.case_id}/privacy")
            st.markdown(V.render_privacy_panel(privacy), unsafe_allow_html=True)
        except Exception as exc:
            st.warning(str(exc))

        if st.session_state.mode == "clinician":
            if st.button("查看云端载荷", width="stretch"):
                try:
                    st.markdown(
                        V.render_json_block(
                            api("GET", f"/v1/cases/{st.session_state.case_id}/cloud-payload")
                        ),
                        unsafe_allow_html=True,
                    )
                except Exception as exc:
                    st.error(str(exc))
            with st.expander("隐私审计"):
                try:
                    st.markdown(
                        V.render_json_block(
                            api("GET", "/v1/audit", params={"case_id": st.session_state.case_id})
                        ),
                        unsafe_allow_html=True,
                    )
                except Exception as exc:
                    st.error(str(exc))

if analysis is not None:
    st.divider()
    st.markdown('<div class="dg-section-label">症状核验</div>', unsafe_allow_html=True)
    st.subheader("结合症状进行二次风险校准")
    if st.session_state.verification_plan is None:
        with st.form("context_intake"):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                duration_label = st.selectbox("病灶出现多久？", list(DURATION_VALUES))
                pain = st.checkbox("有疼痛")
                pruritus = st.checkbox("有瘙痒")
            with col_b:
                fever = st.checkbox("伴发热")
                rapid_spread = st.checkbox("近期范围快速扩大")
                severe_bleeding = st.checkbox("出血较多且难以止住")
            with col_c:
                breathing = st.checkbox("呼吸困难")
                consciousness = st.checkbox("意识异常")
                severe_allergy = st.checkbox("疑似严重过敏反应")
            planner_model = st.selectbox(
                "追问排序模型",
                ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "glm-5.3-flash", "glm-4-flash", "auto"],
                format_func=lambda value: {
                    "openai/gpt-oss-120b": "Groq·GPT-OSS 120B",
                    "openai/gpt-oss-20b": "Groq·GPT-OSS 20B",
                    "qwen/qwen3.8-27b": "Groq·Qwen3.8 27B（预览）",
                    "glm-5.3-flash": "智谱 GLM-5.3-Flash",
                    "glm-4-flash": "智谱 GLM-4-Flash",
                    "auto": "后端默认模型",
                }[value],
            )
            submitted = st.form_submit_button("生成针对性追问", type="primary", width="stretch")
        if submitted:
            try:
                with st.spinner("正在结合视觉候选、症状信息与本地指南生成追问……"):
                    st.session_state.verification_plan = api(
                        "POST",
                        f"/v1/cases/{st.session_state.case_id}/contextual-intake",
                        json={
                            "duration": DURATION_VALUES[duration_label],
                            "pain": pain,
                            "pruritus": pruritus,
                            "fever": fever,
                            "rapid_spread": rapid_spread,
                            "breathing_difficulty": breathing,
                            "altered_consciousness": consciousness,
                            "severe_bleeding": severe_bleeding,
                            "severe_allergic_reaction": severe_allergy,
                            "model": planner_model,
                        },
                    )
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    plan = st.session_state.verification_plan
    if plan is not None and st.session_state.contextual_assessment is None:
        st.info(f"追问生成方式：{plan['planner_source']}｜原始图像未发送到云端")
        with st.form("verification_answers"):
            answers = []
            for question in plan["questions"]:
                choice = st.radio(
                    question["question"],
                    ["是", "否"],
                    index=None,
                    key=f"answer_{question['id']}",
                    horizontal=True,
                    help=question["patient_hint"],
                )
                answers.append((question["id"], choice))
            verified = st.form_submit_button("完成核验并进行二次校准", type="primary", width="stretch")
        if verified:
            if any(choice is None for _, choice in answers):
                st.warning("请回答全部追问后再提交。")
            else:
                try:
                    st.session_state.contextual_assessment = api(
                        "POST",
                        f"/v1/cases/{st.session_state.case_id}/contextual-calibration",
                        json={
                            "answers": [
                                {"question_id": item, "answer": choice == "是"}
                                for item, choice in answers
                            ]
                        },
                    )
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    contextual = st.session_state.contextual_assessment
    if contextual is not None:
        visual_level = contextual["visual_triage_level"]
        adjusted_level = contextual["contextual_triage_level"]
        st.markdown(
            V.render_calibration_compare(visual_level, adjusted_level, contextual["risk_changed"]),
            unsafe_allow_html=True,
        )
        symptom_features = {
            "病程": 0.6, "疼痛": 0.3, "瘙痒": 0.4, "发热": 0.2,
            "快速扩散": 0.1, "边缘变化": 0.5, "出血": 0.0,
            "呼吸困难": 0.0, "意识异常": 0.0, "严重过敏": 0.0,
        }
        for feat in contextual.get("positive_context_features", []) or []:
            for key in symptom_features:
                if key in feat:
                    symptom_features[key] = 0.85
        inject(V.render_symptom_heatmap(symptom_features), height=320)
        st.success(contextual["action"])
        st.caption("视觉候选分数未被修改；云模型未决定风险等级。")
        with st.expander("二次校准依据"):
            st.write("本地规则原因：", contextual["reason_codes"])
            st.write("阳性上下文特征：", contextual["positive_context_features"] or ["无"])
            st.write("本地 RAG 引用：", [item["title"] for item in contextual["rag_references"]])

if analysis is not None:
    st.divider()
    st.markdown('<div class="dg-section-label">辅助诊断报告</div>', unsafe_allow_html=True)
    st.subheader("生成并在线编辑报告")
    st.caption("云端模型仅接收脱敏后的结构化信息；患者姓名、门诊号、联系方式和原始图像均在本地回填。")
    report_left, report_right = st.columns([1, 2.3], gap="large")
    with report_left:
        try:
            available_models = [item for item in api("GET", "/v1/chat/models") if item.get("available")]
        except Exception:
            available_models = []
        model_options = ["local-template", *[item["id"] for item in available_models]]
        model_labels = {"local-template": "本地结构化模板（离线）"}
        model_labels.update({item["id"]: item["label"] for item in available_models})
        report_model = st.selectbox(
            "报告生成模型", model_options, format_func=lambda value: model_labels.get(value, value)
        )
        if st.button("生成报告初稿", type="primary", width="stretch"):
            try:
                with st.spinner("正在整理结构化病例证据并生成报告初稿……"):
                    report = api(
                        "POST", f"/v1/cases/{st.session_state.case_id}/reports",
                        json={"model": report_model},
                    )
                st.session_state.active_report = report
                st.session_state.report_editor = report["content"]
                st.rerun()
            except Exception as exc:
                st.error(str(exc))
        if st.session_state.active_report:
            st.success("报告初稿已保存并关联当前患者与输入图像。")
            st.caption(
                f"生成方式：{st.session_state.active_report['provider']} · "
                f"{st.session_state.active_report['model']}"
            )
    with report_right:
        if st.session_state.active_report:
            edited_report = st.text_area(
                "报告正文（可直接修改）", key="report_editor", height=420
            )
            save_col, download_col = st.columns(2)
            with save_col:
                if st.button("保存医生终稿", type="primary", width="stretch"):
                    try:
                        st.session_state.active_report = api(
                            "PUT", f"/v1/reports/{st.session_state.active_report['report_id']}",
                            json={"content": edited_report, "status": "final"},
                        )
                        st.success("医生终稿已保存，历史版本已记录。")
                    except Exception as exc:
                        st.error(str(exc))
            with download_col:
                st.download_button(
                    "下载 Markdown", edited_report,
                    file_name=st.session_state.active_report["filename"],
                    mime="text/markdown", width="stretch",
                )
            with st.expander("报告预览", expanded=True):
                st.markdown(edited_report)
        else:
            st.info("选择模型生成报告后，可在这里在线编辑、预览和保存。")

chatbox_template = (Path(__file__).with_name("chatbox_component.html")).read_text(encoding="utf-8")
chatbox_config = {
    "apiUrl": API_URL.rstrip("/"),
    "caseId": st.session_state.case_id,
    "mode": "clinician",
    "authToken": st.session_state.auth_token,
    "defaultModel": (
        os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
        if os.getenv("DERMAGUARD_CHAT_PROVIDER", "mock").strip().lower() == "groq"
        else os.getenv("ZHIPUAI_MODEL", "glm-5.3-flash")
    ),
}
st.iframe(
    chatbox_template.replace("__DG_CONFIG__", json.dumps(chatbox_config, ensure_ascii=False)),
    width=1,
    height=1,
    alt="霁肤悬浮聊天助手运行组件",
)
