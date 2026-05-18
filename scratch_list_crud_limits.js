const fs = require('fs');
const path = require('path');

const crudDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\app\\crud';
if (fs.existsSync(crudDir)) {
  const files = fs.readdirSync(crudDir).filter(f => f.endsWith('.py'));
  files.forEach(file => {
    const content = fs.readFileSync(path.join(crudDir, file), 'utf8');
    const lines = content.split('\n');
    lines.forEach((line, idx) => {
      if (line.includes('limit') || line.includes('max') || line.includes('quota') || line.includes('count') || line.includes('50')) {
        console.log(`[${file}:${idx+1}]: ${line.trim()}`);
      }
    });
  });
}
