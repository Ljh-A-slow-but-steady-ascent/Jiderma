from __future__ import annotations

import os
from typing import Any

import requests
import streamlit as st

from ui import visuals as V


API_URL = os.getenv("DERMAGUARD_API_URL", "http://127.0.0.1:8000").rstrip("/")
st.set_page_config(page_title="霁肤 · 病例报告库", page_icon="霁", layout="wide")
st.markdown(V.theme_css(), unsafe_allow_html=True)


def response(method: str, path: str, **kwargs) -> requests.Response:
    headers = dict(kwargs.pop("headers", {}))
    token = st.session_state.get("auth_token", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    result = requests.request(method, f"{API_URL}{path}", headers=headers, timeout=240, **kwargs)
    if not result.ok:
        try:
            detail = result.json().get("detail", result.text)
        except Exception:
            detail = result.text
        raise RuntimeError(f"请求失败（{result.status_code}）：{detail}")
    return result


def api(method: str, path: str, **kwargs) -> Any:
    return response(method, path, **kwargs).json()


if not st.session_state.get("auth_token"):
    st.switch_page("streamlit_app.py")
    st.stop()

for key, default in {"archive_report_id": None, "delete_report_id": None}.items():
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    st.markdown("### 霁肤 · Jiderma")
    user = st.session_state.get("auth_user") or {}
    st.write(f"**{user.get('full_name', '医生')}**")
    if st.button("返回诊疗工作台", width="stretch"):
        st.switch_page("streamlit_app.py")
    if st.button("退出登录", width="stretch"):
        try:
            api("POST", "/v1/auth/logout")
        except Exception:
            pass
        st.session_state.clear()
        st.switch_page("streamlit_app.py")

st.title("病例报告库")
st.caption("报告正文、输入图像、患者病例和生成记录统一关联；删除报告不会删除患者病例与原始图像。")

search = st.text_input("搜索患者姓名、患者编号或报告名称", placeholder="输入关键词")
try:
    reports = api("GET", "/v1/reports", params={"query": search})
except Exception as exc:
    st.error(str(exc))
    st.stop()

if not reports:
    st.info("当前没有匹配的报告。请先在诊疗工作台完成分析并生成报告。")
else:
    st.markdown(f"#### 报告文件 · {len(reports)}")
    for item in reports:
        c1, c2, c3, c4 = st.columns([4.2, 1.4, .8, .8], vertical_alignment="center")
        c1.markdown(
            f"**📄 {item['filename']}**  \n"
            f"患者：{item['patient_name']} · 编号：{item['outpatient_no']} · "
            f"状态：{'医生终稿' if item['status'] == 'final' else 'AI 初稿'}"
        )
        c2.caption(item["updated_at"][:16].replace("T", " "))
        if c3.button("打开", key=f"open-{item['report_id']}", width="stretch"):
            st.session_state.archive_report_id = item["report_id"]
            st.session_state.delete_report_id = None
            st.rerun()
        if c4.button("删除", key=f"delete-{item['report_id']}", width="stretch"):
            st.session_state.delete_report_id = item["report_id"]
            st.rerun()

if st.session_state.delete_report_id:
    target = next((item for item in reports if item["report_id"] == st.session_state.delete_report_id), None)
    st.warning(f"确认删除报告“{target['filename'] if target else st.session_state.delete_report_id}”吗？患者病例与原始图像会保留。")
    yes, no = st.columns(2)
    if yes.button("确认删除报告", type="primary", width="stretch"):
        try:
            api("DELETE", f"/v1/reports/{st.session_state.delete_report_id}")
            if st.session_state.archive_report_id == st.session_state.delete_report_id:
                st.session_state.archive_report_id = None
            st.session_state.delete_report_id = None
            st.success("报告已删除；患者病例和原始图像仍保留。")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if no.button("取消", width="stretch"):
        st.session_state.delete_report_id = None
        st.rerun()

if st.session_state.archive_report_id:
    st.divider()
    try:
        report = api("GET", f"/v1/reports/{st.session_state.archive_report_id}")
        st.subheader(report["filename"])
        st.caption(
            f"患者：{report['patient_name']} · 患者编号：{report['outpatient_no']} · "
            f"病例：{report['case_id']} · 生成模型：{report['model']}"
        )
        image_col, editor_col = st.columns([1, 1.65], gap="large")
        with image_col:
            image_response = response("GET", f"/v1/reports/{report['report_id']}/image")
            st.image(image_response.content, caption="报告关联的输入图像", width="stretch")
            st.caption("原图仅通过已鉴权的本地接口读取。")
        with editor_col:
            editor_key = f"archive-editor-{report['report_id']}"
            content = st.text_area("报告正文（可在线编辑）", value=report["content"], height=480, key=editor_key)
            save, download = st.columns(2)
            if save.button("保存医生终稿", type="primary", width="stretch"):
                try:
                    api("PUT", f"/v1/reports/{report['report_id']}", json={"content": content, "status": "final"})
                    st.success("报告已保存，并记录新的编辑版本。")
                except Exception as exc:
                    st.error(str(exc))
            download.download_button(
                "下载 Markdown", content, file_name=report["filename"],
                mime="text/markdown", width="stretch",
            )
            with st.expander("报告预览", expanded=True):
                st.markdown(content)
    except Exception as exc:
        st.error(str(exc))
