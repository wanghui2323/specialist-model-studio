#!/usr/bin/env python3
"""Render a deterministic, synthetic single-line OCR fixture and optional local baseline.

This generates image/text pairs, not image-classification folders. It never calls
Studio, creates a TrainingTask, downloads a model, or changes a release gate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import shutil
import subprocess
import zipfile

from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION


SEED = 20261004
SIZE = (320, 72)
COUNTS = {"train": 180, "validation": 40, "test": 60, "challenge": 40}
ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789- "
DEFAULT_FONTS = [
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/System/Library/Fonts/Supplemental/Courier New.ttf"),
]
GATES = {
    "test": {"cer_max": 0.02, "exact_sequence_accuracy_min": 0.95},
    "challenge": {"cer_max": 0.08, "exact_sequence_accuracy_min": 0.80},
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def token(rng: random.Random, length: int, alphabet: str = ALPHABET[:36]) -> str:
    return "".join(rng.choice(alphabet) for _ in range(length))


def make_text(rng: random.Random, family_index: int, challenge: bool) -> tuple[str, str]:
    letters, digits = ALPHABET[:26], "0123456789"
    if challenge:
        cases = [
            (f"{token(rng, 4)} {token(rng, 2, letters)}-{token(rng, 4, digits)}", "heldout_pair"),
            (f"{token(rng, 2, letters)}-{token(rng, 2, digits)}-{token(rng, 4, letters)}", "heldout_triplet"),
            (f"UNIT {token(rng, 3)} {token(rng, 3, digits)}", "heldout_unit"),
            (f"REV {token(rng, 2, letters)} {token(rng, 4)}", "heldout_revision"),
        ]
    else:
        cases = [
            (f"{token(rng, 2, letters)}-{token(rng, 4)}-{token(rng, 3, digits)}", "part_number"),
            (f"LOT {token(rng, 3)}-{token(rng, 4, digits)}", "lot_number"),
            (f"QC {rng.choice(['PASS', 'HOLD'])} {token(rng, 4)}", "quality_label"),
            (f"PART {token(rng, 2, letters)}{token(rng, 3, digits)}", "part_label"),
        ]
    return cases[family_index % len(cases)]


def render_text(text: str, rng: random.Random, font_path: Path, condition: str) -> tuple[Image.Image, dict]:
    width, height = SIZE
    supersample = 2
    background = (255, 255, 255)
    canvas = Image.new("RGB", (width * supersample, height * supersample), background)
    if condition in {"background", "combined"}:
        draw = ImageDraw.Draw(canvas)
        low, high = rng.randint(219, 229), rng.randint(248, 254)
        for y in range(canvas.height):
            tone = low + round((high - low) * y / (canvas.height - 1))
            draw.line((0, y, canvas.width, y), fill=(tone, min(tone + 2, 255), min(tone + 5, 255)))
        background = (high, min(high + 2, 255), min(high + 5, 255))
    font_size = rng.choice([28, 30, 32])
    draw = ImageDraw.Draw(canvas)
    while True:
        font = ImageFont.truetype(str(font_path), font_size * supersample)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= (width - 32) * supersample:
            break
        font_size -= 1
        if font_size < 20:
            raise ValueError(f"Text cannot fit safely: {text!r}")
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (canvas.width - text_width) // 2 - bbox[0] + rng.randint(-2, 2) * supersample
    y = (canvas.height - text_height) // 2 - bbox[1] + rng.randint(-2, 2) * supersample
    ink = rng.randint(12, 36)
    draw.text((x, y), text, font=font, fill=(ink, ink, ink))
    canvas = canvas.resize(SIZE, Image.Resampling.LANCZOS)
    angle = 0.0
    if condition in {"rotation", "combined"}:
        angle = round(rng.choice([-1, 1]) * rng.uniform(1.0, 3.0), 3)
        canvas = canvas.rotate(angle, Image.Resampling.BICUBIC, expand=False, fillcolor=background)
    noise_amplitude = 0
    if condition in {"noise", "combined"}:
        noise_amplitude = 12 if condition == "noise" else 8
        pixels = []
        for pixel in canvas.getdata():
            delta = rng.randint(-noise_amplitude, noise_amplitude)
            pixels.append(tuple(max(0, min(255, channel + delta)) for channel in pixel))
        canvas.putdata(pixels)
    return canvas, {
        "condition": condition,
        "font_size_px": font_size,
        "rotation_degrees": angle,
        "noise": {"kind": "seeded_uniform_luminance", "amplitude": noise_amplitude},
        "background": "light_tinted_gradient" if condition in {"background", "combined"} else "white",
        "supersampling": supersample,
    }


def contact_sheet(output: Path, records: dict[str, list[dict]], font_path: Path) -> None:
    cols, tile_width, tile_height = 4, 332, 112
    selected = [(split, row) for split in COUNTS for row in records[split][:8]]
    sheet = Image.new("RGB", (cols * tile_width + 24, 80 + 8 * tile_height + 16), "#eef1f3")
    draw = ImageDraw.Draw(sheet)
    title = ImageFont.truetype(str(font_path), 25)
    label = ImageFont.truetype(str(font_path), 13)
    draw.text((20, 14), "SYNTHETIC SINGLE-LINE OCR | 32 preview samples", font=title, fill="#26383d")
    draw.text((20, 49), "Ground truth is the character sequence below each image. No Studio training has been run.", font=label, fill="#526268")
    for index, (split, row) in enumerate(selected):
        x, y = 12 + (index % cols) * tile_width, 80 + (index // cols) * tile_height
        with Image.open(output / split / row["image"]) as image:
            sheet.paste(image, (x, y))
        draw.text((x + 3, y + 75), f"{row['sample_id']} | {row['render']['condition']}", font=label, fill="#526268")
        draw.text((x + 3, y + 92), row["text"], font=label, fill="#172e34")
    sheet.save(output / "preview_contact_sheet.png", compress_level=9)


def edit_distance(reference: str, hypothesis: str) -> int:
    previous = list(range(len(hypothesis) + 1))
    for i, left in enumerate(reference, 1):
        current = [i]
        for j, right in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def run_baseline(output: Path, records: dict[str, list[dict]], workers: int) -> dict:
    executable = shutil.which("tesseract")
    if not executable:
        report = {"status": "not_run", "reason": "No installed tesseract executable found; no dependency was installed.", "studio_execution": False}
        write_json(output / "baseline_report.json", report)
        return report
    version_result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15)
    language_result = subprocess.run([executable, "--list-langs"], capture_output=True, text=True, timeout=15)
    languages = language_result.stdout + language_result.stderr
    if version_result.returncode or not re.search(r"(?m)^eng\s*$", languages):
        report = {"status": "not_run", "reason": "Installed tesseract did not provide a usable eng language model.", "studio_execution": False}
        write_json(output / "baseline_report.json", report)
        return report
    work = [(split, row) for split in ("validation", "test", "challenge") for row in records[split]]
    def recognize(item: tuple[str, dict]) -> dict:
        split, row = item
        command = [executable, str(output / split / row["image"]), "stdout", "-l", "eng", "--oem", "1", "--psm", "7", "-c", f"tessedit_char_whitelist={ALPHABET}"]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30)
            raw = result.stdout
            predicted = re.sub(r"\s+", " ", raw).strip()
            return {"sample_id": row["sample_id"], "split": split, "condition": row["render"]["condition"], "text": row["text"], "prediction_raw": raw, "prediction_normalized": predicted, "exit_code": result.returncode, "stderr": result.stderr.strip(), "character_edits": edit_distance(row["text"], predicted), "reference_characters": len(row["text"]), "exact_match": predicted == row["text"]}
        except subprocess.TimeoutExpired:
            return {"sample_id": row["sample_id"], "split": split, "condition": row["render"]["condition"], "text": row["text"], "prediction_raw": "", "prediction_normalized": "", "exit_code": -1, "stderr": "Recognition timed out after 30 seconds", "character_edits": len(row["text"]), "reference_characters": len(row["text"]), "exact_match": False}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        predictions = list(pool.map(recognize, work))
    write_jsonl(output / "baseline_predictions.jsonl", predictions)
    metrics = {}
    for split in ("validation", "test", "challenge"):
        rows = [row for row in predictions if row["split"] == split]
        total_chars = sum(row["reference_characters"] for row in rows)
        total_edits = sum(row["character_edits"] for row in rows)
        passed = sum(row["exact_match"] for row in rows)
        metrics[split] = {"samples": len(rows), "reference_characters": total_chars, "character_edits": total_edits, "cer": total_edits / total_chars, "exact_sequence_matches": passed, "exact_sequence_accuracy": passed / len(rows), "process_failures": sum(row["exit_code"] != 0 for row in rows)}
        if split in GATES:
            metrics[split]["meets_proposed_cer_gate"] = metrics[split]["cer"] <= GATES[split]["cer_max"]
            metrics[split]["meets_proposed_sequence_gate"] = metrics[split]["exact_sequence_accuracy"] >= GATES[split]["exact_sequence_accuracy_min"]
    language_directory = re.search(r'"([^"\n]+)"', languages)
    trained_data = Path(language_directory.group(1)) / "eng.traineddata" if language_directory else None
    report = {"status": "completed" if all(row["exit_code"] == 0 for row in predictions) else "completed_with_process_failures", "studio_execution": False, "kind": "independent_preinstalled_tesseract_baseline", "training_performed": False, "network_used": False, "executable": executable, "executable_sha256": sha256(Path(executable)), "version": version_result.stdout.splitlines()[0], "language": "eng", "language_model_sha256": sha256(trained_data) if trained_data and trained_data.is_file() else None, "parameters": {"oem": 1, "psm": 7, "character_whitelist": ALPHABET}, "normalization": "Collapse whitespace to one ASCII space and strip surrounding whitespace only; preserve case and punctuation.", "metrics": metrics, "policy": "Parameters and candidate gates were fixed before this evaluation. No training or test-based adjustment was performed. Baseline is not a Studio Run and not an end-to-end OCR claim."}
    write_json(output / "baseline_report.json", report)
    return report


def validate(output: Path, records: dict[str, list[dict]]) -> dict:
    text_ids, image_ids, pixel_ids = {}, {}, {}
    for split, rows in records.items():
        if len(rows) != COUNTS[split]:
            raise AssertionError(f"Unexpected row count for {split}")
        for row in rows:
            path = output / split / row["image"]
            if not row["text"] or set(row["text"]) - set(ALPHABET):
                raise AssertionError(f"Invalid OCR label for {row['sample_id']}")
            with Image.open(path) as image:
                image.load()
                if image.mode != "RGB" or image.size != SIZE:
                    raise AssertionError(f"Invalid rendered image for {row['sample_id']}")
                pixel_hash = hashlib.sha256(image.tobytes()).hexdigest()
            for identity, seen in ((row["text"], text_ids), (sha256(path), image_ids), (pixel_hash, pixel_ids)):
                if identity in seen:
                    raise AssertionError(f"Duplicate between {seen[identity]} and {row['sample_id']}")
                seen[identity] = row["sample_id"]
    train_characters = set("".join(row["text"] for row in records["train"]))
    if train_characters != set(ALPHABET):
        raise AssertionError(f"Training alphabet coverage is incomplete: {set(ALPHABET) - train_characters}")
    regular_families = {row["family"] for row in records["train"]}
    if any(row["family"] in regular_families for row in records["challenge"]):
        raise AssertionError("Challenge layouts must use held-out string patterns")
    return {"status": "passed", "counts": {split: len(rows) for split, rows in records.items()}, "total_images": len(image_ids), "unique_image_sha256": len(image_ids), "unique_decoded_pixel_sha256": len(pixel_ids), "unique_transcriptions": len(text_ids), "cross_split_duplicate_images": 0, "cross_split_duplicate_transcriptions": 0, "training_alphabet": "".join(char for char in ALPHABET if char in train_characters), "challenge_patterns_absent_from_training": True, "all_images_decodable_rgb": True}


def write_readme(output: Path, baseline: dict | None) -> None:
    baseline_summary = "未请求独立 OCR 基线；没有运行识别器。"
    if baseline and baseline.get("metrics"):
        baseline_summary = "\n".join(f"- {split}: CER {values['cer']:.4%}，整句准确率 {values['exact_sequence_accuracy']:.2%}，{values['samples']} 张，进程失败 {values['process_failures']}。" for split, values in baseline["metrics"].items())
    elif baseline:
        baseline_summary = baseline.get("reason", "基线未运行。")
    text = f"""# 单行 OCR：合成零件编号与短文本

这是 **image → 字符序列** 数据，不是整张图片分类。示例 `RX-K9Q8-574` 中每个字符的位置和顺序都属于答案；文件夹 `train`、`test` 等是数据划分，绝不是类别标签。

## 文件与规模

- `ocr-single-line.zip`：可供未来 OCR 导入适配器读取的完整数据包，包含四个划分及 `dataset_spec.json`。
- `train/` 180 张、`validation/` 40 张、`test/` 60 张、`challenge/` 40 张，共 320 张。
- 每个划分含 `images/*.png` 和 `annotations.jsonl`。每条标注的 `image` 相对于该标注文件所在目录，例如 `images/train-0000.png`。
- 图片为 320×72 RGB PNG，已经裁成单行；字符集合是大写 A–Z、数字 0–9、ASCII 空格和短横线。不含中文，不验证多行版面、检测、手写字或文档字段提取。
- 标注含 `sample_id`、`image`、`text`、`split`、`family`、字体编号、渲染条件及图像 SHA-256。`text` 是大小写和标点敏感的逐字符真值。
- `preview_contact_sheet.png`：32 张分层预览，标签显示在图片下方。
- `validation_report.json`：图片解码、数量、字符覆盖及跨划分重复检查。
- `manifest.json`：全部交付文件的大小与 SHA-256（除 manifest 自身与其校验文件）；`manifest.sha256` 单独校验 manifest。

## 生成来源与复现

所有文本和图像均由本仓库脚本生成，seed=`{SEED}`。没有采集用户文件、真实企业单据或互联网图片。字体取自本机 macOS 已安装的 Arial 与 Courier New；路径、名称与文件摘要见 `dataset_spec.json`，不打包或分发字体二进制。不同机器须提供合法安装的对应字体；不同字体或 Pillow 版本可能产生不同像素，须重新核对摘要。

在已安装 Pillow 的项目环境运行：

```bash
python scripts/acceptance/generate_ocr_fixtures.py \\
  --output runs/acceptance/20261004-four-scenarios/ocr \\
  --baseline
```

输出目录必须不存在或为空；脚本不会覆盖已有数据。`--font /path/Arial.ttf --font /path/Courier.ttf` 可显式选字体；`--baseline` 只调用已有 Tesseract，不安装依赖或下载模型。

训练、验证、最终测试标签及图像均唯一。挑战集固定为四种各 10 张的条件：轻旋转、亮度噪声、浅色渐变背景、组合扰动；其编号组合模板也未出现在训练集中。所有挑战字符本身已出现在训练字符集合中，测试的是组合与扰动泛化，不是未知字库。

## 候选验收口径

这些是未来接入或微调时应先确认并冻结的候选门槛，**尚未被写入或批准为 Studio 训练合同**。

| 划分 | CER 上限 | 整句准确率下限 | 用途 |
| --- | --- | --- | --- |
| validation | 不作最终发布判定 | 不作最终发布判定 | 模型选择、早停和训练期检查 |
| test | 2% | 95% | 冻结模型之后的一次最终验收 |
| challenge | 8% | 80% | 单独报告扰动与未见组合表现 |

CER = 全集字符编辑距离之和 / 真值字符数之和，包含空格和短横线；不是逐样本 CER 的简单平均。整句准确率要求整个规范化字符序列完全相同。输出规范化只折叠空白并去掉首尾空白，不纠正大小写、不把 O/0、I/1、S/5 合并。失败或超时不能跳过，应计入失败样本；按字体、长度、扰动类型分别检查错误。

## 本机独立基线

{baseline_summary}

详细参数、Tesseract 版本与语言模型摘要见 `baseline_report.json`（请求并具备识别器时生成）；逐图真值、原始输出、规范化输出与编辑距离见 `baseline_predictions.jsonl`。该基线使用预装的英文识别器，**没有进行微调，不是 Studio TrainingTask/Run，也不是 Studio 的 OCR 全流程验收**。没有根据 test/challenge 的结果调整数据、识别参数或门槛。

## 当前接入停点与用途

当前 Studio 的 OCR 目标可以进入需求研究与集成规划，但单行 OCR Recipe、配对 image/text Data Adapter、训练器和证据链尚未接通。只有接入并验证对应 OCR 适配器后，才使用页面导入本 ZIP；不要把它送入图片类别目录适配器，也不能以图片分类成功冒充文本识别成功。下一步是将这份配对数据契约接到可信 OCR 识别训练方案，先验证数据导入和小规模微调，再走独立评测及交付。

该数据只用于验证格式、工具和学习流程；合成干净文本或本机基线高分不能证明真实拍照、反光、磨损、现场字体或业务单据的识别效果。挑战集也仍然是合成数据。字体文件本身不在包内，合成图片与编号不含真实业务内容。
"""
    (output / "README.md").write_text(text, encoding="utf-8")


def package_dataset(output: Path) -> None:
    files = [output / "dataset_spec.json"]
    for split in COUNTS:
        files.extend(path for path in (output / split).rglob("*") if path.is_file())
    with zipfile.ZipFile(output / "ocr-single-line.zip", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path.relative_to(output).as_posix(), date_time=(2026, 10, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("runs/acceptance/20261004-four-scenarios/ocr"))
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--font", type=Path, action="append", default=None)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--baseline-workers", type=int, choices=(1, 2, 3, 4), default=2)
    args = parser.parse_args()
    if args.seed != SEED:
        parser.error(f"This named fixture fixes seed={SEED}; create a separately versioned fixture for a different seed.")
    fonts = args.font or DEFAULT_FONTS
    for path in fonts:
        if not path.is_file():
            parser.error(f"Font is unavailable: {path}; pass --font for a legally installed local font.")
        ImageFont.truetype(str(path), 20)
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error(f"Refusing to overwrite non-empty output directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    font_sources = []
    for index, path in enumerate(fonts):
        family, style = ImageFont.truetype(str(path), 20).getname()
        font_sources.append({"font_id": f"font-{index}", "family": family, "style": style, "path": str(path), "sha256": sha256(path), "source": "Pre-existing local system font; binary is not redistributed."})
    all_texts, records = set(), {}
    for split_index, (split, count) in enumerate(COUNTS.items()):
        (output / split / "images").mkdir(parents=True)
        rows = []
        for index in range(count):
            sample_seed = args.seed + (split_index + 1) * 1_000_000 + index
            rng = random.Random(sample_seed)
            while True:
                text, family = make_text(rng, index, split == "challenge")
                if text not in all_texts:
                    all_texts.add(text)
                    break
            # Alternate fonts by four-item block so each text/perturbation
            # family is represented with both fonts, instead of confounding
            # e.g. noise with one font and rotation with the other.
            font_index = (index // 4 + split_index) % len(fonts)
            condition = ["rotation", "noise", "background", "combined"][index % 4] if split == "challenge" else "clean"
            image, rendering = render_text(text, rng, fonts[font_index], condition)
            sample_id = f"{split}-{index:04d}"
            path = output / split / "images" / f"{sample_id}.png"
            image.save(path, compress_level=9)
            rows.append({"sample_id": sample_id, "image": f"images/{sample_id}.png", "text": text, "split": split, "synthetic": True, "sample_seed": sample_seed, "family": family, "font_id": f"font-{font_index}", "width": SIZE[0], "height": SIZE[1], "mode": "RGB", "render": rendering, "image_sha256": sha256(path)})
        write_jsonl(output / split / "annotations.jsonl", rows)
        records[split] = rows
    specification = {"schema_version": "1.0", "fixture_id": "synthetic-single-line-ocr-20261004-v1", "task": "single_line_text_recognition", "output_kind": "character_sequence", "not_image_classification": True, "seed": args.seed, "image_size": list(SIZE), "image_mode": "RGB", "alphabet": ALPHABET, "split_counts": COUNTS, "synthetic": True, "text_source": "Seeded generated part numbers and short industrial labels; no real records or downloaded images.", "font_sources": font_sources, "generator": {"relative_source": "scripts/acceptance/generate_ocr_fixtures.py", "source_sha256": sha256(Path(__file__)), "python": platform.python_version(), "pillow": PILLOW_VERSION}, "annotation_path_rule": "image is relative to its annotations.jsonl parent directory", "evaluation": {"proposed_gates": GATES, "approval_status": "proposal_only_not_a_studio_contract", "normalization": "collapse whitespace and strip; preserve case and punctuation", "cer": "micro Levenshtein edits divided by reference character count, including spaces/hyphens"}, "studio_status": {"ocr_recipe_connected": False, "ocr_adapter_connected": False, "training_performed": False, "instructions": "Do not import this archive as image-folder classification. Requires a paired image/text OCR adapter and verified OCR Recipe."}}
    write_json(output / "dataset_spec.json", specification)
    validation = validate(output, records)
    write_json(output / "validation_report.json", validation)
    contact_sheet(output, records, fonts[0])
    package_dataset(output)
    baseline = run_baseline(output, records, args.baseline_workers) if args.baseline else None
    write_readme(output, baseline)
    manifest = {"schema_version": "1.0", "fixture_id": specification["fixture_id"], "seed": args.seed, "counts": COUNTS, "validation_status": validation["status"], "font_binary_included": False, "studio_training_performed": False, "manifest_self_hash_rule": "manifest.json and manifest.sha256 are excluded from files; manifest.sha256 authenticates manifest.json separately.", "files": [{"path": path.relative_to(output).as_posix(), "size_bytes": path.stat().st_size, "sha256": sha256(path)} for path in sorted(output.rglob("*")) if path.is_file()]}
    write_json(output / "manifest.json", manifest)
    (output / "manifest.sha256").write_text(f"{sha256(output / 'manifest.json')}  manifest.json\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "counts": COUNTS, "zip_bytes": (output / "ocr-single-line.zip").stat().st_size, "zip_sha256": sha256(output / "ocr-single-line.zip"), "validation": validation["status"], "baseline_status": baseline.get("status") if baseline else "not_requested", "baseline_metrics": baseline.get("metrics") if baseline else None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
