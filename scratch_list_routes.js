const fs = require('fs');
const path = require('path');

const routersDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\app\\api\\routers';
const files = fs.readdirSync(routersDir).filter(f => f.endsWith('.py'));

const results = {};

files.forEach(file => {
  const content = fs.readFileSync(path.join(routersDir, file), 'utf8');
  const lines = content.split('\n');
  const routes = [];
  let currentDecorators = [];
  
  lines.forEach((line, index) => {
    const trimmed = line.trim();
    if (trimmed.startsWith('@router.')) {
      currentDecorators.push({ line: trimmed, lineNum: index + 1 });
    } else if (trimmed.startsWith('async def ')) {
      if (currentDecorators.length > 0) {
        routes.push({
          decorators: currentDecorators.map(d => d.line),
          func: trimmed.split('(')[0],
          lineNum: currentDecorators[0].lineNum
        });
        currentDecorators = [];
      }
    } else if (!trimmed.startsWith('#') && trimmed !== '') {
      if (!trimmed.startsWith('@')) {
        currentDecorators = [];
      }
    }
  });
  
  results[file] = routes;
});

console.log(JSON.stringify(results, null, 2));
