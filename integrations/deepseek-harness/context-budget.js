// Byte bounds are enforced transport/work limits. Token counts are planning
// estimates unless a provider supplies an exact tokenizer; do not conflate them.
export function contextBudget(config={}) {
  const input=config.maxInputBytes??750000,summary=config.maxSummaryBytes??300000,output=config.maxOutputBytes??64000;
  for(const value of [input,summary,output])if(!Number.isInteger(value)||value<4096||value>4*1024*1024)throw new TypeError('invalid context byte budget');
  if(summary>input)throw new TypeError('summary input budget must fit the normal input budget');
  const fragments=config.maxSummaryFragments??8;
  if(!Number.isInteger(fragments)||fragments<1||fragments>32)throw new TypeError('invalid summary fragment count');
  return {max_input_bytes:input,max_summary_bytes:summary,max_output_bytes:output,max_summary_fragments:fragments,
    token_estimate_source:'utf8_bytes_div_3_heuristic_not_exact',output_limit_unit:'utf8_bytes'};
}
export function budgetAssessment(bytes,purpose,budget) {
  const limit=purpose==='compaction'?budget.max_summary_bytes:budget.max_input_bytes;
  const ratio=bytes/limit;
  return {input_bytes:bytes,input_byte_limit:limit,ratio,estimated_text_tokens:Math.ceil(bytes/3),estimate_source:budget.token_estimate_source,
    action:ratio>1?'split_or_reject':ratio>=.9?'prepare_recovery':ratio>=.75?'compact':ratio>=.6?'externalize':'within_budget'};
}

export function balancedMessageGroups(messages) {
  const groups=[],pending=new Set();let group=[];
  for(const message of messages) {
    group.push(message);
    for(const block of message.content||[]) {
      if(block.type==='tool-call') {if(pending.has(String(block.id)))throw new Error('duplicate pending tool call');pending.add(String(block.id));}
      if(block.type==='tool-result') {if(!pending.delete(String(block.toolCallId)))throw new Error('tool result without its source call');}
    }
    if(!pending.size) {groups.push(group);group=[];}
  }
  if(pending.size)throw new Error('cannot compact an incomplete tool call/result pair');
  return groups;
}

export function splitContextMessages(messages,maxBytes,overheadBytes=0) {
  if(!Number.isInteger(maxBytes)||maxBytes<4096||overheadBytes>=maxBytes)throw new Error('context fragment has no available input budget');
  const groups=balancedMessageGroups(messages),chunks=[];let current=[],used=overheadBytes;
  for(const group of groups) {
    const cost=Buffer.byteLength(JSON.stringify(group),'utf8');
    if(cost+overheadBytes>maxBytes)throw new Error('one required message/tool pair exceeds the fragment budget; use bounded source evidence');
    if(current.length&&used+cost>maxBytes) {chunks.push(current);current=[];used=overheadBytes;}
    current.push(...group);used+=cost;
  }
  if(current.length)chunks.push(current);
  return chunks;
}

export function verifiedSummaryQuotes(summary,messages) {
  const source=[];
  for(let i=0;i<messages.length;i++) {
    const message=messages[i];
    if(message.source?.kind==='plugin')continue;
    for(const block of message.content||[]) {
      if(block.type==='text') {
        let text=block.text;
        if(message.source?.kind==='user'&&text.includes('USER_MESSAGE:\n'))text=text.slice(text.indexOf('USER_MESSAGE:\n')+'USER_MESSAGE:\n'.length);
        source.push({message_index:i,role:message.role,source_kind:message.source?.kind||'unspecified',text});
      }
    }
  }
  const result=[];
  for(const match of summary.matchAll(/[“"]([^”"\n]{2,2000})[”"]/gu)) {
    const quote=match[1];const found=source.find(item=>item.text.includes(quote));
    if(found&&!result.some(item=>item.quote===quote)) {
      const offset=found.text.indexOf(quote),start=Math.max(0,offset-120),end=Math.min(found.text.length,offset+quote.length+120);
      result.push({quote,message_index:found.message_index,role:found.role,source_kind:found.source_kind,source_char_start:start,source_char_end:end,source_context:found.text.slice(start,end),context_complete:start===0&&end===found.text.length});
    }
  }
  return result;
}
