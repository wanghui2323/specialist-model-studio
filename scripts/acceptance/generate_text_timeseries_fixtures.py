#!/usr/bin/env python3
"""Generate original, reproducible NLP and forecasting review fixtures.

These are independent sklearn/seasonal-naive references, NOT Studio Runs.
No model downloads, provider calls, user data or product state are involved.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import platform
import random
import re
import zipfile
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline


SEED = 20261004
SPLITS = ("train", "validation", "test")
LABELS = {
    "logistics": {"name": "物流查询", "definition": "查询发货、运输、签收或送达情况，尚未明确提出退货、换货等另一项操作。"},
    "return_refund": {"name": "退货退款", "definition": "明确要求退货、退款、取消并退回货款，或查询退款到账。"},
    "exchange": {"name": "换货", "definition": "已收到货后明确申请更换商品、尺寸、颜色或补换配件。"},
    "product_fault": {"name": "商品故障", "definition": "描述商品功能异常、质量问题，并询问检查、维修或保修；没有明确申请退换货。"},
    "invoice": {"name": "发票", "definition": "索取、补开、查询或修改发票、抬头、税号等开票信息。"},
    "order_change": {"name": "订单修改", "definition": "发货前修改收货信息、规格、数量或订单备注，不包含修改发票信息。"},
}

# Each split is independently authored. There is no shared sentence template
# with swapped product names/IDs across train, validation and test.
TEXTS = {
    "logistics": {
        "train": [
            "付款两天了还显示待发货，什么时候能寄出？",
            "快递单号查不到运输记录，麻烦帮我看看。",
            "包裹在转运中心停了四天，有没有丢件？",
            "物流写着已经签收，可是我本人没有收到。",
            "请告诉我这一单是用哪家快递寄的。",
            "预计送达日期过了，能催一下配送吗？",
            "订单显示分两个包裹，其中一个到哪里了？",
            "快递员说找不到地址，请联系他重新派送。",
            "刚收到发货短信，但运单状态一直没有更新。",
            "我周末要出门，想查下货物能否周五送到。",
            "驿站没有我的件，系统却提示已入库。",
            "这个包裹是送上门还是放在取件柜？",
        ],
        "validation": [
            "配送轨迹最后一条还是前天的，请查一下位置。",
            "家里等了一整天没见配送员，今天还会送吗？",
            "两件商品只收到了一个快递袋，另一件是否单独发出？",
            "页面上的签收照片不是我家，能核查投递情况吗？",
            "已经下单一周，仓库那边到底出库了没有？",
            "到达本市后又被运走了，是物流中转出错了吗？",
        ],
        "test": [
            "订单一直卡在揽收中，商家实际交给快递了吗？",
            "收件通知来了却没有取件码，该到哪里取货？",
            "运输途中提示异常滞留，麻烦核实原因和新的到货时间。",
            "配送员把货放到邻居楼栋，我找不到包裹。",
            "寄出的第三天了，想知道现在走到哪个城市。",
            "我买的东西今天能派送完吗，物流预约时间已经超了。",
        ],
    },
    "return_refund": {
        "train": [
            "这件衣服不喜欢，想退掉并拿回货款。",
            "重复购买了一份，请取消多出的订单并退款。",
            "退货已经寄回，你们何时把钱退给我？",
            "商品还没用过，七天内申请退货需要什么手续？",
            "退款显示成功，但银行卡里一直没有到账。",
            "东西跟介绍不一致，我不想换，要直接退款。",
            "刚付款就发现买错了，能撤单退钱吗？",
            "我同意寄回全部商品，请发退货地址。",
            "售后退款金额少了运费，请核对一下。",
            "上次提交的退货申请被拒绝了，我想重新申请。",
            "这一单不要了，希望按原支付方式退还。",
            "货有破损，我选择退货退款，不接受补发。",
        ],
        "validation": [
            "退回的快递昨天已签收，退款还要等多久？",
            "买来后发现不适合我的需求，请办理退货。",
            "支付被扣了两次，多扣的那笔钱请退回。",
            "我决定取消购买，这个订单的款项如何返还？",
            "退单完成却只到账一部分，剩余退款在哪里？",
            "收到实物后不满意，想结束交易退回商品。",
        ],
        "test": [
            "售后单里还在审核退钱申请，什么时候可以到账？",
            "包装尚未拆开，现在申请原路退回全部金额。",
            "商家同意退货了，我应该把物品寄到哪个仓库？",
            "货款退进余额了，我需要转回当时付款的账户。",
            "不需要这套产品了，请协助取消并返还支付款。",
            "已经按要求交回商品，为什么退款流程又暂停了？",
        ],
    },
    "exchange": {
        "train": [
            "鞋子已经收到了，尺码偏小，想换大一号。",
            "寄来的外套是蓝色，我希望换成黑色。",
            "新到的杯子有裂纹，请给我换一个完整的。",
            "这台机器到手就坏了，我选择换货，不要退款。",
            "衣服吊牌还在，怎样申请同款换码？",
            "收到的是旧款，麻烦更换为我购买的新款。",
            "配件发错型号了，能把错误的换成正确的吗？",
            "货已经签收，想将双人套装换成单人款。",
            "昨天申请的换货什么时候能寄出替换商品？",
            "收到的颜色与下单不同，请办理换色。",
            "我把需要换的鞋寄回了，新鞋什么时候发？",
            "这件有明显污渍，希望更换同款全新的。",
        ],
        "validation": [
            "试穿后发现腰围太紧，能否换一条宽松些的？",
            "到手的壶盖缺了一角，我想整套换新。",
            "商品送到了，家人更喜欢另一种颜色，换货怎么操作？",
            "寄回换码的外套已到仓库，请查替换进度。",
            "签收后才发现规格错了，可以更换对应版本吗？",
            "这一套少了正确的接头，我愿意寄回错误配件换对应的。",
        ],
        "test": [
            "裤子穿着太长，保留商品的前提下想更换短一档。",
            "我已拿到货，想把浅灰款换成深灰款。",
            "替换货件一直没发出，我的换货售后何时能完成？",
            "这双鞋左右尺码不一致，请安排换一双配对的。",
            "购买的型号与收到的不符，我需要换回正确型号。",
            "新商品表面有瑕疵，我想要同款良品替换。",
        ],
    },
    "product_fault": {
        "train": [
            "电饭煲插上电没有反应，应该怎么检查？",
            "耳机左边没有声音，重连手机也没用。",
            "机器运行一会儿就自动关机，是哪里出了问题？",
            "屏幕经常闪烁，是否可以申请保修？",
            "吸尘器的吸力突然变弱了，有排查方法吗？",
            "刚买的水壶烧水时底部漏水，怎么处理故障？",
            "设备提示错误代码E3，说明书没有解释。",
            "充电一晚上仍然只有一格电，需要维修吗？",
            "洗衣机脱水时声音特别大，能安排师傅检查吗？",
            "按下开关灯亮但电机不转，请帮我判断原因。",
            "保修期内的搅拌机刀头卡住了，维修流程是什么？",
            "连接网络后一直掉线，我想先解决这个使用问题。",
        ],
        "validation": [
            "净水器不断发出报警声，滤芯才换过该怎么排查？",
            "手机支架的旋钮无法锁紧，算不算质量故障？",
            "显示器通电后黑屏，换过插座还是一样。",
            "用了两周突然停止工作，是否还在免费维修范围？",
            "电池每次充满很快耗尽，需要检测哪里？",
            "按钮按下去弹不回来，请问有没有检修办法？",
        ],
        "test": [
            "风扇启动后只响不转，想咨询检修步骤。",
            "打印出来一直是空白页，墨盒是新的，哪里可能有问题？",
            "蓝牙音箱用着用着断音，能帮忙排除故障吗？",
            "设备机身异常发烫，我需要了解保修维修渠道。",
            "扫地机器人无法回到充电座，该怎样检查传感器？",
            "保温功能不再起作用，维修需要提供哪些凭证？",
        ],
    },
    "invoice": {
        "train": [
            "这笔订单需要开电子发票，请问在哪里申请？",
            "发票抬头写错了，麻烦改成公司全称。",
            "已经填好税号，为什么还没有收到票据？",
            "可以为上个月的购买记录补开发票吗？",
            "我要增值税专用发票，需要提交哪些资料？",
            "请把电子发票重新发送到我的邮箱。",
            "开票金额与实际支付金额对不上，帮忙核实。",
            "购买时忘记选择发票，现在还能补开吗？",
            "下载发票的链接失效了，请提供新的文件。",
            "单位要求填写纳税人识别号，能修改开票信息吗？",
            "发票上的商品名称错误，是否需要重新开具？",
            "我需要纸质发票，不知道寄送方式如何选择。",
        ],
        "validation": [
            "财务说这张票的购买方信息不完整，能重开吗？",
            "电子税票已经申请三天，还没收到开票通知。",
            "个人抬头想改为公司抬头，应该如何办理？",
            "需要将两次购买分别开具票据，不能合在一张。",
            "报销要用的发票文件打不开，请再发一次。",
            "开具专票时银行账号和税号填在哪里？",
        ],
        "test": [
            "订单结束后还能下载对应的电子发票吗？",
            "税务信息有变更，尚未开出的票请用新的抬头。",
            "公司报销必须附票，请帮我补齐这单的开票材料。",
            "这张增值税发票需要红冲后重开，找哪个入口？",
            "开票页提交成功却没有邮件，能查下票号吗？",
            "发给我的票面税号少了一位，需要更正。",
        ],
    },
    "order_change": {
        "train": [
            "订单还没发货，收货地址能改一下吗？",
            "联系人手机号填错了一位，请修改配送信息。",
            "仓库尚未出库，我想把数量从一件改成两件。",
            "刚下单选错了尺寸，发货前可以调整吗？",
            "请在这笔未发出的订单上备注不要礼盒。",
            "收件人姓名写成了旧名字，麻烦改为新的。",
            "还没有打包，能将蓝色款改为白色款吗？",
            "今天搬家了，未寄出的商品请更新收件地址。",
            "同一订单的两个商品希望合并寄送，能加备注吗？",
            "下单时漏填楼栋号，请帮我补充完整地址。",
            "这单还在待处理，我想调整所选商品规格。",
            "请把未发货订单的收件电话改成备用号码。",
        ],
        "validation": [
            "目前仍是待出库状态，能修改成另一种容量吗？",
            "订单里的门牌号写反了，发走之前请更正。",
            "快递还没交给承运商，希望将收货人换成家人。",
            "想给尚未打包的商品增加一条配送备注。",
            "新订单多选了一件，出库前可以减少购买数量吗？",
            "订单创建后发现尺码选错，能在仓库处理前改掉吗？",
        ],
        "test": [
            "这单等待发货，目的地想改到我的办公地址。",
            "仓库还没开始拣货，请修改规格为大容量版。",
            "刚拍下的订单可以追加一件相同商品吗？",
            "填写收货资料时遗漏了单元号，麻烦补上。",
            "货物尚未出库，我要更新收件人的联系电话。",
            "请给新下的订单添加备注，包装时不要放价格标签。",
        ],
    },
}

CHALLENGES = [
    ("这单一直没动静，我是催一下还是直接退掉比较好？", ["logistics", "return_refund"], "clarify", "用户尚未决定催物流还是退款。"),
    ("颜色不合适，能给我换一下吗？", ["exchange", "order_change"], "clarify", "需要确认是否已经收到货，不能仅凭换字决定。"),
    ("这个东西有问题，给个解决办法。", ["product_fault", "return_refund", "exchange"], "clarify", "未说明故障表现或希望采取的售后动作。"),
    ("补一下我的信息，之前写错了。", ["invoice", "order_change"], "clarify", "不知道要改的是开票信息还是收货信息。"),
    ("货没收到，钱也没有退回来，两件事都帮我查。", ["logistics", "return_refund"], "multi_intent", "明确存在两个并行诉求。"),
    ("请给有瑕疵的商品换新，同时补开这单发票。", ["exchange", "invoice"], "multi_intent", "商品替换与开票是独立工作项。"),
    ("机器坏了，不知道该修还是该退。", ["product_fault", "return_refund"], "clarify", "不替用户选择维修或退款。"),
    ("我不需要退货，只想知道包裹送到哪里了。", ["logistics"], "negation", "明确否定退货，考查否定语义。"),
    ("地址没有写错，我要修改的是发票里的单位地址。", ["invoice"], "negation", "收货地址关键词不是实际诉求。"),
    ("这次不换商品，我想退钱。", ["return_refund"], "negation", "否定换货，明确请求退款。"),
    ("电话改好后顺便告诉我几号能送到。", ["order_change", "logistics"], "multi_intent", "修改资料和预计到货时间两个诉求。"),
    ("能不能尽快处理上次那个售后？", list(LABELS), "clarify", "缺少订单上下文和售后类型。"),
]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path: Path, rows, fields) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows), encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(path: Path, root: Path, members: list[Path]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for member in sorted(members):
            info = zipfile.ZipInfo(member.relative_to(root).as_posix(), date_time=(2026, 10, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            bundle.writestr(info, member.read_bytes())


def manifest(root: Path, scenario: str, metrics: dict) -> None:
    files = {
        path.relative_to(root).as_posix(): {"sha256": sha(path), "size_bytes": path.stat().st_size}
        for path in sorted(root.rglob("*")) if path.is_file() and path.name != "manifest.json"
    }
    write_json(root / "manifest.json", {
        "schema_version": "1.0", "scenario": scenario, "created_for_date": "2026-10-04",
        "seed": SEED, "source": "original_synthetic_fixture", "production_effectiveness_evidence": False,
        "studio_run": False, "generator": "scripts/acceptance/generate_text_timeseries_fixtures.py",
        "generator_sha256": sha(Path(__file__)), "metrics": metrics, "files": files,
        "self_hash_note": "本文件不包含自身哈希；所有其他交付文件均列入校验。",
    })


def char_bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"[\W_]+", "", text)
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def generate_nlp(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    rows = {}
    for split in SPLITS:
        values = []
        for label, sources in TEXTS.items():
            for text in sources[split]:
                values.append({"id": "txt-" + hashlib.sha256(text.encode()).hexdigest()[:12], "text": text, "label": label})
        random.Random(SEED + SPLITS.index(split)).shuffle(values)
        rows[split] = values
        write_csv(root / "data" / f"{split}.csv", values, ["id", "text", "label"])
        write_jsonl(root / "data" / f"{split}.jsonl", values)
    all_text = [row["text"] for split in SPLITS for row in rows[split]]
    assert len(all_text) == len(set(all_text)), "duplicate text across fixed splits"
    normalized = [re.sub(r"[\W_]+", "", text) for text in all_text]
    assert len(normalized) == len(set(normalized)), "punctuation-only duplicate"
    near_pairs = []
    max_similarity = 0.0
    for left_split, right_split in [("train", "validation"), ("train", "test"), ("validation", "test")]:
        for left in rows[left_split]:
            a = char_bigrams(left["text"])
            for right in rows[right_split]:
                b = char_bigrams(right["text"])
                similarity = len(a & b) / max(1, len(a | b))
                max_similarity = max(max_similarity, similarity)
                if similarity >= 0.75:
                    near_pairs.append({"left_id": left["id"], "right_id": right["id"], "similarity": similarity})
    assert not near_pairs, "near-duplicate utterances cross split boundaries"

    challenge = [{"id": f"challenge-{i:03d}", "text": text, "acceptable_labels": labels,
                  "expected_action": action, "review_note": note}
                 for i, (text, labels, action, note) in enumerate(CHALLENGES, 1)]
    write_jsonl(root / "data" / "challenge.jsonl", challenge)
    write_json(root / "labels.json", {
        "labels": LABELS,
        "single_label_policy": "明确售后动作优先于原因；收到商品后换货与发货前改订单分开。含多个明确诉求、缺上下文、否定歧义的样本进入challenge人工复核，不强行赋唯一标签。",
    })
    pipeline = Pipeline([
        ("text", TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=1, sublinear_tf=True)),
        ("classifier", LogisticRegression(C=1.0, max_iter=1000, random_state=SEED)),
    ])
    pipeline.fit([row["text"] for row in rows["train"]], [row["label"] for row in rows["train"]])
    baseline = root / "baseline"
    baseline.mkdir(exist_ok=True)
    metrics = {
        "execution_kind": "independent_local_reference", "studio_run": False,
        "pretrained_model_finetuning": False, "algorithm": "character TF-IDF (2-4 grams) + LogisticRegression C=1.0",
        "fit_split": "train_only", "hyperparameter_search": False,
        "test_policy": "固定模型后计算测试指标；未按测试结果调整数据或超参数。",
        "acceptance_gates": None, "acceptance_note": "用户尚未设定业务准出门槛；不输出通过/可发布判断。",
        "split_counts": {split: len(items) for split, items in rows.items()},
        "class_counts": {split: dict(sorted(Counter(row["label"] for row in items).items())) for split, items in rows.items()},
        "integrity": {"exact_cross_split_duplicates": 0, "normalized_cross_split_duplicates": 0,
                      "template_generation_used": False, "near_duplicate_threshold": 0.75,
                      "near_duplicate_pairs": near_pairs, "max_cross_split_bigram_jaccard": max_similarity},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scikit_learn": sklearn.__version__},
    }
    label_order = list(LABELS)
    for split in ("validation", "test"):
        y = [row["label"] for row in rows[split]]
        predictions = pipeline.predict([row["text"] for row in rows[split]])
        probabilities = pipeline.predict_proba([row["text"] for row in rows[split]])
        metrics[split] = {
            "accuracy": float(accuracy_score(y, predictions)), "macro_f1": float(f1_score(y, predictions, average="macro")),
            "per_class": classification_report(y, predictions, labels=label_order, output_dict=True, zero_division=0),
            "confusion_matrix": confusion_matrix(y, predictions, labels=label_order).tolist(), "label_order": label_order,
        }
        write_csv(baseline / f"{split}_predictions.csv", [
            {**row, "predicted_label": str(predicted), "max_probability": round(float(probability.max()), 8), "correct": row["label"] == predicted}
            for row, predicted, probability in zip(rows[split], predictions, probabilities, strict=True)
        ], ["id", "text", "label", "predicted_label", "max_probability", "correct"])
    predicted = pipeline.predict([row["text"] for row in challenge])
    probabilities = pipeline.predict_proba([row["text"] for row in challenge])
    write_jsonl(baseline / "challenge_predictions.jsonl", [
        {**row, "predicted_label": str(label), "max_probability": round(float(probability.max()), 8),
         "automatic_single_label_allowed": row["expected_action"] == "negation"}
        for row, label, probability in zip(challenge, predicted, probabilities, strict=True)
    ])
    metrics["challenge"] = {"count": len(challenge), "accuracy_reported": False,
        "note": "clarify/multi_intent没有唯一正确类别；本基线无多标签或拒答机制，预测仅供复核。概率未经校准。"}
    joblib.dump(pipeline, baseline / "tfidf_logreg.joblib", compress=3)
    write_json(baseline / "metrics.json", metrics)
    (root / "README.md").write_text(f"""# 中文售后工单六分类：复验数据与独立基线

这是一套原创、手写的中文合成工单，只用于数据准备、对话路径、切分与评测流程演示。没有真实客户数据，不代表真实业务效果。

## 数据与文件

- `data/train.csv` / `.jsonl`：72 条，每类 12 条。
- `data/validation.csv` / `.jsonl`：36 条，每类 6 条。
- `data/test.csv` / `.jsonl`：36 条，每类 6 条，固定最终测试集。
- `data/challenge.jsonl`：12 条歧义、多意图或否定样本，单独人工复核。
- `labels.json`：六类定义与标注规则。
- `nlp_after_sales_review.zip`：上述数据及说明的可携带包；CSV/JSONL也可单独选择。
- `baseline/`：独立基线指标、逐条预测、可信本地产生的模型文件。
- `manifest.json`：文件大小与 SHA-256。ZIP不包含模型文件及测试预测。

CSV/JSONL字段：`id`为文本内容哈希形成的稳定标识，仅审计使用；`text`为唯一输入特征；`label`为六类英文标签。不得把id作为模型特征。
CSV与JSONL是同一批样本的两种表示，导入时选择一种，不能拼接两种格式而重复计数。
challenge多出`acceptable_labels`候选类别、`expected_action`（clarify/multi_intent/negation）和`review_note`。它们是人工复核答案，不能作为输入特征。

## 来源与切分

全部文本在本脚本中原创编写，三个split分别列出，没有通过替换品名/订单号复用句子模板。文本精确和去标点交叉重复均为0；跨split字符二元组Jaccard最大值为 {max_similarity:.4f}，大于等于0.75的近重复对为0。相同售后语义与必要词汇跨split出现是本任务的一部分。

保持现有split，不混合后随机再切分；真实数据应按客户、会话、时间及近重复模板分组。明确“退款/换货”等动作优先于原因；多意图不强行压成单标签。标注分歧需单独复核。

## 已实际运行的独立参考

字符TF-IDF + LogisticRegression，仅fit训练集，不下载或微调预训练语言模型，没有超参搜索。验证集 accuracy={metrics['validation']['accuracy']:.4f}、macro-F1={metrics['validation']['macro_f1']:.4f}；测试集 accuracy={metrics['test']['accuracy']:.4f}、macro-F1={metrics['test']['macro_f1']:.4f}。

这是生成脚本直接运行的 sklearn 基线，**不是 Studio 训练 Run，不是预训练模型微调，也不是业务准出证据**。用户尚未给出业务验收门槛，没有为使结果好看而设置或降低门槛。查看逐条错误与混淆矩阵；样本很少且书面语为主，真实口语、错别字、上下文和类别不均衡尚未覆盖。challenge没有唯一类别时不报告单标签准确率，模型概率未经校准。

## 给 Studio 的复验路径

先说明“中文文本六分类，希望微调已有中文模型”，提供类别定义与固定split，要求给数据规格、模型选择依据和资源准备方案。明确传统基线只作为比较对象。
当前若没有已验证的文本分类 Recipe/Adapter，应停在数据检查、研究与接入规划；不要把文本当表格类别做稠密独热编码，也不要把本ZIP交给图片目录适配器。任何真实微调、导入或训练仍按当时已接入工具及其批准门禁执行。

重现（仓库根目录，使用安装了项目依赖的Python）：
`python scripts/acceptance/generate_text_timeseries_fixtures.py --scenario nlp`

值得收集：是否保持文本分类目标及微调路线；是否主动给数据准备建议；是否保留预划分测试集；是否说明独立基线与Studio训练的区别；是否把多意图问题误判为一个确定类别。
""", encoding="utf-8")
    archive(root / "nlp_after_sales_review.zip", root, [root / "README.md", root / "labels.json", *sorted((root / "data").glob("*"))])
    manifest(root, "nlp_after_sales_6class", {split: {k: metrics[split][k] for k in ("accuracy", "macro_f1")} for split in ("validation", "test")})
    return {"scenario": "nlp", "counts": metrics["split_counts"], "validation": metrics["validation"]["macro_f1"], "test": metrics["test"]["macro_f1"], "output": str(root)}


def generate_timeseries(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    start = date(2024, 1, 1)
    lengths = {"train": 365, "validation": 56, "test": 56}
    count = sum(lengths.values())
    stores = [("store_a", 180.0), ("store_b", 280.0), ("store_c", 110.0)]
    fields = ["store_id", "date", "day_of_week", "is_weekend", "planned_promotion", "discount_pct", "calendar_event", "sales_units"]
    known_fields = fields[:-1]
    values = {split: [] for split in SPLITS}
    histories = {}
    future = []
    rng = np.random.default_rng(SEED)
    for store_index, (store_id, level) in enumerate(stores):
        history = []
        for index in range(count + 7):
            day = start + timedelta(days=index)
            promo = int((index + store_index * 11) % 35 in {3, 4, 5})
            event = int(index % 91 in {44, 45})
            row = {"store_id": store_id, "date": day.isoformat(), "day_of_week": day.weekday(),
                   "is_weekend": int(day.weekday() >= 5), "planned_promotion": promo,
                   "discount_pct": 20 if promo else 0, "calendar_event": event}
            if index >= count:
                future.append(row)
                continue
            weekly = [0.82, 0.88, 0.95, 1.0, 1.12, 1.27, 1.17][day.weekday()]
            annual = 1 + 0.11 * math.sin(2 * math.pi * index / 365)
            expected = (level + 0.035 * index) * weekly * annual * (1 + 0.35 * promo + 0.15 * event)
            noise = rng.normal(0, 7 + store_index * 2)
            sales = max(0, int(round(expected + noise)))
            row["sales_units"] = sales
            split = "train" if index < 365 else "validation" if index < 421 else "test"
            values[split].append(row)
            history.append(row)
        histories[store_id] = history
    for split, rows in values.items():
        rows.sort(key=lambda row: (row["date"], row["store_id"]))
        write_csv(root / "data" / f"{split}.csv", rows, fields)
        write_jsonl(root / "data" / f"{split}.jsonl", rows)
    future.sort(key=lambda row: (row["date"], row["store_id"]))
    write_csv(root / "data" / "future_7d_inputs.csv", future, known_fields)
    write_jsonl(root / "data" / "future_7d_inputs.jsonl", future)
    assert all("sales_units" not in row for row in future)
    all_rows = [row for split in SPLITS for row in values[split]]
    assert len({(r["store_id"], r["date"]) for r in all_rows}) == len(all_rows)
    assert max(r["date"] for r in values["train"]) < min(r["date"] for r in values["validation"])
    assert max(r["date"] for r in values["validation"]) < min(r["date"] for r in values["test"])
    assert max(r["date"] for r in values["test"]) < min(r["date"] for r in future)
    metrics = {
        "execution_kind": "independent_local_reference", "studio_run": False,
        "algorithm": "seasonal_naive_lag_7", "horizon_days": 7,
        "evaluation_protocol": "non-overlapping rolling 7-day origins; earlier actuals become available only after their block ends",
        "acceptance_gates": None, "acceptance_note": "未设业务准出门槛，不按结果降低门槛或声明可上线。",
        "data_source": "original synthetic simulation; not real stores or measured demand",
        "split_days_per_store": lengths, "split_rows": {split: len(rows) for split, rows in values.items()},
        "date_ranges": {split: [rows[0]["date"], rows[-1]["date"]] for split, rows in values.items()},
        "future_date_range": [future[0]["date"], future[-1]["date"]],
        "mase_scaling": "per-store mean absolute lag-7 error on training period only; unchanged for validation/test",
        "feature_policy": {"known_future": known_fields, "unknown_future": ["sales_units", "realized demand noise"],
            "calendar_event": "synthetic preannounced store campaign; not an official public-holiday calendar"},
    }
    scales = {}
    for store_id, history in histories.items():
        train = np.asarray([row["sales_units"] for row in history[:365]], dtype=float)
        scales[store_id] = float(np.abs(train[7:] - train[:-7]).mean())
        assert scales[store_id] > 0
    metrics["mase_training_scale_by_store"] = scales
    baseline = root / "baseline"
    baseline.mkdir(exist_ok=True)
    for split, first, last in [("validation", 365, 421), ("test", 421, count)]:
        predictions = []
        for store_id, history in histories.items():
            for block_start in range(first, last, 7):
                origin = history[block_start - 1]["date"]
                for i in range(block_start, min(block_start + 7, last)):
                    source = history[i - 7]
                    assert source["date"] <= origin < history[i]["date"]
                    actual, predicted = history[i]["sales_units"], source["sales_units"]
                    predictions.append({"store_id": store_id, "forecast_origin": origin, "forecast_date": history[i]["date"],
                        "horizon": i - block_start + 1, "source_observation_date": source["date"],
                        "actual_sales_units": actual, "predicted_sales_units": predicted,
                        "absolute_error": abs(actual - predicted), "scaled_absolute_error": abs(actual - predicted) / scales[store_id]})
        def scores(items):
            errors = np.asarray([r["absolute_error"] for r in items], dtype=float)
            return {"MAE": float(errors.mean()), "RMSE": float(np.sqrt(np.mean(errors**2))),
                    "MASE": float(np.mean([r["scaled_absolute_error"] for r in items])),
                    "sMAPE_percent": float(np.mean([200 * r["absolute_error"] / max(1, abs(r["actual_sales_units"]) + abs(r["predicted_sales_units"])) for r in items])), "count": len(items)}
        metrics[split] = {"overall": scores(predictions), "by_store": {store: scores([r for r in predictions if r["store_id"] == store]) for store, _ in stores}}
        write_csv(baseline / f"{split}_predictions.csv", predictions, list(predictions[0]))
    future_predictions = []
    for row in future:
        horizon = (date.fromisoformat(row["date"]) - (start + timedelta(days=count - 1))).days
        source = histories[row["store_id"]][count - 7 + horizon - 1]
        assert source["date"] <= (start + timedelta(days=count - 1)).isoformat()
        future_predictions.append({**row, "forecast_origin": (start + timedelta(days=count - 1)).isoformat(),
            "source_observation_date": source["date"], "predicted_sales_units": source["sales_units"]})
    write_csv(baseline / "future_7d_predictions.csv", future_predictions, list(future_predictions[0]))
    metrics["integrity"] = {"duplicate_store_date_pairs": 0, "missing_days_per_store": 0,
        "time_ordered_splits": True, "prediction_source_after_origin_count": 0,
        "future_input_contains_target": False, "future_realized_values_generated": False,
        "promotions_preannounced": True, "test_used_for_model_selection": False}
    write_json(baseline / "metrics.json", metrics)
    write_json(root / "data_dictionary.json", {
        "store_id": "虚构门店标识，三个序列不可混合为一条序列。",
        "date": "业务日ISO日期；每家门店每日一条，不能随机划分。",
        "day_of_week": "已知日历变量，Monday=0，Sunday=6。",
        "is_weekend": "已知周末标志，0/1。",
        "planned_promotion": "事先排定的促销计划，0/1；本合成任务假设预测时已知。",
        "discount_pct": "事先计划的折扣百分数，0或20，与实际售后折扣不同。",
        "calendar_event": "事先安排的虚构门店活动日，0/1，不是法定节假日。",
        "sales_units": "当天实际销量（非负整数），仅历史及评测数据有；未来输入不含该字段。",
        "lag_rule": "滞后销量必须按store_id在预测origin之前的可见历史计算；不可读取未来真实销量。",
    })
    (root / "README.md").write_text(f"""# 多门店未来7天日销量：复验数据与季节朴素基线

全部数据为原创合成的三个虚构门店，不含真实经营信息，只用于时序数据准备、对话与回测流程演示。合成波动不代表业务效果。

## 规模与固定切分

每店477个历史日：训练365日、验证56日、测试56日。总计1431条历史记录，三个split分别1095/168/168行；未来7日输入21行。
- 训练：{metrics['date_ranges']['train'][0]} 至 {metrics['date_ranges']['train'][1]}。
- 验证：{metrics['date_ranges']['validation'][0]} 至 {metrics['date_ranges']['validation'][1]}。
- 测试：{metrics['date_ranges']['test'][0]} 至 {metrics['date_ranges']['test'][1]}。
- 未来：{metrics['future_date_range'][0]} 至 {metrics['future_date_range'][1]}，没有真实销量答案。

`data/`下每个split提供CSV和等价JSONL；`future_7d_inputs.csv/.jsonl`只包含预测时可知的字段。
CSV和JSONL是等价副本，导入时选择一种格式，不能把两种格式拼接成双倍样本。
`data_dictionary.json`解释每列；`timeseries_sales_review.zip`仅打包数据和说明；`baseline/`保存独立参考预测与指标，未放入上传包；`manifest.json`列出SHA-256。

## 生成机制和信息边界

固定随机种子{SEED}，叠加门店基准量、周内季节性、平滑年周期、缓慢趋势、预定促销/活动以及随机需求噪声。促销计划在生成目标之前确定，未来计划可以给模型；未来真实销量及随机噪声不能作为输入。活动日是虚构计划，不是现实法定节假日。
每个门店的日期连续且无重复。保持时间顺序切分，不能把多门店混成一个序列，也不能转换为普通表格随机切分。真实业务还需检查缺货、关店、调价、促销临时变更及统计口径；这些未全部模拟。

## 已实际执行的独立基线

季节朴素法：未来第h天（h=1..7）的预测等于同店上周对应日的实际销量。验证和测试各有8个不重叠的7日预测窗口，每个窗口的全部预测只读预测起点之前的观察值；前一窗口结束后才允许其实际值进入下个窗口。
MASE按每店训练期`mean(abs(y[t]-y[t-7]))`缩放，验证/测试不重估分母；总体MASE为逐样本缩放误差平均。MAE单位为件，sMAPE用百分数。参考结果：
- 验证：MAE={metrics['validation']['overall']['MAE']:.4f}，MASE={metrics['validation']['overall']['MASE']:.4f}。
- 测试：MAE={metrics['test']['overall']['MAE']:.4f}，MASE={metrics['test']['overall']['MASE']:.4f}。

这不是学习型模型训练，更不是Studio训练Run。没有模型选择或超参搜索，没有设置或放宽业务验收门槛。未来预测文件只是基线结果，未生成未来真实答案。促销起止会使简单周季节基线失准，误差是本示例应保留的发现。

## 给Studio的复验路径

说明“多门店按日期预测未来7天销量，希望训练时序模型”，提供预测频率、跨度、已知未来协变量、固定切分和季节基线。要求先给数据规格、滞后特征可见性、滚动回测、算力与最小实验准备方案。
若没有经过验证的时序Recipe/Adapter，停在准备、研究和接入规划；不要因为CSV可读就改成独立行表格回归。任何真正训练仍需要对应Recipe、数据合同和授权。

重现（仓库根目录）：`python scripts/acceptance/generate_text_timeseries_fixtures.py --scenario timeseries`

值得收集：是否保留“未来7天”的时序目标；是否避免随机切分；是否把未来未知销量/天气当特征；是否混淆已知促销计划与实际促销结果；是否报告基线及滚动origin；是否把独立脚本的预测误称Studio训练。
""", encoding="utf-8")
    archive(root / "timeseries_sales_review.zip", root, [root / "README.md", root / "data_dictionary.json", *sorted((root / "data").glob("*"))])
    manifest(root, "multi_store_daily_sales_7d", {split: metrics[split]["overall"] for split in ("validation", "test")})
    return {"scenario": "timeseries", "counts": metrics["split_rows"], "test": metrics["test"]["overall"], "output": str(root)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("all", "nlp", "timeseries"), default="all")
    parser.add_argument("--output-root", type=Path, default=Path("runs/acceptance/20261004-four-scenarios"))
    args = parser.parse_args()
    selected = ("nlp", "timeseries") if args.scenario == "all" else (args.scenario,)
    for scenario in selected:
        function = generate_nlp if scenario == "nlp" else generate_timeseries
        print(json.dumps(function(args.output_root / scenario), ensure_ascii=False))


if __name__ == "__main__":
    main()
