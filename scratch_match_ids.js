const fs = require('fs');
const path = require('path');

function getFiles(dir, ext) {
  let results = [];
  if (!fs.existsSync(dir)) return results;
  const list = fs.readdirSync(dir);
  list.forEach(file => {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);
    if (stat && stat.isDirectory()) {
      if (file !== 'node_modules' && file !== '.git' && file !== '__pycache__' && file !== '.venv') {
        results = results.concat(getFiles(filePath, ext));
      }
    } else if (ext.some(e => file.endsWith(e))) {
      results.push(filePath);
    }
  });
  return results;
}

const backendDir = 'c:/Users/admin/OneDrive/Documents/GitHub/task-buddy-backend';
const frontendDir = 'c:/Users/admin/OneDrive/Documents/GitHub/task-buddy-frontend';

const backendTestFiles = getFiles(path.join(backendDir, 'tests'), ['.py']);
const frontendTestFiles = getFiles(path.join(frontendDir, 'tests'), ['.ts', '.tsx']).concat(getFiles(path.join(frontendDir, 'quality'), ['.ts', '.tsx']));

console.log(`Backend files: ${backendTestFiles.length}`);
console.log(`Frontend files: ${frontendTestFiles.length}`);

// We'll search for 'TC\d+' pattern in all test files
const tcMatches = [];

backendTestFiles.forEach(file => {
  const content = fs.readFileSync(file, 'utf8');
  const relPath = path.relative(backendDir, file);
  const matches = content.match(/TC\d+_[A-Za-z0-9_]+/g) || [];
  const simpleMatches = content.match(/TC\d+/g) || [];
  if (matches.length > 0 || simpleMatches.length > 0) {
    tcMatches.push({
      file: relPath,
      repo: 'backend',
      matches: [...new Set(matches)],
      simple: [...new Set(simpleMatches)]
    });
  }
});

frontendTestFiles.forEach(file => {
  const content = fs.readFileSync(file, 'utf8');
  const relPath = path.relative(frontendDir, file);
  const matches = content.match(/TC\d+_[A-Za-z0-9_]+/g) || [];
  const simpleMatches = content.match(/TC\d+/g) || [];
  if (matches.length > 0 || simpleMatches.length > 0) {
    tcMatches.push({
      file: relPath,
      repo: 'frontend',
      matches: [...new Set(matches)],
      simple: [...new Set(simpleMatches)]
    });
  }
});

console.log('--- Matches found ---');
console.log(JSON.stringify(tcMatches, null, 2));
