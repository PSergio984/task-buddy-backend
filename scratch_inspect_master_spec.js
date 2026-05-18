const fs = require('fs');
const content = fs.readFileSync('c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\docs\\MASTER_SPEC.md', 'utf8');

const lines = content.split('\n');
console.log(`Total lines: ${lines.length}`);

let count = 0;
lines.forEach((line, idx) => {
  if (line.includes('TC') && count < 40) {
    console.log(`${idx + 1}: ${line.trim()}`);
    count++;
  }
});
