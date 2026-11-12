import test from 'node:test';
import assert from 'node:assert/strict';
import {assertPreviewIdentity,samePreviewSelection} from '../src/document-preview-state.ts';

const expected={document_id:'one',format:'html',classification:'private',reader_version:'table-text-v2',number_locale:'en-US',sha256:'a'.repeat(64),byte_length:100};
const packet={schema_version:'1.0',...expected,blocks:[{block_id:'block-1',locator:'html:block:1',text:'Revenue | 281,724'}]};
const result={packet,byte_length:100,model_called:false,persisted:false};

test('preview is bound to original bytes, classification and selected reading options',()=>{
  assert.doesNotThrow(()=>assertPreviewIdentity(result,expected));
  for(const update of [{document_id:'other'},{sha256:'b'.repeat(64)},{format:'text'},{classification:'public'},{reader_version:null},{number_locale:null}])assert.throws(()=>assertPreviewIdentity({...result,packet:{...packet,...update}},expected));
  for(const update of [{byte_length:99},{model_called:true},{persisted:true}])assert.throws(()=>assertPreviewIdentity({...result,...update},expected));
});

test('preview rejects malformed, missing or oversized blocks before display',()=>{
  for(const blocks of [[],null,[{...packet.blocks[0],text:''}],[{...packet.blocks[0],text:'x'.repeat(32769)}],[{...packet.blocks[0],block_id:'other'}],[{...packet.blocks[0],locator:'x'.repeat(257)}]])assert.throws(()=>assertPreviewIdentity({...result,packet:{...packet,blocks}},expected));
  assert.throws(()=>assertPreviewIdentity({...result,packet:null},expected));
});

test('legacy preview may omit reader options but must still match the requested bytes',()=>{
  const old={...expected,format:'text',reader_version:undefined,number_locale:undefined};
  assert.doesNotThrow(()=>assertPreviewIdentity({...result,packet:{...packet,...old}},old));
});

test('an old preview is not visible for another file or changed interpretation',()=>{
  const file={name:'report.html'};
  const saved={file,format:'html',classification:'private',numberLocale:''};
  assert.equal(samePreviewSelection(saved,{...saved}),true);
  for(const update of [{file:{name:'report.html'}},{file:undefined},{format:'text'},{classification:'public'},{numberLocale:'en-US'}])assert.equal(samePreviewSelection(saved,{...saved,...update}),false);
});

test('preview character bounds match Unicode codepoints rather than UTF16 units',()=>{
  const block={...packet.blocks[0],text:'😀'.repeat(32768)};
  assert.doesNotThrow(()=>assertPreviewIdentity({...result,packet:{...packet,blocks:[block]}},expected));
  assert.throws(()=>assertPreviewIdentity({...result,packet:{...packet,blocks:[{...block,text:block.text+'😀'}]}},expected));
});
