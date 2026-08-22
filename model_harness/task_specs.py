from __future__ import annotations

from copy import deepcopy
from typing import Any


TASK_SPEC_SCHEMA_VERSION = "0.1"

FAMILY_DETAILS: dict[str, dict[str, str]] = {
    "image_classification": {
        "label": "整张图片分类",
        "output": "为每张图片输出一个类别",
    },
    "ocr": {
        "label": "OCR 文字识别",
        "output": "输出图片中的文字内容",
    },
    "object_detection": {
        "label": "目标检测与定位",
        "output": "输出目标类别与边界框坐标",
    },
    "segmentation": {
        "label": "图像分割",
        "output": "输出目标或区域的像素级掩码",
    },
    "audio_classification": {
        "label": "语音分类 / 关键词识别",
        "output": "为每段音频输出一个类别",
    },
    "asr": {
        "label": "语音识别 / ASR",
        "output": "把语音或录音转写为文字",
    },
    "speech_synthesis": {
        "label": "语音合成 / TTS",
        "output": "把文本合成为指定音色的语音",
    },
    "tabular_classification": {
        "label": "表格分类",
        "output": "为每行结构化数据输出一个类别",
    },
    "tabular_regression": {
        "label": "表格数值预测",
        "output": "为每行样本输出一个数值",
    },
    "time_series_forecasting": {
        "label": "时序预测",
        "output": "根据历史序列预测未来一个或多个数值",
    },
    "anomaly_detection": {
        "label": "异常检测",
        "output": "输出是否异常、异常分数或异常位置",
    },
    "text_classification": {
        "label": "文本分类",
        "output": "为每段文本输出一个类别",
    },
    "named_entity_recognition": {
        "label": "命名实体识别 / NER",
        "output": "输出文本中的实体、类型与位置",
    },
    "classification": {
        "label": "分类",
        "output": "为每个输入输出一个类别",
    },
    "regression": {
        "label": "数值预测",
        "output": "为每个输入输出一个数值",
    },
    "custom": {
        "label": "其他专用模型能力",
        "output": "按你明确的输入、输出与验收形式生成结果",
    },
}

TASK_FAMILY_VALUES = tuple(FAMILY_DETAILS)

FAMILY_ALIASES = {
    "classification": "classification",
    "image_classification": "image_classification",
    "image-classification": "image_classification",
    "ocr": "ocr",
    "text_recognition": "ocr",
    "text-recognition": "ocr",
    "detection": "object_detection",
    "object_detection": "object_detection",
    "object-detection": "object_detection",
    "segmentation": "segmentation",
    "image_segmentation": "segmentation",
    "image-segmentation": "segmentation",
    "semantic_segmentation": "segmentation",
    "semantic-segmentation": "segmentation",
    "instance_segmentation": "segmentation",
    "instance-segmentation": "segmentation",
    "audio_classification": "audio_classification",
    "audio-classification": "audio_classification",
    "keyword_spotting": "audio_classification",
    "keyword-spotting": "audio_classification",
    "asr": "asr",
    "speech_recognition": "asr",
    "speech-recognition": "asr",
    "automatic_speech_recognition": "asr",
    "automatic-speech-recognition": "asr",
    "speech_to_text": "asr",
    "speech-to-text": "asr",
    "transcription": "asr",
    "speech_synthesis": "speech_synthesis",
    "speech-synthesis": "speech_synthesis",
    "text_to_speech": "speech_synthesis",
    "text-to-speech": "speech_synthesis",
    "tts": "speech_synthesis",
    "tabular_classification": "tabular_classification",
    "tabular-classification": "tabular_classification",
    "regression": "regression",
    "tabular_regression": "tabular_regression",
    "tabular-regression": "tabular_regression",
    "time_series_forecasting": "time_series_forecasting",
    "time-series-forecasting": "time_series_forecasting",
    "timeseries_forecasting": "time_series_forecasting",
    "forecasting": "time_series_forecasting",
    "anomaly_detection": "anomaly_detection",
    "anomaly-detection": "anomaly_detection",
    "outlier_detection": "anomaly_detection",
    "outlier-detection": "anomaly_detection",
    "text_classification": "text_classification",
    "text-classification": "text_classification",
    "nlp_classification": "text_classification",
    "nlp-classification": "text_classification",
    "named_entity_recognition": "named_entity_recognition",
    "named-entity-recognition": "named_entity_recognition",
    "ner": "named_entity_recognition",
    "entity_extraction": "named_entity_recognition",
    "entity-extraction": "named_entity_recognition",
    "custom": "custom",
    "other": "custom",
}


def normalize_family(value: Any) -> str | None:
    selected = str(value or "").strip().lower()
    return FAMILY_ALIASES.get(selected)


def capability_for_family(
    family: str,
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = deepcopy(current or {})
    result["family"] = family
    if family == "image_classification":
        result.update({"modality": "image", "objective": "classification"})
    elif family == "ocr":
        result.update({"modality": "image", "objective": "ocr"})
    elif family == "object_detection":
        result.update({"modality": "image", "objective": "object_detection"})
    elif family == "segmentation":
        result.update({"modality": "image", "objective": "segmentation"})
    elif family == "audio_classification":
        result.update({"modality": "audio", "objective": "classification"})
    elif family == "asr":
        result.update({"modality": "audio", "objective": "speech_recognition"})
    elif family == "speech_synthesis":
        result.update({"modality": "audio", "objective": "speech_synthesis"})
    elif family == "tabular_classification":
        result.update({"modality": "tabular", "objective": "classification"})
    elif family == "tabular_regression":
        result.update({"modality": "tabular", "objective": "regression"})
    elif family == "time_series_forecasting":
        result.update({"modality": "time_series", "objective": "forecasting"})
    elif family == "text_classification":
        result.update({"modality": "text", "objective": "classification"})
    elif family == "named_entity_recognition":
        result.update(
            {"modality": "text", "objective": "named_entity_recognition"}
        )
    elif family == "anomaly_detection":
        result.setdefault("modality", "specialist")
        result["objective"] = "anomaly_detection"
    elif family in {"classification", "regression"}:
        result.setdefault("modality", "specialist")
        result["objective"] = family
    elif family == "custom":
        result.setdefault("modality", "specialist")
        result["objective"] = "custom"
    return result


def build_task_spec_revision(
    *,
    task_id: str,
    revision: int,
    name: str,
    business_goal: str,
    capability_request: dict[str, Any],
    created_at_utc: str,
    source: str,
    supersedes_revision: int | None,
    user_note: str | None = None,
) -> dict[str, Any]:
    capability = deepcopy(capability_request)
    decision = capability_decision(name, business_goal, capability)
    revision_id = f"{task_id}:spec:r{revision}"
    return {
        "schema_version": TASK_SPEC_SCHEMA_VERSION,
        "revision_id": revision_id,
        "task_id": task_id,
        "revision": revision,
        "supersedes_revision": supersedes_revision,
        "name": name,
        "business_goal": business_goal,
        "capability_request": capability,
        "capability_decision": decision,
        "source": source,
        "user_note": user_note,
        "created_at_utc": created_at_utc,
    }


def capability_decision(
    name: str,
    business_goal: str,
    capability_request: dict[str, Any],
) -> dict[str, Any]:
    text = f"{name} {business_goal}".strip().lower()
    explicit_family = normalize_family(capability_request.get("family"))
    explicit = explicit_family
    modality = str(capability_request.get("modality", "")).strip().lower()
    objective = str(capability_request.get("objective", "")).strip().lower()
    if explicit is None:
        explicit = _family_from_capability(modality, objective)

    strong_families: set[str] = set()
    reason_codes: list[str] = []
    looks_audio = _looks_audio(text, modality)
    looks_image = _looks_image(text, modality)
    looks_tabular = _looks_tabular(text, modality)
    looks_text = _looks_text(text, modality)

    asr_intent = _contains_any(
        text,
        "asr",
        "speech recognition",
        "speech-to-text",
        "speech to text",
        "语音识别",
        "语音转写",
        "语音转录",
        "音频转写",
        "音频转录",
        "录音转写",
        "录音转录",
        "语音听写",
    ) or (
        looks_audio
        and _contains_any(text, "转成文字", "转为文字", "转文字", "转写", "转录")
    )
    if asr_intent:
        strong_families.add("asr")
        reason_codes.append("text_mentions_speech_transcription")

    if _contains_any(
        text,
        "tts",
        "text to speech",
        "text-to-speech",
        "语音合成",
        "声音克隆",
        "音色克隆",
        "训练自己的声音",
        "训练我的声音",
        "克隆我的声音",
        "文本转语音",
        "文字转语音",
    ):
        strong_families.add("speech_synthesis")
        reason_codes.append("text_mentions_speech_synthesis")

    keyword_intent = looks_audio and _contains_any(
        text,
        "关键词识别",
        "关键词分类",
        "唤醒词",
        "声音分类",
        "语音分类",
        "keyword spotting",
        "wake word",
    )
    if keyword_intent:
        strong_families.add("audio_classification")
        reason_codes.append("text_mentions_keyword_spotting")

    ocr_intent = _contains_any(
        text,
        "ocr",
        "图片文字识别",
        "图像文字识别",
        "扫描件识别",
        "票据识别",
        "文字识别",
        "文本识别",
        "字符识别",
        "读取文字",
        "提取文字",
        "识别文字",
    ) or (
        not looks_audio and _contains_any(text, "转成文字", "转为文字")
    )
    if ocr_intent:
        strong_families.add("ocr")
        reason_codes.append("text_mentions_ocr")

    if _contains_any(
        text,
        "目标检测",
        "object detection",
        "边界框",
        "bbox",
        "框出",
        "坐标",
        "定位零件",
        "定位缺陷",
    ):
        strong_families.add("object_detection")
        reason_codes.append("text_mentions_detection_output")

    if _contains_any(
        text,
        "图像分割",
        "语义分割",
        "实例分割",
        "缺陷分割",
        "像素级",
        "掩码",
        "segmentation",
    ):
        strong_families.add("segmentation")
        reason_codes.append("text_mentions_segmentation_output")

    if _contains_any(
        text,
        "异常检测",
        "异常识别",
        "异常分数",
        "离群检测",
        "outlier detection",
        "anomaly detection",
    ):
        strong_families.add("anomaly_detection")
        reason_codes.append("text_mentions_anomaly_output")

    if _contains_any(
        text,
        "命名实体",
        "实体识别",
        "实体抽取",
        "named entity",
        " ner",
        "ner ",
    ):
        strong_families.add("named_entity_recognition")
        reason_codes.append("text_mentions_named_entities")

    forecasting_intent = _contains_any(
        text,
        "时间序列预测",
        "时序预测",
        "销量预测",
        "需求预测",
        "forecasting",
        "forecast",
    ) or (
        _contains_any(text, "预测", "预估") and _looks_time_series(text, modality)
    )
    if forecasting_intent:
        strong_families.add("time_series_forecasting")
        reason_codes.append("text_mentions_forecasting_output")

    if _contains_any(
        text,
        "分类",
        "类别",
        "区分",
        "合格不合格",
        "是否合格",
        "有无缺陷",
    ):
        if looks_audio:
            selected = "audio_classification"
        elif looks_image:
            selected = "image_classification"
        elif looks_tabular:
            selected = "tabular_classification"
        elif looks_text:
            selected = "text_classification"
        else:
            selected = "classification"
        strong_families.add(selected)
        reason_codes.append("text_mentions_classification_output")

    if not forecasting_intent and _contains_any(
        text,
        "回归",
        "数值预测",
        "预测价格",
        "预测温度",
        "预测寿命",
        "预测分数",
        "评分预测",
        "连续值",
    ):
        selected = "tabular_regression" if looks_tabular else "regression"
        strong_families.add(selected)
        reason_codes.append("text_mentions_regression_output")

    generic_visual_recognition = looks_image and _contains_any(
        text,
        "识别",
        "检测",
        "判断",
        "看懂",
    )
    if explicit_family:
        if strong_families and not _family_compatible(
            explicit_family,
            strong_families,
        ):
            reason_codes.append("explicit_family_overrides_ambiguous_text")
        return _resolved(
            explicit_family,
            "explicit_family",
            1.0,
            reason_codes,
        )
    conflicting = bool(
        explicit
        and strong_families
        and not _family_compatible(explicit, strong_families)
    )
    if conflicting:
        candidates = sorted({explicit, *strong_families}, key=_family_sort_key)
        return _clarification(
            candidates,
            "显式能力选择与业务描述不一致",
            [*reason_codes, "explicit_capability_conflicts_with_text"],
        )
    if explicit:
        return _resolved(explicit, "explicit_capability", 1.0, reason_codes)
    if len(strong_families) > 1:
        return _clarification(
            sorted(strong_families, key=_family_sort_key),
            "业务描述同时包含多种不同的输出形式",
            [*reason_codes, "multiple_output_families"],
        )
    if len(strong_families) == 1:
        inferred = next(iter(strong_families))
        if inferred == "ocr":
            return _clarification(
                ["ocr", "image_classification", "object_detection"],
                "OCR 需要确认是读取整体文字、判断文档类别还是定位文字区域",
                [*reason_codes, "ocr_output_requires_clarification"],
            )
        return _needs_confirmation(inferred, reason_codes)
    if generic_visual_recognition:
        return _clarification(
            [
                "image_classification",
                "ocr",
                "object_detection",
                "segmentation",
                "anomaly_detection",
            ],
            "“识别/检测图片”未说明是输出类别、文字、位置、掩码还是异常",
            [*reason_codes, "generic_visual_recognition"],
        )
    if looks_audio and _contains_any(text, "识别", "检测", "判断", "理解"):
        return _clarification(
            ["audio_classification", "asr", "speech_synthesis", "custom"],
            "“处理音频”未说明是输出类别、转写文字、合成语音还是其他结果",
            [*reason_codes, "generic_audio_recognition"],
        )
    if looks_tabular:
        return _clarification(
            [
                "tabular_classification",
                "tabular_regression",
                "time_series_forecasting",
                "anomaly_detection",
                "custom",
            ],
            "表格或结构化数据任务未说明是输出类别、数值、未来序列还是异常",
            [*reason_codes, "generic_tabular_task"],
        )
    if looks_text:
        return _clarification(
            ["text_classification", "named_entity_recognition", "custom"],
            "文本任务未说明是输出类别、实体还是其他结构",
            [*reason_codes, "generic_text_task"],
        )
    return _clarification(
        ["classification", "regression", "custom"],
        "尚未说明模型要接收什么、输出什么",
        [*reason_codes, "missing_input_output_definition"],
    )


def _family_from_capability(modality: str, objective: str) -> str | None:
    if objective in {"ocr", "text_recognition", "text-recognition"}:
        return "ocr"
    if objective in {"detection", "object_detection", "object-detection"}:
        return "object_detection"
    if objective in {
        "segmentation",
        "image_segmentation",
        "image-segmentation",
        "semantic_segmentation",
        "instance_segmentation",
    }:
        return "segmentation"
    if objective in {
        "asr",
        "speech_recognition",
        "speech-recognition",
        "speech_to_text",
        "speech-to-text",
        "transcription",
    }:
        return "asr"
    if objective in {
        "tts",
        "speech_synthesis",
        "speech-synthesis",
        "text_to_speech",
        "text-to-speech",
    }:
        return "speech_synthesis"
    if objective in {
        "forecasting",
        "time_series_forecasting",
        "time-series-forecasting",
    }:
        return "time_series_forecasting"
    if objective in {
        "anomaly_detection",
        "anomaly-detection",
        "outlier_detection",
        "outlier-detection",
    }:
        return "anomaly_detection"
    if objective in {
        "named_entity_recognition",
        "named-entity-recognition",
        "ner",
        "entity_extraction",
    }:
        return "named_entity_recognition"
    if objective == "classification":
        if modality in {"audio", "speech"}:
            return "audio_classification"
        if modality in {"image", "vision", "cv"}:
            return "image_classification"
        if modality in {"text", "nlp", "document"}:
            return "text_classification"
        if modality in {"tabular", "table", "csv"}:
            return "tabular_classification"
        return "classification"
    if objective == "regression":
        if modality in {"time_series", "time-series", "timeseries", "sequence"}:
            return "time_series_forecasting"
        return "tabular_regression" if modality in {"tabular", "table", "csv"} else "regression"
    if objective in {"custom", "other"}:
        return "custom"
    return None


def _family_compatible(explicit: str, inferred: set[str]) -> bool:
    if explicit in inferred:
        return True
    groups = (
        {
            "classification",
            "image_classification",
            "audio_classification",
            "text_classification",
            "tabular_classification",
        },
        {"regression", "tabular_regression", "time_series_forecasting"},
    )
    return any(explicit in group and inferred <= group for group in groups)


def _resolved(
    family: str,
    source: str,
    confidence: float,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "status": "resolved",
        "selected_family": family,
        "source": source,
        "confidence": confidence,
        "reason_codes": reason_codes,
        "question": None,
        "candidates": [_candidate(family)],
    }


def _needs_confirmation(
    family: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "status": "needs_confirmation",
        "selected_family": family,
        "source": "business_goal",
        "confidence": 0.82,
        "reason_codes": reason_codes,
        "question": "我已形成一个候选任务规格。请确认输出形式，或选择其他能力。",
        "candidates": [_candidate(family)],
    }


def _clarification(
    families: list[str],
    reason: str,
    reason_codes: list[str],
) -> dict[str, Any]:
    return {
        "status": "needs_clarification",
        "selected_family": None,
        "source": "ambiguous",
        "confidence": 0.0,
        "reason_codes": reason_codes,
        "question": f"{reason}。请选择你希望模型的唯一输出形式。",
        "candidates": [_candidate(family) for family in families],
    }


def _candidate(family: str) -> dict[str, str]:
    details = FAMILY_DETAILS.get(family, {"label": family, "output": family})
    return {"family": family, **details}


def _family_sort_key(family: str) -> tuple[int, str]:
    order = {
        "image_classification": 0,
        "ocr": 1,
        "object_detection": 2,
        "segmentation": 3,
        "audio_classification": 4,
        "asr": 5,
        "speech_synthesis": 6,
        "tabular_classification": 7,
        "tabular_regression": 8,
        "time_series_forecasting": 9,
        "anomaly_detection": 10,
        "text_classification": 11,
        "named_entity_recognition": 12,
        "classification": 13,
        "regression": 14,
        "custom": 15,
    }
    return order.get(family, 99), family


def _contains_any(text: str, *needles: str) -> bool:
    return any(needle in text for needle in needles)


def _looks_image(text: str, modality: str) -> bool:
    return modality in {"image", "vision", "cv"} or _contains_any(
        text,
        "图片",
        "图像",
        "照片",
        "视觉",
        "零件",
        "外观",
    )


def _looks_audio(text: str, modality: str) -> bool:
    return modality in {"audio", "speech"} or _contains_any(
        text,
        "语音",
        "音频",
        "声音",
        "唤醒词",
        "关键词",
    )


def _looks_tabular(text: str, modality: str) -> bool:
    return modality in {"tabular", "table", "csv"} or _contains_any(
        text,
        "表格",
        "csv",
        "excel",
        "数据表",
        "结构化数据",
        "字段",
        "每行",
    )


def _looks_text(text: str, modality: str) -> bool:
    return modality in {"text", "nlp", "document"} or _contains_any(
        text,
        "文本",
        "评论",
        "句子",
        "语料",
        "文章",
        "邮件",
        "工单",
        "合同",
        "文档",
        "nlp",
    )


def _looks_time_series(text: str, modality: str) -> bool:
    return modality in {
        "time_series",
        "time-series",
        "timeseries",
        "sequence",
    } or _contains_any(
        text,
        "时间序列",
        "时序",
        "历史序列",
        "下个月",
        "下一周",
        "未来7天",
        "未来一周",
        "未来一个月",
        "逐日",
        "每小时",
        "按天",
        "按周",
    )
