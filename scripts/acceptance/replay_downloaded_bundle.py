#!/usr/bin/env python3
"""Replay an exact page-downloaded generic bundle in a fresh offline OCI job.

This trusted wrapper validates/copies data; it never imports exported source or
loads serialized model objects on the host. It creates no product TrainingRun.
"""
import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

from model_harness.execution_runtime import execution_root
from model_harness.generic_recipe import _digest
from model_harness.generic_io_schema import validate_output_result
from model_harness.isolated_execution import ExecutionBundle, OCIExecutor


def sha(data):
    return hashlib.sha256(data).hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value or any(ord(c) < 32 for c in value):
        raise ValueError('unsafe archive path')
    if PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise ValueError('unsafe archive path')
    return value


def verify_extract(archive, record, destination):
    if destination.exists():
        raise ValueError('fresh extraction directory required')
    if sha(archive.read_bytes()) != record['archive']['sha256'] or archive.stat().st_size != record['archive']['size_bytes']:
        raise ValueError('download does not match the canonical bundle record')
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        if len(infos) > 1024 or sum(i.file_size for i in infos) > 2 * 1024**3:
            raise ValueError('archive exceeds verification budget')
        names=[relative(i.filename) for i in infos]
        if len({n.casefold() for n in names}) != len(names) or any(stat.S_ISLNK(i.external_attr >> 16) or i.is_dir() for i in infos):
            raise ValueError('duplicate, directory or symlink archive member')
        manifest=json.loads(z.read('bundle_manifest.json'))
        if manifest['manifest_sha256'] != record['manifest_sha256'] or _digest({k:v for k,v in manifest.items() if k != 'manifest_sha256'}) != record['manifest_sha256']:
            raise ValueError('bundle manifest digest mismatch')
        for k in ('task_id','run_id','bundle_id'):
            if manifest[k] != record[k]: raise ValueError('bundle identity mismatch')
        rows={relative(r['path']):r for r in manifest['files']}
        if len(rows) != len(manifest['files']) or set(names) != set(rows) | {'bundle_manifest.json'}:
            raise ValueError('undeclared bundle members')
        payload={}
        for name,row in rows.items():
            data=z.read(name)
            if len(data) != row['size_bytes'] or sha(data) != row['sha256']:
                raise ValueError('bundle file digest mismatch: '+name)
            payload[name]=data
        model=json.loads(payload['artifacts/generic_model.json'])
        portable=json.loads(payload['artifacts/generic_execution.json'])
        if model['model_sha256'] != _digest({k:v for k,v in model.items() if k!='model_sha256'}):
            raise ValueError('model manifest digest mismatch')
        if model['task_id'] != manifest['task_id'] or model['run_id'] != manifest['run_id']:
            raise ValueError('model identity mismatch')
        bundle=ExecutionBundle.from_dict(portable['bundle'])
        if bundle.digest != portable['bundle_sha256'] or bundle.digest != model['bundle_sha256']:
            raise ValueError('execution bundle digest mismatch')
        ledger={r['path']:r for r in model['artifacts']}
        needed=list(model['model_files'])+[r['path'] for r in model['artifacts'] if r['role']=='base_model_dependency']+['config.json']
        for name in needed:
            data=payload['artifacts/'+relative(name)];row=ledger[name]
            if len(data) != row['bytes'] or sha(data) != row['sha256']:
                raise ValueError('model dependency digest mismatch')
            if name in model['model_files'] and row.get('stage','train') != 'train':
                raise ValueError('test-produced checkpoint cannot be replayed')
        destination.mkdir(parents=True,mode=0o700)
        for name,data in payload.items():
            path=destination/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        (destination/'bundle_manifest.json').write_bytes(z.read('bundle_manifest.json'))
    return manifest,model,portable,bundle


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for arg in ('archive','record','input','evidence-dir'): ap.add_argument('--'+arg,required=True,type=Path)
    args=ap.parse_args()
    root=args.evidence_dir.resolve();root.mkdir(parents=True,exist_ok=True)
    report={'scope':'supplementary downloaded-bundle replay; not a new TrainingRun','status':'incomplete','archive_sha256':sha(args.archive.read_bytes()),'input_sha256':sha(args.input.read_bytes()),'model_inputs_from_downloaded_archive':True}
    try:
        record=json.loads(args.record.read_text())
        manifest,model,portable,bundle=verify_extract(args.archive,record,root/'extracted')
        extension=args.input.suffix.lower()
        if extension not in portable['inference']['extensions'] or args.input.stat().st_size > portable['inference']['max_bytes']:
            raise ValueError('new input does not match the declared prediction contract')
        inputs={'config.json':root/'extracted/artifacts/config.json','sample/input'+extension:args.input.resolve()}
        for name in model['model_files']: inputs['model/'+name]=root/'extracted/artifacts'/name
        for row in model['artifacts']:
            if row['role']=='base_model_dependency': inputs[row['path']]=root/'extracted/artifacts'/row['path']
        isolated=execution_root(Path.home()/'.local/share/specialist-model-studio/isolated-jobs')
        result=OCIExecutor().run_stage(bundle,'predict',expected_bundle_digest=bundle.digest,isolated_root=isolated,input_files=inputs)
        (root/'execution-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        report.update(execution_id=result['execution_id'],network=result['network'],execution_status=result['status'],task_id=manifest['task_id'],run_id=manifest['run_id'],bundle_id=manifest['bundle_id'])
        if result['status']!='completed': raise ValueError('isolated prediction did not complete')
        output=isolated/result['execution_id']/'output'
        infer=json.loads((output/'infer_result.json').read_text())
        validate_output_result(infer,portable['inference'])
        reference=json.loads((root/'extracted/evidence/inference_check.json').read_text())
        # Current package inference evidence may nest the sample result.
        ref=reference.get('output',reference.get('prediction',reference.get('result',{}).get('prediction')))
        if ref is None: raise ValueError('page trial prediction missing from downloaded evidence')
        if ref != infer['prediction']: raise ValueError('downloaded model prediction differs from the page trial')
        report.update(status='passed',prediction_equal_to_page_trial=ref==infer['prediction'],prediction=infer['prediction'])
        (root/'infer_result.json').write_text(json.dumps(infer,ensure_ascii=False,indent=2))
        report['output_artifacts']=result['artifacts']
    except Exception as exc:
        report.update(status='failed',error=str(exc))
    (root/'replay-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ('prediction','output_artifacts')},ensure_ascii=False))
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':sys.exit(main())
