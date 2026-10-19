"""霁肤 · Jiderma 的纯展示组件，不参与推理、分诊、RAG 或 Agent 决策。"""
from __future__ import annotations

import json
from html import escape
from typing import Any


RISK_COLORS = {
    "RETAKE": "#d6a55b",
    "LOCAL_REVIEW": "#62b7a6",
    "REFERRAL": "#d58a62",
    "PRIORITY_REFERRAL": "#d66b73",
}
RISK_LABELS_ZH = {
    "RETAKE": "请重新拍摄",
    "LOCAL_REVIEW": "基层继续评估",
    "REFERRAL": "建议专科转诊",
    "PRIORITY_REFERRAL": "建议优先转诊",
}


DARK_THEME_CSS = r"""
<style>
:root {
  --dg-bg:#0b0f12; --dg-surface:#141b20; --dg-surface-2:#182127;
  --dg-border:rgba(207,225,225,.11); --dg-border-strong:rgba(207,225,225,.18);
  --dg-text:#edf2f0; --dg-muted:#93a09e; --dg-accent:#79c8b8;
  --dg-accent-strong:#9bdecf; --dg-danger:#d66b73; --dg-warning:#d5a15e;
  color-scheme:dark;
}
#MainMenu,[data-testid="stFooter"],[data-testid="stHeaderActionElements"]{display:none!important}
[data-testid="stHeader"]{background:transparent!important}
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{
  background:#0b0f12!important;color:var(--dg-text)!important
}
[data-testid="stAppViewContainer"]{
  background:
    radial-gradient(900px 480px at 12% -10%,rgba(74,132,121,.13),transparent 64%),
    radial-gradient(700px 420px at 92% 8%,rgba(117,95,67,.08),transparent 64%),
    linear-gradient(180deg,#0b0f12 0%,#0d1216 58%,#0a0d10 100%)!important
}
.block-container{max-width:1280px;padding:1.6rem 2.2rem 5rem}
.stApp,.stApp p,.stApp span,.stApp label,.stApp li,.stApp h1,.stApp h2,.stApp h3,.stApp h4,.stMarkdown{color:var(--dg-text)}
.stApp h1,.stApp h2,.stApp h3{letter-spacing:-.025em}
.stApp h2{font-size:1.35rem;font-weight:650;margin-top:.25rem}
.stApp h3{font-size:1.05rem;font-weight:640}
[data-testid="stCaptionContainer"],.stCaption{color:var(--dg-muted)!important}
hr{border-color:var(--dg-border)!important;margin:1.7rem 0!important}

[data-testid="stVerticalBlockBorderWrapper"]{
  border-color:var(--dg-border)!important;border-radius:18px!important;
  background:rgba(20,27,32,.64)!important
}
[data-testid="stFileUploaderDropzone"]{
  min-height:138px;background:linear-gradient(145deg,rgba(24,33,39,.82),rgba(16,22,26,.72))!important;
  border:1px dashed rgba(121,200,184,.34)!important;border-radius:16px!important;
  transition:border-color .2s ease,background .2s ease
}
[data-testid="stFileUploaderDropzone"]:hover{border-color:rgba(121,200,184,.72)!important;background:rgba(25,37,41,.92)!important}
[data-testid="stFileUploaderDropzone"] button{
  background:#1e2a2e!important;border:1px solid var(--dg-border-strong)!important;
  color:var(--dg-text)!important;border-radius:10px!important
}
.stButton>button,.stFormSubmitButton>button,button[kind="secondary"]{
  min-height:42px;border-radius:12px!important;font-weight:650!important;
  color:var(--dg-text)!important;border:1px solid var(--dg-border-strong)!important;
  background:#182126!important;box-shadow:none!important;
  transition:transform .16s ease,border-color .16s ease,background .16s ease!important
}
.stButton>button:hover,.stFormSubmitButton>button:hover{
  transform:translateY(-1px);border-color:rgba(121,200,184,.58)!important;background:#1c292d!important
}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{
  color:#07100e!important;border:0!important;background:linear-gradient(135deg,#9bdccc,#70b9ab)!important;
  box-shadow:0 8px 24px rgba(55,122,109,.18)!important
}
[data-baseweb="select"]>div,[data-baseweb="input"]>div,.stTextArea textarea,[data-testid="stNumberInputContainer"]{
  background:#141c21!important;color:var(--dg-text)!important;
  border-color:var(--dg-border-strong)!important;border-radius:11px!important
}
[data-baseweb="popover"] ul{background:#161e23!important}
[data-testid="stCheckbox"] label,[data-testid="stRadio"] label{padding:.28rem .1rem;color:var(--dg-text)!important}
[data-testid="stSegmentedControl"]>div{
  background:#11171b!important;border:1px solid var(--dg-border)!important;
  border-radius:12px!important;padding:3px!important
}
[data-testid="stSegmentedControl"] button{
  background:transparent!important;color:var(--dg-muted)!important;border:0!important;
  box-shadow:none!important;border-radius:9px!important
}
[data-testid="stSegmentedControl"] button *{color:inherit!important}
[data-testid="stSegmentedControl"] button[aria-pressed="true"],
[data-testid="stSegmentedControl"] button[aria-checked="true"],
[data-testid="stSegmentedControl"] button[data-selected="true"]{
  background:#263a38!important;color:var(--dg-accent-strong)!important
}
[data-testid="stAlert"]{
  background:rgba(20,29,34,.8)!important;border:1px solid var(--dg-border)!important;border-radius:14px!important
}
[data-testid="stExpander"]{
  background:rgba(18,25,30,.68)!important;border:1px solid var(--dg-border)!important;
  border-radius:14px!important;overflow:hidden
}
[data-testid="stForm"]{
  background:linear-gradient(145deg,rgba(20,28,33,.78),rgba(16,22,26,.66));
  border:1px solid var(--dg-border)!important;border-radius:18px!important;padding:1.25rem 1.3rem .35rem
}
[data-testid="stStatusWidget"]{background:#141c21!important;border:1px solid var(--dg-border)!important;border-radius:14px!important}
[data-testid="stImage"] img{border-radius:16px;border:1px solid var(--dg-border)}
.stDataFrame{border:1px solid var(--dg-border);border-radius:14px;overflow:hidden}
.dg-data-table-wrap{margin:.35rem 0 1rem;border:1px solid var(--dg-border);border-radius:14px;overflow:hidden;background:var(--dg-surface)}
.dg-data-table{width:100%;border-collapse:collapse;color:var(--dg-text);font-size:.88rem}
.dg-data-table th,.dg-data-table td{padding:.72rem .82rem;border-bottom:1px solid var(--dg-border);text-align:left}
.dg-data-table th{background:var(--dg-surface-2);color:var(--dg-muted);font-size:.78rem;font-weight:680;letter-spacing:.02em}
.dg-data-table tr:last-child td{border-bottom:0}.dg-data-table td:last-child{text-align:right;font-variant-numeric:tabular-nums}
.dg-json-shell{max-height:520px;overflow:auto;margin:.35rem 0 1rem;padding:.9rem 1rem;border:1px solid var(--dg-border);border-radius:14px;background:#10161a}
.dg-json-shell pre{margin:0;color:#dce8e4!important;background:transparent!important;font:12px/1.62 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}

.dg-section-label{
  display:flex;align-items:center;gap:.65rem;margin:.15rem 0 .85rem;color:var(--dg-muted);
  font-size:.76rem;font-weight:750;letter-spacing:.13em;text-transform:uppercase
}
.dg-section-label:before{content:"";width:22px;height:1px;background:var(--dg-accent)}
.dg-upload-note{
  margin:.15rem 0 .8rem;padding:.78rem 1rem;display:flex;align-items:center;gap:.65rem;
  color:#adbbb8;font-size:.84rem;background:rgba(121,200,184,.055);
  border:1px solid rgba(121,200,184,.12);border-radius:12px
}
.dg-upload-note i{width:8px;height:8px;border-radius:50%;background:var(--dg-accent);display:block}
.path-card{
  padding:1.15rem 1.2rem;margin:.5rem 0 1rem;border-radius:16px;
  background:linear-gradient(145deg,rgba(24,34,39,.94),rgba(17,24,28,.94));
  border:1px solid var(--dg-border);border-left:3px solid var(--dg-accent)
}
.path-card.priority{border-left-color:var(--dg-danger)} .path-card.retake{border-left-color:var(--dg-warning)}
.path-card small{color:var(--dg-muted);font-weight:650;letter-spacing:.05em}
.path-card h2{margin:.22rem 0 .4rem;font-size:1.55rem}.path-card p{margin:0;color:#b8c4c1;line-height:1.65}
.dg-empty{
  min-height:258px;display:flex;flex-direction:column;align-items:center;justify-content:center;
  text-align:center;border:1px solid var(--dg-border);border-radius:18px;
  background:linear-gradient(145deg,rgba(20,28,33,.66),rgba(13,18,21,.5))
}
.dg-empty-mark{
  width:48px;height:48px;display:grid;place-items:center;margin-bottom:1rem;border-radius:14px;
  color:var(--dg-accent-strong);background:rgba(121,200,184,.09);
  border:1px solid rgba(121,200,184,.2);font-size:1.25rem
}
.dg-empty strong{font-size:1.02rem;font-weight:650}.dg-empty p{color:var(--dg-muted);max-width:360px;margin:.5rem auto 0;font-size:.88rem;line-height:1.65}
.dg-footer-line{color:#75827f;font-size:.77rem;text-align:center;letter-spacing:.01em}
@media(max-width:760px){.block-container{padding:1rem 1rem 5rem}[data-testid="column"]{min-width:100%!important}}
</style>
"""

LIGHT_THEME_OVERRIDES = r"""
<style>
:root{
  --dg-bg:#f3f6f5;--dg-surface:#ffffff;--dg-surface-2:#eef3f1;
  --dg-border:rgba(32,65,59,.12);--dg-border-strong:rgba(32,65,59,.2);
  --dg-text:#172421;--dg-muted:#64736f;--dg-accent:#397d70;
  --dg-accent-strong:#2d6c61;--dg-danger:#b64e58;--dg-warning:#a56d28;
  color-scheme:light
}
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"]{
  background:#f3f6f5!important;color:var(--dg-text)!important
}
[data-testid="stAppViewContainer"]{
  background:radial-gradient(850px 430px at 10% -8%,rgba(82,154,140,.12),transparent 65%),linear-gradient(180deg,#f8faf9 0%,#eef3f1 100%)!important
}
[data-testid="stVerticalBlockBorderWrapper"],[data-testid="stAlert"],[data-testid="stExpander"],
[data-testid="stStatusWidget"]{background:rgba(255,255,255,.82)!important}
[data-testid="stFileUploaderDropzone"]{background:linear-gradient(145deg,#fff,#f1f6f4)!important}
[data-testid="stFileUploaderDropzone"]:hover{background:#eef5f2!important}
[data-testid="stFileUploaderDropzone"] button,.stButton>button,.stFormSubmitButton>button,button[kind="secondary"]{
  background:#fff!important;color:var(--dg-text)!important
}
.stButton>button:hover,.stFormSubmitButton>button:hover{background:#edf4f1!important}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{
  color:#fff!important;background:linear-gradient(135deg,#397d70,#4f9789)!important
}
[data-baseweb="select"]>div,[data-baseweb="input"]>div,.stTextArea textarea,[data-testid="stNumberInputContainer"],
[data-testid="stSegmentedControl"]>div{background:#fff!important;color:var(--dg-text)!important}
[data-testid="stSegmentedControl"] button{background:transparent!important;color:#52635f!important}
[data-testid="stSegmentedControl"] button[aria-pressed="true"],
[data-testid="stSegmentedControl"] button[aria-checked="true"],
[data-testid="stSegmentedControl"] button[data-selected="true"]{
  background:#dcebe7!important;color:#245f55!important;box-shadow:0 1px 2px rgba(31,70,62,.08)!important
}
[data-baseweb="select"] *,[data-baseweb="input"] *,[data-testid="stTextArea"] textarea,
[data-testid="stNumberInput"] *{color:var(--dg-text)!important}
[data-testid="stCheckbox"] label *,[data-testid="stRadio"] label *,[data-testid="stToggle"] label *{color:var(--dg-text)!important}
[data-baseweb="popover"],[data-baseweb="popover"] ul,[role="listbox"],[role="option"]{background:#fff!important;color:var(--dg-text)!important}
[data-testid="stExpander"] details,[data-testid="stExpander"] summary{background:transparent!important;color:var(--dg-text)!important}
[data-testid="stExpander"] summary *{color:var(--dg-text)!important}
[data-testid="stAlert"] *{color:var(--dg-text)!important}
[data-testid="stDataFrame"],.stDataFrame{background:#fff!important;color:var(--dg-text)!important}
[data-testid="stForm"]{background:linear-gradient(145deg,rgba(255,255,255,.94),rgba(240,246,244,.92))!important}
.dg-data-table-wrap{background:#fff}.dg-data-table th{background:#e8f0ed;color:#50635e}.dg-data-table td{color:#172421}
.dg-json-shell{background:#fff;border-color:rgba(32,65,59,.16);box-shadow:0 1px 3px rgba(30,64,57,.04)}
.dg-json-shell pre{color:#20302c!important}
.dg-upload-note{color:#51635f;background:rgba(57,125,112,.06)}
.path-card{background:linear-gradient(145deg,#fff,#f1f5f3)}
.path-card p{color:#485a56}.dg-empty{background:linear-gradient(145deg,#fff,#eef4f2)}
</style>
"""


def theme_css() -> str:
    """返回主页唯一的浅色主题样式。"""
    return DARK_THEME_CSS + LIGHT_THEME_OVERRIDES


IFRAME_CSS = r"""
<style>
*{box-sizing:border-box}html,body{margin:0;background:transparent;color:#edf2f0;
font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
:root{--surface:#141b20;--border:rgba(207,225,225,.11);--text:#edf2f0;
--muted:#93a09e;--muted-2:#71807d;--accent:#79c8b8;--accent-soft:#8fd2c4;
--danger:#d66b73;--warning:#d5a15e;--panel:rgba(20,28,33,.72);
--panel-soft:#11181c;--track:rgba(207,225,225,.08);--arrow:#52615e}
.dg-card{height:100%;padding:18px;border-radius:18px;border:1px solid var(--border);
background:linear-gradient(145deg,rgba(22,30,35,.96),rgba(15,21,25,.96));overflow:hidden}
.dg-eyebrow{color:var(--muted);font-size:11px;font-weight:750;letter-spacing:.12em;text-transform:uppercase}
.dg-card-title{margin:5px 0 0;color:var(--text);font-size:15px;font-weight:680}.dg-muted{color:var(--muted)}
</style>
"""

IFRAME_LIGHT_CSS = r"""
<style>
.dg-theme-light{--surface:#fff;--border:rgba(32,65,59,.14);--text:#172421;--muted:#64736f;
--muted-2:#71807d;--accent:#397d70;--accent-soft:#55998c;--danger:#b64e58;--warning:#a56d28;
--panel:#fff;--panel-soft:#edf3f1;--track:rgba(32,65,59,.10);--arrow:#72817d;
color:var(--text);height:100%;color-scheme:light}
.dg-theme-light .dg-card{background:linear-gradient(145deg,#fff,#eef4f2)}
.dg-theme-light .dg-hero{background:linear-gradient(120deg,#f9fbfa 0%,#edf4f1 58%,#e6f0ed 100%)!important}
.dg-theme-light .dg-hero h1{color:#172421!important}.dg-theme-light .dg-hero p{color:#52635f!important}
.dg-theme-light .dg-hero-kicker{color:#397d70!important}.dg-theme-light .dg-hero-badge{color:#4e625d!important;background:rgba(255,255,255,.65)!important;border-color:rgba(32,65,59,.12)!important}
.dg-theme-light [style*="color:#edf2f0"]{color:#172421!important}
.dg-theme-light [style*="color:#aab7b4"],.dg-theme-light [style*="color:#acb8b5"],.dg-theme-light [style*="color:#b7c2bf"],.dg-theme-light [style*="color:#aebbb8"]{color:#52635f!important}
</style>
"""


def iframe_wrap(html_body: str) -> str:
    return f'{IFRAME_CSS}{IFRAME_LIGHT_CSS}<div class="dg-theme-light" style="height:100%">{html_body}</div>'


def render_data_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    """主题感知表格，避免 Canvas DataFrame 在浅色模式下保留深色画布。"""
    headers = "".join(f"<th>{escape(label)}</th>" for _, label in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{escape(str(row.get(key, '')))}</td>" for key, _ in columns)
        + "</tr>"
        for row in rows
    )
    return (
        '<div class="dg-data-table-wrap"><table class="dg-data-table">'
        f"<thead><tr>{headers}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def render_json_block(value: Any) -> str:
    """主题感知 JSON 视图，用于替代固定深色的 Streamlit JSON 树。"""
    formatted = escape(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return f'<div class="dg-json-shell"><pre>{formatted}</pre></div>'


def render_hero() -> str:
    return """
<section class="dg-hero" style="height:100%;position:relative;overflow:hidden;border:1px solid rgba(207,225,225,.12);border-radius:22px;background:linear-gradient(120deg,#172229 0%,#11181c 58%,#18201f 100%);padding:25px 28px;">
  <div style="position:absolute;width:360px;height:360px;right:-110px;top:-190px;border-radius:50%;background:radial-gradient(circle,rgba(121,200,184,.16),transparent 67%);"></div>
  <div style="position:relative;display:flex;height:100%;align-items:center;justify-content:space-between;gap:24px;">
    <div>
      <div class="dg-hero-kicker" style="display:flex;align-items:center;gap:9px;margin-bottom:15px;color:#9bcfc4;font-size:11px;font-weight:750;letter-spacing:.12em;text-transform:uppercase;">
        <span style="width:8px;height:8px;border-radius:50%;background:#79c8b8;box-shadow:0 0 0 5px rgba(121,200,184,.08);"></span>医生辅助决策与病例工作台
      </div>
      <h1 style="margin:0;color:#f1f5f3;font-size:34px;line-height:1.05;letter-spacing:-.045em;font-weight:680;">霁肤 · Jiderma</h1>
      <p style="margin:10px 0 0;color:#a7b3b0;font-size:14px;">辅助分析、证据核验与诊疗报告统一工作流</p>
    </div>
    <div style="display:grid;grid-template-columns:repeat(2,max-content);gap:8px;align-self:flex-end;">
      <span class="dg-hero-badge" style="padding:7px 10px;border:1px solid rgba(207,225,225,.1);border-radius:999px;color:#aebbb8;font-size:11px;background:rgba(9,14,17,.24);">隐私保护</span>
      <span class="dg-hero-badge" style="padding:7px 10px;border:1px solid rgba(207,225,225,.1);border-radius:999px;color:#aebbb8;font-size:11px;background:rgba(9,14,17,.24);">证据可追溯</span>
    </div>
  </div>
</section>"""


def render_empty_state() -> str:
    return """
<div class="dg-empty"><div class="dg-empty-mark">⌁</div><strong>等待图像分析</strong>
<p>完成病例填写并上传清晰的临床皮肤图像后，将在这里呈现多模态候选、风险分级、医学证据与建议路径。</p></div>"""


def render_case_status(analysis: dict[str, Any]) -> str:
    visual = analysis.get("visual", {})
    case_id = escape(str(analysis.get("case_id", "未生成")))
    quality = float(visual.get("image_quality", 0.0))
    return f"""
<div style="border:1px solid var(--border);border-radius:16px;background:var(--panel);color:var(--text);padding:1rem 1.05rem;">
  <div style="color:var(--muted);font-size:.72rem;letter-spacing:.08em;margin-bottom:.7rem;">本地分析已完成</div>
  <div style="font-size:.8rem;color:var(--muted);margin-bottom:.8rem;word-break:break-all;">病例编号&nbsp; {case_id}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:.65rem;">
    <div style="padding:.72rem;border-radius:12px;background:var(--panel-soft);"><small style="color:var(--muted);">图像质量</small><div style="font-size:1.18rem;font-weight:680;margin-top:.2rem;">{quality:.0%}</div></div>
    <div style="padding:.72rem;border-radius:12px;background:var(--panel-soft);"><small style="color:var(--muted);">处理位置</small><div style="font-size:1.02rem;font-weight:680;margin-top:.32rem;color:var(--accent);">本机安全域</div></div>
  </div>
</div>"""
def render_risk_gauge(level: str, score: float = 0.0) -> str:
    levels = ["RETAKE", "LOCAL_REVIEW", "REFERRAL", "PRIORITY_REFERRAL"]
    current = levels.index(level) if level in levels else 0
    labels = ["重拍", "基层评估", "专科转诊", "优先转诊"]
    pieces = []
    for idx, label in enumerate(labels):
        active = idx == current
        color = RISK_COLORS.get(level, "#79c8b8") if active else "var(--track)"
        text_color = "var(--text)" if active else "var(--muted-2)"
        weight = "700" if active else "500"
        pieces.append(
            f'<div style="flex:1;min-width:0;"><div style="height:5px;border-radius:8px;background:{color};"></div>'
            f'<div style="margin-top:8px;color:{text_color};font-size:11px;font-weight:{weight};">{label}</div></div>'
        )
    return f"""
<div class="dg-card">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;">
    <div><div class="dg-eyebrow">风险路径</div><div class="dg-card-title">{escape(RISK_LABELS_ZH.get(level, level))}</div></div>
    <div style="color:var(--muted);font-size:12px;">图像质量 {score:.0%}</div>
  </div>
  <div style="display:flex;gap:8px;margin-top:22px;">{''.join(pieces)}</div>
</div>"""


def render_triage_tree(current_level: str | None = None) -> str:
    steps = [
        ("01", "图像质量", "确认分析条件"), ("02", "视觉证据", "提取候选与可信度"),
        ("03", "本地规则", "形成风险分级"), ("04", "照护路径", "给出下一步行动"),
    ]
    cards = "".join(
        f'<div style="flex:1;min-width:110px;padding:12px 13px;border-left:1px solid var(--border);">'
        f'<div style="color:var(--accent);font-size:10px;font-weight:750;letter-spacing:.1em;">{n}</div>'
        f'<div style="color:var(--text);font-size:13px;font-weight:650;margin:5px 0 3px;">{title}</div>'
        f'<div style="color:var(--muted);font-size:11px;">{desc}</div></div>'
        for n, title, desc in steps
    )
    return f'<div class="dg-card" style="display:flex;align-items:stretch;padding:10px 8px;">{cards}</div>'


def render_candidate_radar(predictions: list[dict], labels_zh: dict | None = None) -> str:
    labels_zh = labels_zh or {}
    rows = []
    for index, item in enumerate(predictions[:5]):
        raw = str(item.get("label", "未知"))
        label = escape(str(labels_zh.get(raw, labels_zh.get(raw.lower(), raw))))
        score = max(0.0, min(1.0, float(item.get("score", 0.0))))
        tone = "var(--accent-soft)" if index == 0 else "var(--muted-2)"
        name_color = "var(--text)" if index == 0 else "var(--muted)"
        weight = "680" if index == 0 else "520"
        rows.append(f"""
<div style="display:grid;grid-template-columns:minmax(92px,1.05fr) minmax(120px,2.5fr) 48px;align-items:center;gap:12px;margin-top:13px;">
  <div style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:{name_color};font-size:12px;font-weight:{weight};">{label}</div>
  <div style="height:7px;border-radius:99px;background:var(--track);overflow:hidden;"><div style="width:{score * 100:.2f}%;height:100%;border-radius:inherit;background:{tone};"></div></div>
  <div style="text-align:right;color:{tone};font-variant-numeric:tabular-nums;font-size:12px;">{score:.1%}</div>
</div>""")
    empty = '<p class="dg-muted">暂无候选结果</p>'
    return f"""
<div class="dg-card"><div class="dg-eyebrow">多模态候选</div><div class="dg-card-title">相对匹配分布</div>
{''.join(rows) if rows else empty}
<div style="margin-top:15px;color:var(--muted);font-size:10px;">候选分数用于辅助筛查，不等同于临床确诊概率</div></div>"""


def render_evidence_graph(analysis: dict | None, labels_zh: dict | None = None) -> str:
    labels_zh, analysis = labels_zh or {}, analysis or {}
    predictions = analysis.get("visual", {}).get("top_predictions", [])
    top = predictions[0] if predictions else {}
    raw = str(top.get("label", ""))
    top_name = escape(str(labels_zh.get(raw, labels_zh.get(raw.lower(), raw or "待分析"))))
    level = str(analysis.get("triage", {}).get("level", "待生成"))
    nodes = [
        ("图像+病例", top_name, f"首位候选 · {float(top.get('score', 0)):.1%}"),
        ("本地决策", escape(RISK_LABELS_ZH.get(level, level)), "确定性规则"),
        ("指南检索", f"{len(analysis.get('guidelines', []))} 条依据", "本地来源绑定"),
        ("行动建议", "照护路径", "由医生综合判断"),
    ]
    rendered = []
    for idx, (eyebrow, title, note) in enumerate(nodes):
        rendered.append(f"""
<div style="flex:1;min-width:125px;padding:14px;border:1px solid var(--border);border-radius:13px;background:var(--panel-soft);">
  <div style="color:var(--muted);font-size:10px;">{eyebrow}</div>
  <div style="color:var(--text);font-size:13px;font-weight:680;margin:6px 0 4px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{title}</div>
  <div style="color:var(--muted-2);font-size:10px;">{note}</div>
</div>""")
        if idx < len(nodes) - 1:
            rendered.append('<div style="align-self:center;color:var(--arrow);">→</div>')
    return f'<div class="dg-card"><div class="dg-eyebrow">证据链</div><div style="display:flex;gap:9px;align-items:stretch;margin-top:12px;">{"".join(rendered)}</div></div>'


def render_privacy_panel(privacy: dict | None = None) -> str:
    privacy = privacy or {}
    fields = [
        ("原始图像", bool(privacy.get("raw_image_sent", False)), False),
        ("本地文件路径", bool(privacy.get("local_path_sent", False)), False),
        ("身份信息", bool(privacy.get("identity_sent", False)), False),
        ("脱敏视觉摘要", bool(privacy.get("visual_evidence_sent", True)), True),
    ]
    rows = []
    for name, sent, allowed in fields:
        safe = sent if allowed else not sent
        status = "允许" if allowed and sent else "未外发" if safe else "异常"
        color = "#79c8b8" if safe else "#d66b73"
        rows.append(
            f'<div style="display:flex;align-items:center;justify-content:space-between;padding:11px 0;border-bottom:1px solid var(--track);">'
            f'<span style="color:var(--muted);font-size:12px;">{name}</span><span style="color:{color};font-size:11px;font-weight:680;">● {status}</span></div>'
        )
    return f"""
<div style="padding:1.05rem 1.1rem;border:1px solid var(--border);border-radius:16px;background:var(--panel);color:var(--text);">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.25rem;">
    <strong style="font-size:.92rem;">数据边界</strong><span style="font-size:.67rem;color:var(--accent);padding:.25rem .5rem;border:1px solid var(--border);border-radius:99px;">本地优先</span>
  </div>{''.join(rows)}
  <div style="margin-top:.8rem;color:var(--muted);font-size:.72rem;line-height:1.6;">云模型仅接收通过隐私检查的结构化文本。</div>
</div>"""
