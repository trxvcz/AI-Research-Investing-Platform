import test from 'node:test';
import assert from 'node:assert/strict';
import {assertArchiveIdentity,documentReadingOptions,selectImportAttempt} from '../src/document-archive-state.ts';

test('new HTML imports keep table boundaries and require explicit number syntax',()=>{
  assert.deepEqual(documentReadingOptions('html',''),{reader_version:'table-text-v2'});
  assert.deepEqual(documentReadingOptions('html','en-US'),{reader_version:'table-text-v2',number_locale:'en-US'});
  for(const format of ['text','pdf','xlsx'])assert.deepEqual(documentReadingOptions(format,'en-US'),{});
  assert.throws(()=>documentReadingOptions('html','unknown'));
});

test('unresolved import cannot change frozen reader or number syntax',()=>{
  const payload={format:'html',...documentReadingOptions('html','')};
  const pending=selectImportAttempt(payload,undefined,()=> 'new-id');
  assert.equal(selectImportAttempt(payload,pending,()=>{throw Error('must reuse');}),pending);
  assert.throws(()=>selectImportAttempt({...payload,number_locale:'en-US'},pending,()=>''));
  assert.throws(()=>selectImportAttempt({format:'html'},pending,()=>''));
});

test('returned packet and archived reader options must agree',()=>{
  const options={reader_version:'table-text-v2',number_locale:'en-US'};
  const record={archive_id:'one',...options,packet:{document_id:'one',...options},result:{document_id:'one'}};
  assert.doesNotThrow(()=>assertArchiveIdentity(record,'one'));
  assert.throws(()=>assertArchiveIdentity({...record,packet:{...record.packet,number_locale:null}},'one'));
  assert.throws(()=>assertArchiveIdentity({...record,reader_version:null},'one'));
  assert.doesNotThrow(()=>assertArchiveIdentity({archive_id:'one',packet:{document_id:'one'},result:{document_id:'one'}},'one'));
});
