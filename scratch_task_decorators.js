const fs = require('fs');
const content = fs.readFileSync('c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\app\\api\\routers\\task.py', 'utf8');

const lines = content.split('\n');
lines.forEach((line, index) => {
  if (line.includes('@router.') || line.trim().startsWith('async def ') || line.trim().startsWith('def ')) {
    console.log(`${index + 1}: ${line.trim()}`);
  }
});
