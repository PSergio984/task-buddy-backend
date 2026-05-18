const fs = require('fs');

function parseTable(filePath) {
  if (!fs.existsSync(filePath)) {
    return [];
  }
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const tcs = [];
  
  let inTable = false;
  let headers = [];
  
  for (let line of lines) {
    line = line.trim();
    if (line.startsWith('|') && line.endsWith('|')) {
      const parts = line.split('|').map(x => x.trim()).filter((x, i) => i > 0 && i < line.split('|').length - 1);
      if (parts.length === 0) continue;
      
      if (parts.every(p => p.startsWith(':') || p.startsWith('-') || p.endsWith('-') || p.trim() === '')) {
        continue;
      }
      
      if (!inTable) {
        headers = parts;
        inTable = true;
        continue;
      }
      
      const tcNamePart = parts[0];
      if (tcNamePart && (tcNamePart.includes('TC') || tcNamePart.startsWith('`TC'))) {
        const cleanName = tcNamePart.replace(/`/g, '').trim();
        tcs.push({
          name: cleanName,
          desc: parts[3] || '',
          row: parts
        });
      }
    }
  }
  return tcs;
}

const uatTcs = parseTable('c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\quality\\UAT_TEST_CASES.md');
console.log(`Parsed ${uatTcs.length} test cases from UAT_TEST_CASES.md:`);
uatTcs.forEach(tc => {
  console.log(`- ${tc.name}: ${tc.desc}`);
});
