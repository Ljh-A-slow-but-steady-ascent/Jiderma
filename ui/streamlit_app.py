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
REGION_VALUES = {
    "腹部": "ABDOMEN", "上臂": "ARM", "背部": "BACK", "胸部": "CHEST",
    "耳部": "EAR", "面部": "FACE", "足部": "FOOT", "前臂": "FOREARM",
    "手部": "HAND", "唇部": "LIP", "颈部": "NECK", "鼻部": "NOSE",
    "头皮": "SCALP", "大腿": "THIGH",
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
    "patient": None,
    "active_report": None,
    "clinical_draft": None,
    "clinical_draft_source": "",
    "confirmed_metadata": None,
    "confirmed_metadata_source": "",
    "clinical_extraction_info": None,
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
        patient_sex = st.selectbox("性别 *", ["男", "女"])
    with p3:
        patient_age = st.number_input("年龄 *", min_value=0, max_value=130, value=30)
    with p4:
        outpatient_no = st.text_input("患者编号 / 门诊号 *")
    patient_phone = st.text_input("联系方式（选填）")

st.markdown('<div class="dg-section-label">病例自然语言描述</div>', unsafe_allow_html=True)
st.caption("请用自然语言记录部位、尺寸、症状、变化及肿瘤病史。患者身份信息会在调用语言模型前脱敏。")
with st.container(border=True):
    clinical_narrative = st.text_area(
        "医生病例描述 *", height=170,
        placeholder=(
            "例如：面部色素性病灶，约9×9毫米，近期明显增大且颜色发生变化，"
            "无疼痛、瘙痒和出血，无皮肤肿瘤及其他肿瘤病史。"
        ),
    )
    try:
        extraction_catalog = [
            item for item in api("GET", "/v1/chat/models") if item.get("available")
        ]
    except Exception:
        extraction_catalog = []
    extraction_options = ["auto", *[item["id"] for item in extraction_catalog]]
    extraction_labels = {"auto": "系统默认语言模型"}
    extraction_labels.update({item["id"]: item["label"] for item in extraction_catalog})
    extraction_model = st.selectbox(
        "病例信息抽取模型", extraction_options,
        format_func=lambda value: extraction_labels.get(value, value),
    )

source_fingerprint = json.dumps(
    {
        "narrative": clinical_narrative.strip(),
        "age": int(patient_age),
        "gender": "MALE" if patient_sex == "男" else "FEMALE",
    },
    ensure_ascii=False,
    sort_keys=True,
)
if st.button("解析病例信息", type="secondary", width="stretch"):
    if len(clinical_narrative.strip()) < 10:
        st.warning("请先输入完整的病例描述。")
    else:
        try:
            with st.spinner("正在脱敏并抽取结构化病例信息……"):
                extracted = api("POST", "/v1/clinical-metadata/extract", json={
                    "narrative": clinical_narrative.strip(),
                    "age": int(patient_age),
                    "gender": "MALE" if patient_sex == "男" else "FEMALE",
                    "patient_name": patient_name.strip(),
                    "outpatient_no": outpatient_no.strip(),
                    "phone": patient_phone.strip(),
                    "model": extraction_model,
                })
            st.session_state.clinical_draft = extracted
            st.session_state.clinical_draft_source = source_fingerprint
            st.session_state.confirmed_metadata = None
            st.session_state.confirmed_metadata_source = ""
            draft = extracted["metadata"]
            reverse_regions = {value: label for label, value in REGION_VALUES.items()}
            st.session_state.confirm_region = reverse_regions.get(draft.get("region"), "未识别")
            st.session_state.confirm_diameter_1 = float(draft.get("diameter_1") or 0.0)
            st.session_state.confirm_diameter_2 = float(draft.get("diameter_2") or 0.0)
            for field in ("itch", "hurt", "bleed", "grew", "changed", "skin_cancer_history", "cancer_history"):
                value = draft.get(field)
                st.session_state[f"confirm_{field}"] = "是" if value is True else "否" if value is False else "未识别"
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

draft_is_current = (
    st.session_state.clinical_draft is not None
    and st.session_state.clinical_draft_source == source_fingerprint
)
if st.session_state.clinical_draft is not None and not draft_is_current:
    st.info("病例描述或患者基本信息已变更，请重新解析。")

if draft_is_current:
    extracted = st.session_state.clinical_draft
    if extracted.get("missing_field_labels"):
        st.warning("以下信息未明确提供，请在确认卡中补充：" + "、".join(extracted["missing_field_labels"]))
    st.markdown("#### 结构化信息确认")
    st.caption("请医生核对后再进入多模态分析；未提取到的信息不会被自动补造。")
    with st.form("clinical-metadata-confirmation"):
        m1, m2, m3 = st.columns(3)
        with m1:
            confirmed_region_label = st.selectbox("解剖部位", ["未识别", *REGION_VALUES], key="confirm_region")
        with m2:
            confirmed_diameter_1 = st.number_input(
                "病灶长径（毫米）", min_value=0.0, max_value=200.0,
                step=0.5, key="confirm_diameter_1",
            )
        with m3:
            confirmed_diameter_2 = st.number_input(
                "病灶短径（毫米）", min_value=0.0, max_value=200.0,
                step=0.5, key="confirm_diameter_2",
            )
        boolean_labels = {
            "itch": "瘙痒", "hurt": "疼痛", "bleed": "出血",
            "grew": "近期增大", "changed": "外观变化",
            "skin_cancer_history": "皮肤肿瘤史", "cancer_history": "其他肿瘤史",
        }
        boolean_values: dict[str, str] = {}
        columns = st.columns(4)
        for index, (field, label) in enumerate(boolean_labels.items()):
            with columns[index % 4]:
                boolean_values[field] = st.selectbox(
                    label, ["未识别", "否", "是"], key=f"confirm_{field}"
                )
        confirmed = st.form_submit_button("确认病例信息", type="primary", width="stretch")
    if confirmed:
        unresolved = [label for field, label in boolean_labels.items() if boolean_values[field] == "未识别"]
        if confirmed_region_label == "未识别":
            unresolved.append("解剖部位")
        if confirmed_diameter_1 <= 0:
            unresolved.append("病灶长径")
        if confirmed_diameter_2 <= 0:
            unresolved.append("病灶短径")
        if unresolved:
            st.error("请先补充：" + "、".join(unresolved))
        else:
            st.session_state.confirmed_metadata = {
                "age": int(patient_age),
                "gender": "MALE" if patient_sex == "男" else "FEMALE",
                "region": REGION_VALUES[confirmed_region_label],
                **{field: value == "是" for field, value in boolean_values.items()},
                "diameter_1": float(confirmed_diameter_1),
                "diameter_2": float(confirmed_diameter_2),
            }
            st.session_state.confirmed_metadata_source = source_fingerprint
            st.session_state.clinical_extraction_info = {
                "provider": extracted.get("provider"), "model": extracted.get("model"),
                "privacy_status": extracted.get("privacy_status"),
            }
            st.success("结构化病例信息已由医生确认。")

metadata_is_confirmed = (
    st.session_state.confirmed_metadata is not None
    and st.session_state.confirmed_metadata_source == source_fingerprint
)
if metadata_is_confirmed:
    st.success("病例文本已解析、核对，可与病灶图像共同分析。")

st.markdown('<div class="dg-section-label">病灶图像</div>', unsafe_allow_html=True)

st.markdown(
    '<div class="dg-upload-note"><i></i><span>支持 JPG、PNG 与 WEBP；建议使用光线均匀、对焦清晰的临床皮肤图像</span></div>',
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
        if not all([patient_name.strip(), outpatient_no.strip(), clinical_narrative.strip()]):
            st.warning("请先完整填写患者姓名、患者编号和病例描述。")
            st.stop()
        if not metadata_is_confirmed:
            st.warning("请先解析并确认结构化病例信息。")
            st.stop()
        progress = st.status("正在院内本地完成 AI 分析", expanded=True)
        try:
            patient = api("POST", "/v1/patients", json={
                "name": patient_name.strip(), "sex": patient_sex, "age": int(patient_age),
                "outpatient_no": outpatient_no.strip(), "phone": patient_phone.strip(),
                "medical_history": "", "allergy_history": "",
            })
            st.session_state.patient = patient
            progress.write("✓ 原始医疗影像保持在本地可信域")
            created = api(
                "POST",
                "/v1/cases",
                files={"image": (uploaded.name, uploaded.getvalue(), uploaded.type)},
                data={
                    "mode": "clinician", "retention_mode": "local",
                    "patient_id": patient["patient_id"],
                    "lesion_site": {value: label for label, value in REGION_VALUES.items()}[
                        st.session_state.confirmed_metadata["region"]
                    ],
                    "chief_complaint": clinical_narrative.strip(),
                    "clinical_metadata_json": json.dumps(
                        st.session_state.confirmed_metadata, ensure_ascii=False
                    ),
                },
            )
            st.session_state.case_id = created["case_id"]
            st.session_state.active_report = None
            progress.write("✓ 图片质量检查与图像—病例联合分析")
            st.session_state.analysis = api(
                "POST", f"/v1/cases/{st.session_state.case_id}/analyze"
            )
            progress.write("✓ Top-3 候选与本地医学证据已生成")
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
        st.markdown("#### 多模态候选参考")
        st.caption("不能替代医生检查或病理诊断。")
        inject(V.render_candidate_radar(analysis["visual"]["top_predictions"], DISEASE_LABELS), height=278)
        st.markdown("#### 建议的下一步")
        for index, item in enumerate(analysis["care_pathway"]["recommended_next_steps"], 1):
            st.write(f"{index}. {item}")

        with st.expander("查看本次证据链", expanded=False):
            inject(V.render_evidence_graph(analysis, DISEASE_LABELS), height=178)

        st.markdown("#### Top-3 候选的循证参考")
        st.caption("证据用于帮助医生核对支持点、冲突点、检查与转诊依据，不会重新排序模型候选。")
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
