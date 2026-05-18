const fs = require('fs');
const path = require('path');

const routersDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\app\\api\\routers';
const files = fs.readdirSync(routersDir).filter(f => f.endsWith('.py'));

console.log('Searching for limits/validations/exceptions:');
files.forEach(file => {
  const content = fs.readFileSync(path.join(routersDir, file), 'utf8');
  const lines = content.split('\n');
  lines.forEach((line, idx) => {
    if (line.includes('limit') || line.includes('max') || line.includes('exceed') || line.includes('validation') || line.includes('count')) {
      console.log(`[${file}:${idx+1}]: ${line.trim()}`);
    }
  });
});
