const fs = require('fs');

const masterSpecPath = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\docs\\MASTER_SPEC.md';
const uatCasesPath = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\quality\\UAT_TEST_CASES.md';
const frontendCasesPath = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-frontend\\quality\\TEST_CASES.md';

function parseTable(filePath) {
  if (!fs.existsSync(filePath)) {
    return [];
  }
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const tcs = [];
  
  // Find where the table starts
  let inTable = false;
  let headers = [];
  
  for (let line of lines) {
    line = line.trim();
    if (line.startsWith('|') && line.endsWith('|')) {
      const parts = line.split('|').map(x => x.trim()).filter((x, i) => i > 0 && i < line.split('|').length - 1);
      if (parts.length === 0) continue;
      
      // Skip separator lines e.g. | :--- | :--- |
      if (parts.every(p => p.startsWith(':') || p.startsWith('-') || p.endsWith('-') || p.trim() === '')) {
        continue;
      }
      
      if (!inTable) {
        // First row as headers
        headers = parts;
        inTable = true;
        continue;
      }
      
      // Check if it's a test case line
      const tcNamePart = parts[0];
      if (tcNamePart && (tcNamePart.includes('TC') || tcNamePart.startsWith('`TC'))) {
        const cleanName = tcNamePart.replace(/`/g, '').trim();
        tcs.push({
          name: cleanName,
          row: parts,
          file: filePath
        });
      }
    } else {
      if (inTable && line === '') {
        // Table might have ended or just empty line
      }
    }
  }
  return { headers, tcs };
}

const master = parseTable(masterSpecPath);
const uat = parseTable(uatCasesPath);
const frontend = parseTable(frontendCasesPath);

console.log(`MASTER_SPEC.md: ${master.tcs.length} TCs parsed.`);
console.log(`UAT_TEST_CASES.md: ${uat.tcs.length} TCs parsed.`);
console.log(`frontend/TEST_CASES.md: ${frontend.tcs.length} TCs parsed.`);

console.log('\n--- UAT TEST CASES HEADERS ---');
console.log(uat.headers.join(' | '));

console.log('\n--- FIRST 5 TCs in frontend/TEST_CASES.md ---');
frontend.tcs.slice(0, 5).forEach(tc => {
  console.log(`- ${tc.name}: ${tc.row.slice(1, 4).join(' | ')}`);
});

console.log('\n--- COMPARE TEST NAMES ---');
const uatSet = new Set(uat.tcs.map(t => t.name));
const masterSet = new Set(master.tcs.map(t => t.name));
const frontendSet = new Set(frontend.tcs.map(t => t.name));

const onlyInMaster = master.tcs.filter(t => !uatSet.has(t.name)).map(t => t.name);
const onlyInUat = uat.tcs.filter(t => !masterSet.has(t.name)).map(t => t.name);

console.log(`Only in MASTER_SPEC: ${onlyInMaster.length}`);
console.log(onlyInMaster.slice(0, 10));
if (onlyInMaster.length > 10) console.log('...');

console.log(`Only in UAT_TEST_CASES: ${onlyInUat.length}`);
console.log(onlyInUat.slice(0, 10));
if (onlyInUat.length > 10) console.log('...');
