export function loadDemo(type='equity') {
 if(!['equity','commodity'].includes(type)) throw Error('unsupported asset');
 return {asset_id:type==='equity'?'DEMO-EQUITY':'DEMO-COMMODITY',asset_type:type,as_of:'2024-01-10T00:00:00Z',available_at:'2024-01-09T00:00:00Z',currency:'USD',unit:type==='equity'?'share':'unit',source_id:'synthetic-demo',closes:[100,101,99,102,103,101,104,105],revenue:1000,net_income:100,inventories:50};
}
export function validateData(d){if(Date.parse(d.available_at)>Date.parse(d.as_of)||!Number.isFinite(Date.parse(d.available_at))||!Number.isFinite(Date.parse(d.as_of)))throw Error('point-in-time violation');if(!d.closes?.length||d.closes.some(x=>!Number.isFinite(x)||x<=0))throw Error('invalid prices');}

