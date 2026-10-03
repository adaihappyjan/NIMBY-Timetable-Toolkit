// Enumerate string literals without evaluating application code.
const fs = require('node:fs');
const acorn = require('acorn');
const file = process.argv[2];
const source = fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');
const spans = [];
const semanticMethods = new Set(['includes','startsWith','endsWith','match','matchAll','replace','replaceAll','split','indexOf','lastIndexOf','search','test']);
function walk(node, parent, key) {
  if (!node || typeof node !== 'object') return;
  // Keep data classifiers, object keys and regular expressions language-neutral.
  const semantic = parent && ((parent.type === 'Property' && key === 'key') ||
    (parent.type === 'CallExpression' && parent.callee?.type === 'MemberExpression' && semanticMethods.has(parent.callee.property?.name)) ||
    (parent.type === 'BinaryExpression' && ['===','!==','==','!='].includes(parent.operator)));
  if (!semantic && node.type === 'Literal' && typeof node.value === 'string' && /[\u3400-\u9fff]/.test(node.value)) {
    spans.push({start:node.start,end:node.end,text:node.value,kind:'string'});
  }
  if (node.type === 'TemplateElement' && /[\u3400-\u9fff]/.test(node.value.cooked || '')) {
    spans.push({start:node.start,end:node.end,text:node.value.cooked,kind:'template'});
  }
  for (const [k,v] of Object.entries(node)) {
    if (Array.isArray(v)) v.forEach(n => walk(n,node,k));
    else if (v && typeof v === 'object') walk(v,node,k);
  }
}
walk(acorn.parse(source,{ecmaVersion:'latest',sourceType:'script'}));
// Python offsets count Unicode code points, not UTF-16 code units.
for (const span of spans) {
  span.start = [...source.slice(0,span.start)].length;
  span.end = [...source.slice(0,span.end)].length;
}
process.stdout.write(JSON.stringify(spans));
