// Private, immutable snapshots of model-visible working inputs, excluding
// transport credentials. Never exported in a trained model bundle.
import {mkdir,readFile,writeFile,rename,lstat} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash,randomUUID} from 'node:crypto';

export const snapshotHash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const id = value => {
  if (typeof value!=='string' || !/^[A-Za-z0-9_-]{1,200}$/.test(value)) throw new Error('invalid native snapshot identity');
  return value;
};
async function safeDirectory(path) {
  await mkdir(path,{recursive:true,mode:0o700});
  if ((await lstat(path)).isSymbolicLink()) throw new Error('context snapshot directory is a symbolic link');
}
export function contextDiff(previous, current) {
  const fingerprints = value => {
    const counts=new Map();
    for(const item of value?.history || []) {const hash=snapshotHash(item);counts.set(hash,(counts.get(hash)||0)+1);}
    return counts;
  };
  const before=fingerprints(previous),after=fingerprints(current),added=[],removed=[];
  for(const [hash,count] of after)if(count>(before.get(hash)||0))added.push({sha256:hash,count:count-(before.get(hash)||0)});
  for(const [hash,count] of before)if(count>(after.get(hash)||0))removed.push({sha256:hash,count:count-(after.get(hash)||0)});
  return {added,removed,system_changed:previous?previous.baseInstructions!==current.baseInstructions:false,tools_changed:previous?snapshotHash(previous.tools)!==snapshotHash(current.tools):false};
}
export async function persistContextSnapshot(root, trace, wire) {
  if (!root || !trace.session_id) return null;
  const session=id(trace.session_id),snapshotId=randomUUID();
  const parent=join(root,'_workspace','context-snapshots');await safeDirectory(parent);
  const directory=join(parent,session);await safeDirectory(directory);
  let previous=null;
  try {
    const pointer=JSON.parse(await readFile(join(directory,'latest.json'),'utf8'));
    id(pointer.snapshot_id);
    previous=JSON.parse(await readFile(join(directory,pointer.snapshot_id+'.json'),'utf8'));
    if(previous.session_id!==session || previous.snapshot_sha256!==snapshotHash(Object.fromEntries(Object.entries(previous).filter(([key])=>key!=='snapshot_sha256'))))throw new Error('context snapshot parent digest mismatch');
  } catch(error) {if(error.code!=='ENOENT')throw error;}
  const value={schema_version:'1.0',snapshot_id:snapshotId,session_id:session,observed_at:new Date().toISOString(),
    provider:trace.provider,model:trace.model,purpose:trace.purpose,policy_revision:trace.policy_revision,
    parent_snapshot_id:previous?.snapshot_id || null,parent_snapshot_sha256:previous?.snapshot_sha256 || null,
    wire_context_sha256:snapshotHash(wire),wire,trace,diff:contextDiff(previous?.wire,wire),
    private_diagnostic:true,grants_execution_authorization:false};
  value.snapshot_sha256=snapshotHash(value);
  const serialized=JSON.stringify(value)+'\n';
  if(Buffer.byteLength(serialized)>32*1024*1024)throw new Error('context snapshot exceeds private diagnostic byte budget');
  await writeFile(join(directory,snapshotId+'.json'),serialized,{flag:'wx',mode:0o600});
  const temporary=join(directory,'latest-'+randomUUID()+'.tmp');
  await writeFile(temporary,JSON.stringify({snapshot_id:snapshotId,snapshot_sha256:value.snapshot_sha256})+'\n',{flag:'wx',mode:0o600});
  await rename(temporary,join(directory,'latest.json'));
  return {snapshot_id:snapshotId,snapshot_sha256:value.snapshot_sha256,parent_snapshot_id:value.parent_snapshot_id,diff:value.diff};
}
