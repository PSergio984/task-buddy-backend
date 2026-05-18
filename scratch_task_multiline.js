const fs = require('fs');
const content = fs.readFileSync('c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\app\\api\\routers\\task.py', 'utf8');

const lines = content.split('\n');
let decoratorLines = [];
lines.forEach((line, index) => {
  const trimmed = line.trim();
  if (trimmed.startsWith('@router.')) {
    decoratorLines = [trimmed];
    let i = index + 1;
    while (i < lines.length && !lines[i].trim().startsWith('async def ') && !lines[i].trim().startsWith('def ')) {
      decoratorLines.push(lines[i].trim());
      i++;
    }
    const functionLine = i < lines.length ? lines[i].trim() : '[EOF reached]';
    console.log(`${index + 1}: ${decoratorLines.join(' ')} -> ${functionLine}`);
  }
});
