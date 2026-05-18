const fs = require('fs');
const path = require('path');

const backendDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend';
const frontendDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-frontend';

function walk(dir) {
  let results = [];
  try {
    const list = fs.readdirSync(dir);
    for (const file of list) {
      if (file === 'node_modules' || file === '.git' || file === '.venv' || file === '__pycache__') continue;
      const fullPath = path.join(dir, file);
      const stat = fs.statSync(fullPath);
      if (stat && stat.isDirectory()) {
        results = results.concat(walk(fullPath));
      } else {
        results.push(fullPath);
      }
    }
  } catch (e) {
    console.error('Error in scratch_check_mapping try block:', e);
  }
  return results;
}

const allBackendFiles = walk(backendDir);
const allFrontendFiles = walk(frontendDir);

// Search for any mention of "TC0" or "TC1" or "TC\d+" in all files
console.log('Searching for TC references in backend files...');
allBackendFiles.forEach(file => {
  if (file.endsWith('.py') || file.endsWith('.md')) {
    const content = fs.readFileSync(file, 'utf8');
    const matches = content.match(/TC\d{3}/g);
    if (matches) {
      console.log(`- [${path.relative(backendDir, file)}]: found ${[...new Set(matches)].join(', ')}`);
    }
  }
});

console.log('\nSearching for TC references in frontend files...');
allFrontendFiles.forEach(file => {
  if (file.endsWith('.ts') || file.endsWith('.tsx') || file.endsWith('.md')) {
    const content = fs.readFileSync(file, 'utf8');
    const matches = content.match(/TC\d{3}/g);
    if (matches) {
      console.log(`- [${path.relative(frontendDir, file)}]: found ${[...new Set(matches)].join(', ')}`);
    }
  }
});
