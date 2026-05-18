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
      if (file !== 'node_modules' && file !== '.git') {
        results = results.concat(getFiles(filePath, ext));
      }
    } else if (ext.some(e => file.endsWith(e))) {
      results.push(filePath);
    }
  });
  return results;
}

const frontendDir = 'c:/Users/admin/OneDrive/Documents/GitHub/task-buddy-frontend';
const testFiles = getFiles(frontendDir, ['.test.ts', '.test.tsx', '.spec.ts', '.spec.tsx']);
console.log(`Found ${testFiles.length} frontend test files.`);

testFiles.forEach(file => {
  const content = fs.readFileSync(file, 'utf8');
  const relPath = path.relative(frontendDir, file);
  
  // Look for describe or test or it
  const lines = content.split('\n');
  const tests = [];
  lines.forEach((line, idx) => {
    const match = line.match(/(describe|test|it)\s*\(\s*['"`](.*?)['"`]/);
    if (match) {
      tests.push({
        type: match[1],
        name: match[2],
        line: idx + 1
      });
    }
  });
  
  console.log(`- ${relPath}: ${tests.length} tests`);
  tests.slice(0, 10).forEach(t => {
    console.log(`  [Line ${t.line}] ${t.type}: "${t.name}"`);
  });
});
