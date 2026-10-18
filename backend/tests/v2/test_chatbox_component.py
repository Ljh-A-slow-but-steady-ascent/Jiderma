from pathlib import Path


CHATBOX = Path(__file__).resolve().parents[3] / "ui" / "chatbox_component.html"
UI_APP = Path(__file__).resolve().parents[3] / "ui" / "streamlit_app.py"
VISUALS = Path(__file__).resolve().parents[3] / "ui" / "visuals.py"
STREAMLIT_CONFIG = Path(__file__).resolve().parents[3] / ".streamlit" / "config.toml"


def test_chatbox_exposes_detail_mode_trace_and_markdown_table() -> None:
    source = CHATBOX.read_text(encoding="utf-8")

    assert 'value="detailed"' in source
    assert "detail_level:detailSelect.value" in source
    assert "function renderTrace" in source
    assert "payload.tool_calls" in source
    assert "payload.agent_trace" in source
    assert "Agent Trace" in source
    assert "隐私出境检查" in source
    assert "dg-table-wrap" in source
    assert '<textarea class="dg-input"' in source
    assert "继续询问智能助手" in source
    assert "dg-chat-ui-v2" in source
    assert "function clampPanel" in source
    assert "#dg-chatbox-host.dg-light" in source
    assert "background:var(--dg-header)" in source
    assert 'host.className = "dg-light"' in source
    assert "dg-theme\"" not in source
    assert ".dg-light .dg-code" in source


def test_ui_hides_total_pretriage_latency() -> None:
    source = UI_APP.read_text(encoding="utf-8") + VISUALS.read_text(encoding="utf-8")

    assert "预分诊总耗时" not in source
    assert "total_pretriage_latency_ms" not in source


def test_global_theme_does_not_hide_chat_composer_footer() -> None:
    source = VISUALS.read_text(encoding="utf-8")

    assert "#MainMenu,footer" not in source
    assert '[data-testid="stFooter"]' in source


def test_main_ui_is_light_only_and_has_no_removed_copy() -> None:
    app = UI_APP.read_text(encoding="utf-8")
    visuals = VISUALS.read_text(encoding="utf-8")

    assert 'st.toggle("浅色背景"' not in app
    assert "light_theme" not in app
    assert '"defaultTheme"' not in app
    assert "LIGHT_THEME_OVERRIDES" in visuals
    assert "def theme_css()" in visuals
    assert '<div class="dg-theme-light"' in visuals
    assert 'base = "light"' in STREAMLIT_CONFIG.read_text(encoding="utf-8")
    assert "医生辅助决策与病例工作台" in visuals
    assert "本地智能预分诊系统" not in visuals
    assert "病灶图片 · 仅在本地处理" not in app
    assert "当前结果由本地监督任务头生成" not in app
    assert "本地 RAG 先检索相关指南" not in app
    assert "本地视觉分析&nbsp;" not in app


def test_light_theme_components_use_theme_variables_instead_of_dark_panels() -> None:
    source = VISUALS.read_text(encoding="utf-8")
    component_source = source[source.index("def render_case_status") :]

    assert "--panel:#fff" in source
    assert "--panel-soft:#edf3f1" in source
    assert "background:var(--panel)" in component_source
    assert "background:var(--panel-soft)" in component_source
    assert "background:#11181c" not in component_source
    assert "background:rgba(10,15,18,.3)" not in component_source
    assert "background:rgba(20,28,33,.7)" not in component_source


def test_light_theme_replaces_dark_streamlit_data_views() -> None:
    app = UI_APP.read_text(encoding="utf-8")
    visuals = VISUALS.read_text(encoding="utf-8")

    assert "st.dataframe(" not in app
    assert "st.json(" not in app
    assert "render_data_table" in app
    assert "render_json_block" in app
    assert '.dg-json-shell{background:#fff' in visuals
    assert '[data-testid="stSegmentedControl"] button[aria-pressed="true"]' in visuals
