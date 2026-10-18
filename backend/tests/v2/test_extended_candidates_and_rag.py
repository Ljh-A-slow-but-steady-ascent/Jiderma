import ast
from pathlib import Path

from backend.app.services.dermfm_candidate_sets import (
    AUTHOR_ONTOLOGY_EQUIVALENTS,
    EXTENDED_CANDIDATE_SET_ID,
    EXTENDED_CLASSNAMES,
    DISPLAY_LABELS_ZH,
    LABELS_ZH,
    OPEN_VOCABULARY_ADDITIONS,
    display_label_zh,
)
from backend.app.services.rag.retriever import LocalRagRetriever


def _author_derm1m_labels() -> set[str]:
    path = Path("third_party/DermFM-Zero/src/open_clip/zero_shot_metadata.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(getattr(target, "id", "") == "DERM1M_CLASSNAMES" for target in node.targets):
            return {str(item).lower() for item in ast.literal_eval(node.value)}
    raise AssertionError("DERM1M_CLASSNAMES not found")


def test_extended_candidate_profile_has_60_bilingual_labels():
    assert EXTENDED_CANDIDATE_SET_ID == "dermfm_extended_60_zh_en_v1"
    assert len(EXTENDED_CLASSNAMES) == 60
    assert len(set(item.lower() for item in EXTENDED_CLASSNAMES)) == 60
    assert set(EXTENDED_CLASSNAMES) == set(LABELS_ZH)
    assert {
        "eczema",
        "atopic dermatitis",
        "urticaria",
        "tinea pedis",
        "herpes zoster",
        "actinic keratosis",
        "basal cell carcinoma",
        "squamous cell carcinoma",
        "melanoma",
        "stevens-johnson syndrome",
    } <= set(EXTENDED_CLASSNAMES)


def test_only_declared_open_vocabulary_terms_are_absent_from_author_list():
    author_labels = _author_derm1m_labels()
    absent = {
        item
        for item in EXTENDED_CLASSNAMES
        if item.lower() not in author_labels
        and AUTHOR_ONTOLOGY_EQUIVALENTS.get(item, "").lower() not in author_labels
    }
    assert absent == set(OPEN_VOCABULARY_ADDITIONS)


def test_ham7_presentation_labels_are_all_chinese():
    expected = {
        "actinic keratosis": "日光性角化病",
        "basal cell carcinoma": "基底细胞癌",
        "benign keratosis": "良性角化性病变",
        "dermatofibroma": "皮肤纤维瘤",
        "melanoma": "黑色素瘤",
        "nevus": "色素痣",
        "vascular": "血管性病变",
    }
    assert {label: display_label_zh(label) for label in expected} == expected
    assert all(label in DISPLAY_LABELS_ZH for label in expected)


def test_authoritative_rag_covers_every_presented_condition():
    retriever = LocalRagRetriever()
    expected_documents = {
        "actinic keratosis": "GUIDE_AAD_ACTINIC_KERATOSIS",
        "basal cell carcinoma": "GUIDE_AAD_BASAL_CELL_CARCINOMA",
        "benign keratosis": "GUIDE_DERMNET_BENIGN_KERATOSIS",
        "dermatofibroma": "GUIDE_DERMNET_DERMATOFIBROMA",
        "melanoma": "GUIDE_AAD_MELANOMA",
        "nevus": "GUIDE_AAD_MELANOCYTIC_NEVUS",
        "vascular": "GUIDE_DERMNET_VASCULAR_LESIONS",
    }
    for query, document_id in expected_documents.items():
        ids = {item["document_id"] for item in retriever.search(query, top_k=3)}
        assert document_id in ids


def test_rag_top_k_prefers_distinct_source_documents():
    results = LocalRagRetriever().search("黑色素瘤 变化 出血 转诊", top_k=3)
    assert len({item["document_id"] for item in results}) == len(results)


def test_bilingual_rag_returns_high_relevance_authoritative_sources():
    retriever = LocalRagRetriever()
    cases = {
        "黑色素瘤 边界不规则 快速变大 转诊": {"GUIDE_AAD_MELANOMA", "GUIDE_NICE_NG12_SKIN"},
        "足癣 体癣 瘙痒 环形鳞屑": {"GUIDE_CDC_FUNGAL_SCABIES"},
        "带状疱疹 水疱 疼痛 免疫抑制": {"GUIDE_CDC_ZOSTER"},
        "PRIORITY_REFERRAL basal cell carcinoma 基底细胞癌 squamous cell carcinoma 鳞状细胞癌 风险分级 转诊": {"GUIDE_NICE_NG12_SKIN"},
    }
    for query, expected_documents in cases.items():
        top = retriever.search(query, top_k=1)[0]
        assert top["document_id"] in expected_documents
        assert top["score"] >= 0.45
        assert str(top["source"]).startswith("https://")


def test_rag_evidence_is_traceable_and_fail_closed():
    result = LocalRagRetriever().search("黑色素瘤 活检 转诊", top_k=2)
    assert result
    for item in result:
        assert item["evidence_type"] in {
            "风险依据", "鉴别依据", "检查依据", "转诊依据", "冲突证据", "信息缺口"
        }
        assert item["evidence_status"] in {"充分", "当前知识库证据不足"}
        assert set(item["citation"]) == {
            "document", "organization", "year", "section", "page", "version"
        }
        assert item["query"]
