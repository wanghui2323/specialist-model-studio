#!/usr/bin/env python3
"""Local paired-speech format fixtures, not a voice-training benchmark."""
from __future__ import annotations
import argparse,csv,hashlib,json,platform,subprocess,tempfile,wave,zipfile
from pathlib import Path
from array import array

TEXTS = [
'今天我们先检查录音和文字是否对应。','早上的阳光照进窗户，桌上的茶还很温热。','请把这份材料放在左边的蓝色文件夹里。','会议改到明天下午三点，在二楼的小会议室举行。',
'这次测试关注清晰的发音，也关注自然的停顿。','我们沿着河边慢慢走，远处传来了自行车的铃声。','快递已经放在前台，取件时请核对姓名。','这道菜要先放少量盐，最后再加入切好的葱花。',
'如果今天来不及完成，就先把遇到的问题记下来。','打开设置以后，可以调整文字大小和屏幕亮度。','这个星期有两天需要外出，其余时间都在办公室。','我把钥匙放在门口的小篮子里了。',
'下雨之前记得关窗，也把阳台上的衣服收进来。','一份好的说明应该让第一次使用的人也能看懂。','小猫躲在椅子下面，听到声音后探出了脑袋。','请先核对清单，再把缺少的物品补上。',
'图书馆周一休息，周二到周日正常开放。','这条路线步行大约二十分钟，中间会经过一座桥。','冰箱里的水果已经洗好，吃之前不用再清洗。','数据质量需要逐条检查，数量多不代表问题少。',
'他停下来想了想，然后认真回答了这个问题。','我们可以先做一个小实验，再决定下一步怎么走。','录音时保持自然语速，句子之间稍微停顿一下。','手机电量快用完了，我去找一下充电器。',
'这些文件按照日期整理，新的放在后面。','书架上第二排有一本绿色封面的笔记本。','晚饭以后我们一起去附近的公园散步。','处理完这一批材料，再安排下一轮检查。',
'请把音量调低一点，我想仔细听清最后几个字。','在提交之前，先确认表格里没有空白的必填项。','画面里的树叶随着风轻轻晃动。','所有记录都要保留原始版本，修改后另存一份。',
'下一班列车将在十分钟后到达，请在安全线内等候。','今天的温度比昨天低，出门时加一件外套。','包裹里有三个杯子和两只碗，请轻拿轻放。','系统更新完成以后，再检查一遍连接状态。',
'他说得很慢，仿佛在寻找最合适的表达。','这个按钮用来保存草稿，不会立即公开发布。','如果两份记录内容相同，只保留其中一个样本。','照片里的文字有些模糊，可以换一个角度重新拍。',
'截至九月三十日，这项计划已经完成了第一阶段。','订单总额是三百二十六元五角，请核对收据。','请问明天早上八点半之前能够送到吗？','这条消息包含日期、数量，以及一个需要确认的地点。',
'标点可以帮助理解句子，但不能替代完整的内容。','先把结果保存下来，再讨论它为什么出现偏差。','同样的问题换一种说法，含义也可能完全不同。','测试结束以后，请把实际结果和原始记录一起归档。',
]

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_json(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def make_zip(path,root,paths):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(paths):z.write(p,p.relative_to(root).as_posix())

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=Path('runs/acceptance/20261004-four-scenarios/speech'));ap.add_argument('--voice',default='Tingting');args=ap.parse_args()
    if platform.system()!='Darwin':raise SystemExit('This local audio generator requires macOS say and afconvert. No weights are downloaded.')
    root=args.out.resolve()
    if root.exists() and any(root.iterdir()):raise SystemExit('Output must be empty; use --out with a new directory to preserve recorded or reviewed samples.')
    root.mkdir(parents=True,exist_ok=True)
    assert len(TEXTS)==48 and len(set(TEXTS))==48
    records=[]
    with tempfile.TemporaryDirectory(prefix='sms-tts-fixture-') as temp:
        for i,text in enumerate(TEXTS):
            split='train' if i<32 else 'validation' if i<40 else 'test'
            path=root/split/'wav'/f'utt_{i+1:03d}.wav';path.parent.mkdir(parents=True,exist_ok=True)
            raw=Path(temp)/'clip.aiff'
            subprocess.run(['say','-v',args.voice,'-r','175','-o',str(raw),text],check=True,capture_output=True)
            subprocess.run(['afconvert',str(raw),str(path),'-f','WAVE','-d','LEI16@24000','-c','1'],check=True,capture_output=True)
            with wave.open(str(path)) as w:
                assert (w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,2,24000)
                frames=w.readframes(w.getnframes());samples=array('h',frames)
                duration=w.getnframes()/w.getframerate()
            assert duration>0 and any(samples)
            records.append({'id':f'utt_{i+1:03d}','audio':path.relative_to(root).as_posix(),'text':text,'speaker_id':'synthetic_tingting','language':'zh-CN','split':split,'duration_seconds':round(duration,3),'sample_rate':24000,'channels':1,'sample_width_bytes':2,'peak_absolute_pcm':max(abs(x) for x in samples),'sha256':digest(path),'provenance':'macOS say synthetic voice; local format fixture; not user voice'})
    for split in ('train','validation','test'):
        rows=[x for x in records if x['split']==split]
        (root/split/'metadata.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in rows),encoding='utf-8')
        with (root/split/'metadata.csv').open('w',encoding='utf-8-sig',newline='') as f:
            wr=csv.DictWriter(f,fieldnames=['id','audio','text','speaker_id']);wr.writeheader();wr.writerows({k:r[k] for k in wr.fieldnames} for r in rows)
    with (root/'recording_script.csv').open('w',encoding='utf-8-sig',newline='') as f:
        wr=csv.writer(f);wr.writerow(['id','suggested_split','text','own_audio_filename','checked_text_matches_audio'])
        for r in records:wr.writerow([r['id'],r['split'],r['text'],r['id']+'.wav',''])
    (root/'inference_prompts.jsonl').write_text(''.join(json.dumps({'id':f'new_{i+1:02d}','text':t},ensure_ascii=False)+'\n' for i,t in enumerate(['请把明天下午的预约改到周五上午。','这批零件一共二百四十件，分成六箱装好。','你看见放在窗台上的那副眼镜了吗？','价格下降了百分之八，但运输费用没有变化。'])),encoding='utf-8')
    stats={'dataset_kind':'synthetic_format_fixture','counts':{s:sum(r['split']==s for r in records) for s in ('train','validation','test')},'duration_seconds':round(sum(r['duration_seconds'] for r in records),2),'sample_rate':24000,'channels':1,'sample_width_bytes':2,'unique_texts':len(set(r['text'] for r in records)),'unique_audio_sha256':len(set(r['sha256'] for r in records)),'validation':{'all_decode':True,'all_non_silent':True,'split_text_overlap':False},'studio_training_run':False,'trained_voice_similarity':None,'voice':args.voice,'generator':'macOS say + afconvert; no model trained','sources':['local macOS say Tingting synthetic output; original Chinese recording script'],'optional_real_data_reference':'https://www.openslr.org/93/','public_release_note':'Local sample audio is system synthesized. Do not include system voice assets in the open-source release; the original recording script and generator may be reviewed separately.'}
    write_json(root/'data_validation.json',stats)
    (root/'README.md').write_text(f'''# 语音：自己的声音朗读中文（TTS）\n\n本包是**格式与流程样例**，不是训练好的个人声音模型，也不是你本人的录音。音频由本机 macOS `{args.voice}` 系统音色合成，文本为本次原创；不把系统合成语音资产并入开源发布。\n\n共 48 条、{stats['duration_seconds']} 秒：训练 32 条，验证 8 条，独立测试 8 条。PCM WAV，单声道，24 kHz、16 bit。每条音频配逐字文本，`metadata.jsonl` 中 audio 相对整个包根目录定位。文字与音频均无精确重复，自动检测全部能解码且非静音。人工听感/文字一致性仍可按录音脚本抽听。\n\n## 怎么用\n\n1. 首先按总目录对话路径描述目标与从零训练路线，要求先给规格、参考架构/资源和最小实验。\n2. `tts_speech_review.zip` 只含 train/validation 和字典，`tts_speech_holdout.zip` 单独保留测试集与全新合成提示，不能用于挑模型。仅在工作台出现对应 TTS 数据接入后导入；通用 ZIP 按钮不等于 TTS 适配器。\n3. 试自己的声音：按 `recording_script.csv` 逐条录制自己的 WAV，替换对应文件并核对实际转写。这里的 48 句只能做采集/对齐和管线检查，不能据此承诺从零训练的可用音质；最终规格与数据规模应由选定架构、小实验和质量目标决定。\n4. 评测至少包含未见文本的可懂度、漏字/重复、自然度、本人音色相似度；训练 loss 不能代替这些。可以人工对照原文听写和盲听评分。`inference_prompts.jsonl` 是独立新句，不参与训练。\n\n## 当前验证范围\n\n已验证：本机语音合成输出、格式、时长、非静音、标签/音频对应文件、无精确泄漏。未完成：Studio TTS Recipe/Adapter 接入、个人声音训练、从零模型效果、音色相似度和商用质量。这里不把声学关键词分类当 TTS。\n\n若后续需要真实公开中文语音，可研究官方 [AISHELL-3](https://www.openslr.org/93/)（Apache 2.0；公开数据的声音不是你的声音）。此包没有下载该完整数据集；选择真人语料时保留原许可、来源、speaker 和会话信息，不能把单个说话人的测试录音用于调参。\n''',encoding='utf-8')
    trainpaths=[p for split in ('train','validation') for p in (root/split).rglob('*') if p.is_file()]+[root/'README.md',root/'data_validation.json']
    testpaths=[p for p in (root/'test').rglob('*') if p.is_file()]+[root/'inference_prompts.jsonl']
    make_zip(root/'tts_speech_review.zip',root,trainpaths);make_zip(root/'tts_speech_holdout.zip',root,testpaths)
    write_json(root/'manifest.json',{'schema_version':'1.0','files':[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(root.rglob('*')) if p.is_file() and p.name!='manifest.json']})
    print(json.dumps(stats,ensure_ascii=False))
if __name__=='__main__':main()
