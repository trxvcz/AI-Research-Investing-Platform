import type {components} from './schema';

type Model=components['schemas'];
export type PreviewCreate=Required<Omit<Model['DocumentPreviewCreate'],'reader_version'|'number_locale'>>&Pick<Model['DocumentPreviewCreate'],'reader_version'|'number_locale'>;
export type PreviewResult=Model['DocumentPreviewResult'];
export type PreviewExpected=Pick<PreviewCreate,'document_id'|'format'|'classification'|'reader_version'|'number_locale'>&{sha256:string;byte_length:number};
export type PreviewSelection={file:File|undefined;format:PreviewCreate['format'];classification:PreviewCreate['classification'];numberLocale:''|'en-US'};

export function samePreviewSelection(saved:PreviewSelection,current:PreviewSelection):boolean {
  return saved.file===current.file&&saved.format===current.format&&saved.classification===current.classification&&saved.numberLocale===current.numberLocale;
}

export function assertPreviewIdentity(result:PreviewResult,expected:PreviewExpected):void {
  const packet=result?.packet;
  if(!packet||result.model_called!==false||result.persisted!==false
    ||result.byte_length!==expected.byte_length||packet.document_id!==expected.document_id
    ||packet.sha256!==expected.sha256||packet.format!==expected.format||packet.classification!==expected.classification
    ||(packet.reader_version??null)!==(expected.reader_version??null)
    ||(packet.number_locale??null)!==(expected.number_locale??null)
    ||packet.schema_version!=='1.0'||!Array.isArray(packet.blocks)||packet.blocks.length<1||packet.blocks.length>512) {
    throw Error('Podgląd nie odpowiada wybranemu dokumentowi i ustawieniom.');
  }
  let total=0;
  const encoder=new TextEncoder();
  for(const [index,block] of packet.blocks.entries()){
    if(!block||block.block_id!==`block-${index+1}`||typeof block.locator!=='string'||!block.locator||block.locator.length>512||Array.from(block.locator).length>256
      ||typeof block.text!=='string'||!block.text.trim()||block.text.length>65536||Array.from(block.text).length>32768||block.text.includes('\0'))throw Error('Nieprawidłowe bloki podglądu.');
    total+=encoder.encode(block.text).byteLength;
    if(total>2097152)throw Error('Przekroczono limit tekstu podglądu.');
  }
}
