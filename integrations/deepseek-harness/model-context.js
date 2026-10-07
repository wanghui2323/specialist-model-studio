// Provider-neutral transport projection over immutable native messages.
// The SDK's frozen Agent-loop request and durable log are never rewritten.
// Adapters may use this derived working set when serializing their wire input.
import {createHash} from 'node:crypto';

export const CONTEXT_POLICY_REVISION = 'working-set-v3';
const digest = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');
const bytes = value => Buffer.byteLength(JSON.stringify(value),'utf8');
const MACHINE_NOTIFICATIONS = new Set(['subagent-report','subagent-settled']);
const isFactSnapshot = message => message.source?.kind==='plugin' && message.source.plugin==='specialist-model-studio-facts' && message.source.form==='snapshot';

function receipt(content, identity) {
  return {type:'text',text:JSON.stringify({
    context_view:'historical_evidence_reference_only',
    policy_revision:CONTEXT_POLICY_REVISION,
    ...identity,
    original_content_sha256:digest(content),
    original_bytes:bytes(content),
    grants_execution_authorization:false,
    instruction:'Original evidence remains in native history and the task evidence store. This is not current task state, source code, or approval. Re-read the exact task, proposal, Run or report before editing, making a status claim or requesting approval.'
  })};
}

export function prepareModelContext(options, {recentMessages=6, receiptThresholdBytes=2048}={}) {
  if (!Number.isInteger(recentMessages) || recentMessages<1 || !Number.isInteger(receiptThresholdBytes) || receiptThresholdBytes<512) throw new TypeError('invalid context policy budget');
  const original=options.messages || [], calls=new Map(), archived=[];
  for (const message of original) for (const block of message.content || []) {
    if (block.type==='tool-call') calls.set(String(block.id),block.name);
  }
  const cutoff=Math.max(0,original.length-recentMessages);
  let latestFailure=-1,latestFactSnapshot=-1;
  for(let i=0;i<original.length;i++) {
    if((original[i].content||[]).some(b=>b.type==='tool-result'&&b.isError===true))latestFailure=i;
    if(isFactSnapshot(original[i]))latestFactSnapshot=i;
  }
  const messages=original.map((message,index)=>{
    // Current trusted facts remain full. Older host snapshots describe past
    // state and must not compete with today's owner/Run/approval facts.
    // Typed plugin provenance is required; ordinary user text is untouched.
    if (isFactSnapshot(message) && index!==latestFactSnapshot && message.role!=='system') {
      const textBlocks=(message.content||[]).filter(block=>block.type==='text');
      if (!textBlocks.length) return message;
      archived.push({kind:'host_fact_snapshot',message_index:index,content_sha256:digest(textBlocks)});
      return {...message,content:[receipt(textBlocks,{source_kind:'plugin',plugin:message.source.plugin,message_index:index}),...message.content.filter(block=>block.type!=='text')]};
    }
    if (index>=cutoff || index===latestFailure || index===latestFactSnapshot || message.role==='system') return message;
    if (MACHINE_NOTIFICATIONS.has(message.source?.kind) && bytes(message.content)>receiptThresholdBytes) {
      const source=message.source;
      const textBlocks=(message.content || []).filter(block=>block.type==='text');
      if (!textBlocks.length) return message;
      const replacement=receipt(textBlocks,{source_kind:source.kind,sender_session_id:source.senderSessionId,terminal_notice:source.summary || null});
      archived.push({kind:'machine_notification',message_index:index,content_sha256:digest(textBlocks),source_kind:source.kind});
      // Rich content remains present; only historical machine text is externalized.
      return {...message,content:[replacement,...message.content.filter(block=>block.type!=='text')]};
    }
    let changed=false;
    const content=(message.content || []).map(block=>{
      // Ordinary user text, including malicious text that resembles a tool
      // envelope, is always verbatim. Native tool results are typed blocks.
      if (block.type!=='tool-result' || bytes(block.content)<=receiptThresholdBytes) return block;
      const textBlocks=block.content.filter(part=>part.type==='text');
      if (!textBlocks.length) return block;
      changed=true;
      const id=String(block.toolCallId), name=calls.get(id) || null;
      archived.push({kind:'tool_result',call_id:id,tool_name:name,content_sha256:digest(textBlocks),message_index:index,is_error:block.isError===true});
      return {...block,content:[receipt(textBlocks,{tool_call_id:id,tool_name:name,is_error:block.isError===true}),...block.content.filter(part=>part.type!=='text')]};
    });
    return changed?{...message,content}:message;
  });
  // A native auxiliary compaction call summarizes evidence; it cannot execute
  // product operations. Tool schemas waste its budget and invite tool output.
  // `purpose` is a runtime field, never inferred from a user's chat text.
  const compaction=options.purpose==='compaction';
  const wireMessages=compaction?messages.map((message,index)=>index===messages.length-1&&message.source?.kind==='plugin'&&message.source?.plugin==='dsh-compaction-basic'?{...message,role:'system'}:message):messages;
  return {
    messages:wireMessages,
    tools:compaction?[]:options.tools,
    trace:{policy_revision:CONTEXT_POLICY_REVISION,recent_messages:recentMessages,receipt_threshold_bytes:receiptThresholdBytes,protected_latest_failure_index:latestFailure,current_fact_snapshot_index:latestFactSnapshot,
      original_messages_sha256:digest(original),working_messages_sha256:digest(wireMessages),
      original_bytes:bytes({system:options.system,messages:original,tools:options.tools}),
      working_bytes:bytes({system:options.system,messages:wireMessages,tools:compaction?[]:options.tools}),
      compaction_tool_schemas_excluded:compaction,archived}
  };
}
