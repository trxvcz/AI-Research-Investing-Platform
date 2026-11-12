export function analyze(d){const c=d.closes;return {sma3:c.slice(-3).reduce((a,b)=>a+b,0)/3,last:c.at(-1),signal:'none; synthetic fixture'};}

