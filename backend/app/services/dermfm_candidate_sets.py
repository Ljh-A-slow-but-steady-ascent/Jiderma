"""Prompt-only candidate profiles for the frozen DermFM-Zero-Open encoder."""

from __future__ import annotations


EXTENDED_CANDIDATE_SET_ID = "dermfm_extended_60_zh_en_v1"

# Labels use the author's English ontology terms whenever available. Erysipelas,
# seborrheic dermatitis and toxic epidermal necrolysis are open-vocabulary additions.
EXTENDED_CLASSNAMES = (
    "eczema",
    "atopic dermatitis",
    "allergic contact dermatitis",
    "irritant contact dermatitis",
    "urticaria",
    "insect bite",
    "neurodermatitis",
    "tinea pedis",
    "tinea corporis",
    "tinea cruris",
    "onychomycosis",
    "tinea versicolor",
    "folliculitis",
    "impetigo",
    "cellulitis",
    "erysipelas",
    "herpes zoster",
    "herpes simplex virus",
    "verruca vulgaris",
    "flat wart",
    "acne vulgaris",
    "seborrheic dermatitis",
    "actinic keratosis",
    "seborrheic keratosis",
    "nevus",
    "miliaria",
    "scabies",
    "psoriasis",
    "rosacea",
    "vitiligo",
    "alopecia areata",
    "pityriasis rosea",
    "hand foot and mouth disease",
    "molluscum contagiosum",
    "candidiasis",
    "melasma",
    "dermatofibroma",
    "hemangioma",
    "pyogenic granuloma",
    "epidermal cyst",
    "basal cell carcinoma",
    "squamous cell carcinoma",
    "melanoma",
    "Bowen's disease",
    "lentigo maligna melanoma",
    "merkel cell carcinoma",
    "cutaneous t cell lymphoma",
    "cutaneous b-cell lymphoma",
    "Kaposi's sarcoma of skin",
    "metastatic carcinoma",
    "stevens-johnson syndrome",
    "toxic epidermal necrolysis",
    "acute generalized exanthematous pustulosis",
    "pemphigus vulgaris",
    "bullous pemphigoid",
    "eczema herpeticum",
    "staphylococcal scalded skin syndrome",
    "pyoderma gangrenosum",
    "leukocytoclastic vasculitis",
    "urticarial vasculitis",
)

LABELS_ZH = {
    "eczema": "湿疹",
    "atopic dermatitis": "特应性皮炎",
    "allergic contact dermatitis": "过敏性接触性皮炎",
    "irritant contact dermatitis": "刺激性接触性皮炎",
    "urticaria": "荨麻疹",
    "insect bite": "虫咬皮炎",
    "neurodermatitis": "神经性皮炎",
    "tinea pedis": "足癣",
    "tinea corporis": "体癣",
    "tinea cruris": "股癣",
    "onychomycosis": "甲癣",
    "tinea versicolor": "花斑糠疹",
    "folliculitis": "毛囊炎",
    "impetigo": "脓疱疮",
    "cellulitis": "蜂窝织炎",
    "erysipelas": "丹毒",
    "herpes zoster": "带状疱疹",
    "herpes simplex virus": "单纯疱疹",
    "verruca vulgaris": "寻常疣",
    "flat wart": "扁平疣",
    "acne vulgaris": "寻常痤疮",
    "seborrheic dermatitis": "脂溢性皮炎",
    "actinic keratosis": "日光性角化病",
    "seborrheic keratosis": "脂溢性角化病",
    "nevus": "色素痣",
    "miliaria": "痱子",
    "scabies": "疥疮",
    "psoriasis": "银屑病",
    "rosacea": "玫瑰痤疮",
    "vitiligo": "白癜风",
    "alopecia areata": "斑秃",
    "pityriasis rosea": "玫瑰糠疹",
    "hand foot and mouth disease": "手足口病",
    "molluscum contagiosum": "传染性软疣",
    "candidiasis": "皮肤念珠菌病",
    "melasma": "黄褐斑",
    "dermatofibroma": "皮肤纤维瘤",
    "hemangioma": "血管瘤",
    "pyogenic granuloma": "化脓性肉芽肿",
    "epidermal cyst": "表皮囊肿",
    "basal cell carcinoma": "基底细胞癌",
    "squamous cell carcinoma": "鳞状细胞癌",
    "melanoma": "黑色素瘤",
    "Bowen's disease": "Bowen病（鳞癌原位病变）",
    "lentigo maligna melanoma": "雀斑样痣型黑色素瘤",
    "merkel cell carcinoma": "Merkel细胞癌",
    "cutaneous t cell lymphoma": "皮肤T细胞淋巴瘤",
    "cutaneous b-cell lymphoma": "皮肤B细胞淋巴瘤",
    "Kaposi's sarcoma of skin": "皮肤Kaposi肉瘤",
    "metastatic carcinoma": "皮肤转移癌",
    "stevens-johnson syndrome": "Stevens-Johnson综合征",
    "toxic epidermal necrolysis": "中毒性表皮坏死松解症",
    "acute generalized exanthematous pustulosis": "急性泛发性发疹性脓疱病",
    "pemphigus vulgaris": "寻常型天疱疮",
    "bullous pemphigoid": "大疱性类天疱疮",
    "eczema herpeticum": "疱疹性湿疹",
    "staphylococcal scalded skin syndrome": "葡萄球菌性烫伤样皮肤综合征",
    "pyoderma gangrenosum": "坏疽性脓皮病",
    "leukocytoclastic vasculitis": "白细胞碎裂性血管炎",
    "urticarial vasculitis": "荨麻疹性血管炎",
}

# Presentation aliases include the exact HAM7 linear-head labels and common
# ontology variants. They are deliberately separate from LABELS_ZH so the
# frozen 60-class zero-shot candidate set keeps its strict one-to-one mapping.
DISPLAY_LABELS_ZH = {
    **LABELS_ZH,
    "akiec": "日光性角化病/表皮内癌",
    "actinic keratoses": "日光性角化病",
    "basal cell carcinoma": "基底细胞癌",
    "bcc": "基底细胞癌",
    "benign keratosis": "良性角化性病变",
    "benign keratosis-like lesions": "良性角化性病变",
    "bkl": "良性角化性病变",
    "dermatofibroma": "皮肤纤维瘤",
    "df": "皮肤纤维瘤",
    "melanoma": "黑色素瘤",
    "mel": "黑色素瘤",
    "nevus": "色素痣",
    "melanocytic nevus": "黑素细胞痣",
    "melanocytic nevi": "黑素细胞痣",
    "nv": "色素痣",
    "vascular": "血管性病变",
    "vascular lesion": "血管性病变",
    "vascular lesions": "血管性病变",
    "vasc": "血管性病变",
}


def display_label_zh(label: str) -> str:
    """Return a stable Chinese presentation label without changing model output."""
    raw = str(label).strip()
    return DISPLAY_LABELS_ZH.get(raw, DISPLAY_LABELS_ZH.get(raw.lower(), raw))

OPEN_VOCABULARY_ADDITIONS = frozenset(
    {"erysipelas", "seborrheic dermatitis", "toxic epidermal necrolysis"}
)

AUTHOR_ONTOLOGY_EQUIVALENTS = {
    "actinic keratosis": "actinic solar damage(actinic keratosis)",
    "seborrheic keratosis": "seborrheic keratoses",
    "epidermal cyst": "epidermoid cyst",
}

assert len(EXTENDED_CLASSNAMES) == 60
assert set(EXTENDED_CLASSNAMES) == set(LABELS_ZH)
