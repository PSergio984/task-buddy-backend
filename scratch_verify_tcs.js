const fs = require('fs');
const path = require('path');

const uatPath = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\quality\\UAT_TEST_CASES.md';
const frontendUatPath = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-frontend\\quality\\TEST_CASES.md';

function parseUatFile(filePath) {
  if (!fs.existsSync(filePath)) {
    console.log('File not found:', filePath);
    return [];
  }
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const tcs = [];
  
  let currentTC = null;
  
  for (let line of lines) {
    line = line.trim();
    if (line.startsWith('|') && line.endsWith('|')) {
      const rawParts = line.split('|');
      const parts = rawParts.slice(1, -1).map(s => s.trim());
      if (parts.length === 0) continue;
      
      // Check if separator line
      if (parts.every(p => /^:?-+:?$/.test(p) || p === '')) {
        continue;
      }
      
      const tcNamePart = parts[0];
      const isTCHeader = tcNamePart && (tcNamePart.includes('TC') || tcNamePart.startsWith('`TC'));
      
      if (isTCHeader) {
        const cleanName = tcNamePart.replace(/`/g, '').trim();
        if (cleanName && parts.length >= 4) {
          currentTC = {
            name: cleanName,
            positiveNegative: parts[1] || '',
            type: parts[2] || '',
            description: parts[3] || '',
            precondition: parts[4] || '',
            steps: []
          };
          tcs.push(currentTC);
        }
      }
      
      if (currentTC && !isTCHeader && parts.length >= 8) {
        const stepNo = parts[5] || '';
        const stepDesc = parts[6] || '';
        const expected = parts[7] || '';
        if (stepNo || stepDesc || expected) {
          currentTC.steps.push({ stepNo, stepDesc, expected });
        }
      }
    }
  }
  return tcs;
}

const backendUAT = parseUatFile(uatPath);
const frontendUAT = parseUatFile(frontendUatPath);

console.log(`Backend UAT contains ${backendUAT.length} test cases.`);
console.log(`Frontend UAT contains ${frontendUAT.length} test cases.`);

// Write a list of all names to a file to verify
fs.writeFileSync('uat_parsed.json', JSON.stringify({ backendUAT, frontendUAT }, null, 2));
console.log('Saved to uat_parsed.json');
