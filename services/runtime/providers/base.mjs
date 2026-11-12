// Implement per provider; never silently simulate a live answer.
export class Provider { capabilities(){return [];} estimate(){throw Error('Missing verified price sheet');} async invoke(){throw Error('Provider not configured');} }

