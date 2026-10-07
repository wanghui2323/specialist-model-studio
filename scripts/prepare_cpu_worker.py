#!/usr/bin/env python3
"""Build the reviewed CPU worker, inspect it offline and write a local receipt.

Only runtime/cpu enters the Docker build context. No model/source checkout,
training data or credentials are copied or passed as build arguments.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ARCHES={'aarch64':'arm64','arm64':'arm64','x86_64':'amd64','amd64':'amd64'}
IMAGE=re.compile(r'^sha256:[a-f0-9]{64}$')
INVENTORY="import json,sys,importlib.metadata as m;print(json.dumps({'python':sys.version,'packages':{d.metadata['Name'].lower():d.version for d in m.distributions()}}))"
PROBE="import torch,numpy,scipy,transformers,sklearn,librosa,pandas,PIL,json; x=torch.tensor([1.,2.],requires_grad=True);(x*x).sum().backward();print(json.dumps({'parameter_gradient':x.grad.tolist(),'cuda_available':torch.cuda.is_available(),'tensor_roundtrip':x.detach().numpy().tolist()}))"


def command(argv, *, timeout=1800, capture=False):
    result=subprocess.run(argv,stdin=subprocess.DEVNULL,timeout=timeout,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if not capture:
        # Registry failures may contain temporary signed CDN URLs.
        def clean(match):
            from urllib.parse import urlsplit, urlunsplit
            url=urlsplit(match.group(0));return urlunsplit((url.scheme,url.hostname or "",url.path,"",""))
        for output in [result.stdout,result.stderr]:sys.stderr.write(re.sub(r'https?://[^\s"<>]+',clean,output))
    if result.returncode:raise subprocess.CalledProcessError(result.returncode,argv)
    return result


def build_arguments(arch,tag,base_image=None,context=None):
    if arch not in ('arm64','amd64') or not re.fullmatch(r'[a-z0-9][a-z0-9._:/-]{1,120}',tag):
        raise ValueError('supported Linux architecture and safe local image tag required')
    extra=[]
    if base_image is not None:
        if not IMAGE.fullmatch(base_image):raise ValueError('verified immutable base image ID required')
        extra=['--build-arg','BASE_IMAGE='+base_image]
    return ['docker','build',*extra,'--network=none','--build-arg',f'LOCKFILE=requirements-linux-{arch}.lock','--tag',tag,str(context or ROOT/'runtime/cpu')]


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():raise ValueError('output/configuration must not be a symlink')
    temp=path.with_name('.'+path.name+'.tmp-'+str(os.getpid()))
    try:
        with temp.open('x') as f:os.chmod(temp,0o600);json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag',default='specialist-model-studio-cpu:1.0.0-rc.2')
    p.add_argument('--output-dir',type=Path,default=Path.home()/'.local/share/specialist-model-studio/runtime/rc2')
    p.add_argument('--configure',action='store_true',help='create the operator execution config after successful probes')
    p.add_argument('--replace-config',action='store_true',help='explicitly replace an existing operator config')
    p.add_argument('--isolated-root',type=Path,default=Path.home()/'.local/share/specialist-model-studio/isolated-jobs')
    a=p.parse_args();out=a.output_dir.expanduser().resolve();config=Path.home()/'.local/share/specialist-model-studio/execution-runtime.json'
    if a.configure and config.exists() and not a.replace_config:raise ValueError('operator config exists; use environment overrides or explicit --replace-config')
    native=command(['docker','info','--format','{{.Architecture}}'],timeout=10,capture=True).stdout.strip()
    arch=ARCHES.get(native)
    if not arch:raise ValueError('CPU recipe currently has reviewed Linux arm64 and amd64 locks; architecture not recognized')
    from prepare_cpu_base import prepare
    print("Verifying the pinned official Python base...",file=sys.stderr,flush=True)
    base_image,base_receipt=prepare(arch)
    print("Building the hash-locked CPU worker...",file=sys.stderr,flush=True)
    lock=ROOT/'runtime/cpu'/f'requirements-linux-{arch}.lock'
    lock_sha=hashlib.sha256(lock.read_bytes()).hexdigest()
    wheels=Path.home()/'.cache/specialist-model-studio/worker-wheels'/lock_sha
    wheels.mkdir(parents=True,exist_ok=True)
    machine='aarch64' if arch=='arm64' else 'x86_64'
    platforms=[f'manylinux_2_{minor}_{machine}' for minor in range(36,16,-1)]+['manylinux2014_'+machine,'linux_'+machine]
    download=['uv','tool','run','--from','pip==26.2.1','--python',sys.executable,'pip','download','--no-deps','--require-hashes','--only-binary=:all:','--python-version','312','--implementation','cp','--abi','cp312','--dest',str(wheels),'-r',str(lock)]
    for platform in platforms:download.extend(['--platform',platform])
    print('Downloading hash-verified wheels on the host; no code is installed or executed from those wheels...',file=sys.stderr,flush=True)
    command(download)
    allowed=set(re.findall(r'--hash=sha256:([a-f0-9]{64})',lock.read_text()))
    wheel_rows=[]
    with tempfile.TemporaryDirectory(prefix='sms-worker-context-') as temporary:
        build_context=Path(temporary)
        for name in ['Dockerfile','.dockerignore',lock.name]:shutil.copyfile(ROOT/'runtime/cpu'/name,build_context/name)
        (build_context/'wheels').mkdir()
        for wheel in sorted(wheels.glob('*.whl')):
            if wheel.is_symlink():raise ValueError('wheel cache symlink is unsafe')
            digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
            if digest not in allowed:raise ValueError('wheel cache digest not in selected dependency lock')
            shutil.copyfile(wheel,build_context/'wheels'/wheel.name);wheel_rows.append({'filename':wheel.name,'sha256':digest,'bytes':wheel.stat().st_size})
        command(build_arguments(arch,a.tag,base_image,build_context))
    image=command(['docker','image','inspect',a.tag,'--format','{{.Id}}'],timeout=10,capture=True).stdout.strip()
    if not IMAGE.fullmatch(image):raise ValueError('immutable built image ID not verified')
    base=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user','65532:65532','--memory','2g','--cpus','1','--pids-limit','64','--entrypoint','python',image,'-c']
    print("Checking the worker offline...",file=sys.stderr,flush=True)
    inventory=json.loads(command([*base,INVENTORY],timeout=60,capture=True).stdout)
    probe=json.loads(command([*base,PROBE],timeout=90,capture=True).stdout)
    if probe.get('parameter_gradient') != [2.,4.] or probe.get('cuda_available') is not False:raise ValueError('offline CPU package probe failed')
    context=ROOT/'runtime/cpu'
    receipt={'schema_version':'1.0','observed_at_utc':datetime.now(timezone.utc).isoformat(),'image':image,'architecture':arch,'docker_context':os.environ.get('DOCKER_CONTEXT','default'),'official_base':base_receipt,'wheels':wheel_rows,'recipe_files':{name:hashlib.sha256((context/name).read_bytes()).hexdigest() for name in ['Dockerfile',f'requirements-linux-{arch}.lock','.dockerignore']},'inventory':inventory,'offline_probe':probe,'build_context':'reviewed recipe plus only hash-verified dependency wheels; build network none','model_weights_included':False,'user_training_data_included':False}
    atomic_json(out/'worker-build.json',receipt)
    isolated=a.isolated_root.expanduser().resolve();isolated.mkdir(parents=True,exist_ok=True,mode=0o700)
    if a.configure:atomic_json(config,{'image':image,'isolated_root':str(isolated)})
    print(json.dumps({'image':image,'isolated_root':str(isolated),'receipt':str(out/'worker-build.json'),'configured':a.configure},ensure_ascii=False))
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,OSError,subprocess.SubprocessError,json.JSONDecodeError) as e:
        # Captured command output is withheld; no environment or credential
        # diagnostics are printed. Build progress itself contains package names.
        print('CPU worker setup failed: '+(str(e) if isinstance(e,ValueError) else type(e).__name__),file=sys.stderr);sys.exit(1)
