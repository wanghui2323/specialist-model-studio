"""Verify the pinned official Python manifest and prepare its exact local base.

Docker VM CDN connectivity may differ from the host. If the verified config
isn't cached, copy hash-verified official blobs on the host and use docker load;
never unpack or execute image files on the host, and never forward registry
credentials to a CDN. This is an operator setup helper, not Agent code.
"""
import hashlib
import json
import ssl
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

INDEX='sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f'
REGISTRY='https://registry-1.docker.io/v2/library/python/'
ACCEPT='application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        parsed=urllib.parse.urlsplit(newurl)
        if parsed.scheme!='https':raise ValueError('registry redirect requires HTTPS')
        redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
        if parsed.netloc!=urllib.parse.urlsplit(req.full_url).netloc:redirected.remove_header('Authorization')
        return redirected

def sha(data):return 'sha256:'+hashlib.sha256(data).hexdigest()

def prepare(arch):
    if arch not in ('arm64','amd64'):raise ValueError('base architecture not reviewed')
    # Use system trust plus certifi when available; certificate verification
    # stays enabled. No global proxy or Docker VM setting is changed.
    try:
        import certifi
        ctx=ssl.create_default_context(cafile=certifi.where())
    except ImportError:ctx=ssl.create_default_context()
    opener=urllib.request.build_opener(urllib.request.HTTPSHandler(context=ctx),SafeRedirect())
    token=None
    metadata_dir=Path(__file__).resolve().parents[1]/'runtime/cpu/base-manifests'
    def fetch(path,digest=None,metadata=False):
        metadata_file=metadata_dir/(digest.split(':')[1]+'.json') if digest and metadata else None
        if metadata_file and metadata_file.is_file():
            saved=metadata_file.read_bytes()
            if sha(saved)!=digest:raise ValueError('pinned base metadata digest mismatch')
            return saved
        nonlocal token
        if token is None:token=json.load(opener.open('https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull',timeout=20))['token']
        req=urllib.request.Request(REGISTRY+path,headers={'Authorization':'Bearer '+token,'Accept':ACCEPT})
        with opener.open(req,timeout=60) as r:data=r.read(256*1024*1024+1)
        if len(data)>256*1024*1024 or digest and sha(data)!=digest:raise ValueError('official base blob size/digest mismatch')
        if metadata_file:
            metadata_dir.mkdir(exist_ok=True);metadata_file.write_bytes(data)
        return data
    index=json.loads(fetch('manifests/'+INDEX,INDEX,True));row=next(x for x in index['manifests'] if x['platform'].get('os')=='linux' and x['platform'].get('architecture')==arch)
    manifest=json.loads(fetch('manifests/'+row['digest'],row['digest'],True));config=manifest['config']['digest'];
    config_bytes=fetch('blobs/'+config,config,True);cfg=json.loads(config_bytes)
    def inspect_base(reference):
        checked=subprocess.run(['docker','image','inspect',reference],capture_output=True,text=True,timeout=10)
        if checked.returncode:return None
        actual=json.loads(checked.stdout)[0]
        # Docker's legacy loader can reserialize OCI configuration JSON. The
        # exact official filesystem diff IDs and executable configuration must
        # match; the real resulting local image ID is used, never fabricated.
        if actual.get('Architecture')!=arch or actual.get('Os')!='linux' or actual.get('RootFS',{}).get('Layers')!=cfg.get('rootfs',{}).get('diff_ids'):return None
        for key in ['Env','Cmd','Entrypoint','User','WorkingDir','ExposedPorts','Volumes']:
            if (actual.get('Config',{}).get(key) or None)!=(cfg.get('config',{}).get(key) or None):return None
        return actual['Id']
    cached_id=inspect_base(config) or inspect_base('specialist-model-studio-python-base:3.12.15')
    receipt={'source_index':INDEX,'platform_manifest':row['digest'],'image_config':config,'architecture':arch,'cached':bool(cached_id)}
    if receipt['cached']:
        receipt['local_image_id']=cached_id;receipt['config_reserialized']=cached_id!=config;return cached_id,receipt
    if cfg.get('architecture')!=arch or cfg.get('os')!='linux':raise ValueError('base configuration platform mismatch')
    with tempfile.TemporaryDirectory(prefix='sms-python-base-') as tmp:
        root=Path(tmp);config_name=config.split(':')[1]+'.json';(root/config_name).write_bytes(config_bytes);layers=[]
        for i,layer in enumerate(manifest['layers']):
            name=str(i)+'/layer.tar';file=root/name;file.parent.mkdir();file.write_bytes(fetch('blobs/'+layer['digest'],layer['digest']));layers.append(name)
        (root/'manifest.json').write_text(json.dumps([{'Config':config_name,'RepoTags':['specialist-model-studio-python-base:3.12.15'],'Layers':layers}]))
        archive=root/'base.tar'
        with tarfile.open(archive,'w') as tar:
            for name in [config_name,'manifest.json',*layers]:tar.add(root/name,arcname=name)
        result=subprocess.run(['docker','load','--input',str(archive)],capture_output=True,text=True,timeout=120)
        if result.returncode:raise ValueError('verified official base image could not be loaded')
    observed=inspect_base(config) or inspect_base('specialist-model-studio-python-base:3.12.15')
    if not observed:raise ValueError('loaded official filesystem/executable configuration mismatch')
    receipt['local_image_id']=observed;receipt['config_reserialized']=observed!=config
    return observed,receipt
