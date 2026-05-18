const fs = require('fs');
const content = fs.readFileSync('c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\quality\\UAT_TEST_CASES.md', 'utf8');

const lines = content.split('\n');
console.log(`Total lines: ${lines.length}`);

// Print lines that start with "#" or contain "TC0" or "TC1"
lines.forEach((line, idx) => {
  if (line.trim().startsWith('#') || line.includes('TC0') || line.includes('TC1')) {
    if (line.length < 150) {
      console.log(`${idx + 1}: ${line.trim()}`);
    } else {
      console.log(`${idx + 1}: [Long line] ${line.trim().substring(0, 100)}...`);
    }
  }
});
