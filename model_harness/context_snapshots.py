"""Read private model-input snapshots only through an owned native session."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from typing import Any
from .context_state import ContextStateError


class ContextSnapshotReader:
    def __init__(self, workspace_root: Path):
        self.root=Path(workspace_root).resolve()/'context-snapshots'

    def directory(self, session_id: str) -> Path:
        if not isinstance(session_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',session_id):
            raise ContextStateError('invalid native snapshot session')
        path=self.root/session_id
        if self.root.is_symlink() or path.is_symlink(): raise ContextStateError('snapshot directory is a symbolic link')
        return path

    def read(self, session_id: str, snapshot_id: str) -> dict[str, Any]:
        if not isinstance(snapshot_id,str) or not re.fullmatch(r'[a-f0-9-]{36}',snapshot_id):
            raise ContextStateError('invalid snapshot id')
        path=self.directory(session_id)/(snapshot_id+'.json')
        if path.is_symlink(): raise ContextStateError('snapshot file is a symbolic link')
        raw=path.read_text(encoding='utf8').strip()
        # JS JSON.stringify preserves the exact wire representation. Verify
        # its original bytes rather than reserializing floats in Python.
        match=re.search(r',"snapshot_sha256":"([a-f0-9]{64})"}$',raw)
        if not match or hashlib.sha256((raw[:match.start()]+'}').encode()).hexdigest()!=match[1]:
            raise ContextStateError('snapshot digest mismatch')
        value=json.loads(raw)
        if value.get('session_id')!=session_id or value.get('snapshot_id')!=snapshot_id or value.get('schema_version')!='1.0':
            raise ContextStateError('snapshot identity mismatch')
        return value

    def list(self, session_id: str, limit: int=12) -> list[dict[str, Any]]:
        path=self.directory(session_id)
        files=sorted((p for p in path.glob('*.json') if p.name!='latest.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:limit]
        result=[]
        for file in files:
            value=self.read(session_id,file.stem)
            result.append({key:value.get(key) for key in ('snapshot_id','snapshot_sha256','session_id','observed_at','provider','model','purpose','policy_revision','parent_snapshot_id','parent_snapshot_sha256','wire_context_sha256','diff','private_diagnostic','grants_execution_authorization')})
            result[-1]['budget']=value.get('trace',{}).get('assessment')
        return result

    def section(self, session_id: str, snapshot_id: str, section: str, start: int=0, max_chars: int=4000) -> dict[str, Any]:
        if section not in {'system','history','tools','trace','diff'} or type(start)is not int or start<0 or type(max_chars)is not int or not 1<=max_chars<=8000:
            raise ContextStateError('invalid snapshot section or range')
        value=self.read(session_id,snapshot_id)
        content=value['wire'].get('baseInstructions','') if section=='system' else value['wire'].get(section) if section in {'history','tools'} else value.get(section)
        text=content if isinstance(content,str) else json.dumps(content,ensure_ascii=False,indent=2)
        return {'snapshot_id':snapshot_id,'snapshot_sha256':value['snapshot_sha256'],'session_id':session_id,'section':section,'text':text[start:start+max_chars],'start':start,'end':min(len(text),start+max_chars),'total_chars':len(text),'complete':start==0 and max_chars>=len(text),'has_more':start+max_chars<len(text),'view':'public_redacted_snapshot_excerpt','grants_execution_authorization':False}
