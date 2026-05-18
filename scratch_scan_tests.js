const fs = require('fs');
const path = require('path');

function getPyFiles(dir) {
  let results = [];
  const list = fs.readdirSync(dir);
  list.forEach(file => {
    const filePath = path.join(dir, file);
    const stat = fs.statSync(filePath);
    if (stat && stat.isDirectory()) {
      if (file !== '__pycache__') {
        results = results.concat(getPyFiles(filePath));
      }
    } else if (file.endsWith('.py')) {
      results.push(filePath);
    }
  });
  return results;
}

const testsDir = 'c:/Users/admin/OneDrive/Documents/GitHub/task-buddy-backend/tests';
const pyFiles = getPyFiles(testsDir);
console.log(`Found ${pyFiles.length} python test files.`);

const testFunctions = [];
pyFiles.forEach(file => {
  const content = fs.readFileSync(file, 'utf8');
  const relPath = path.relative('c:/Users/admin/OneDrive/Documents/GitHub/task-buddy-backend', file);
  
  const lines = content.split('\n');
  lines.forEach((line, idx) => {
    // support async def or def
    const match = line.match(/^\s*(async\s+)?def\s+(test_[a-zA-Z0-9_]+)\s*\(/);
    if (match) {
      testFunctions.push({
        file: relPath,
        func: match[2],
        line: idx + 1
      });
    }
  });
});

console.log(`Total test functions found: ${testFunctions.length}`);
console.log('Sample test functions:');
testFunctions.slice(0, 40).forEach(tf => {
  console.log(`- [${tf.file}:${tf.line}] ${tf.func}`);
});

// Let's save the list of test functions for later matching
fs.writeFileSync('c:/Users/admin/OneDrive/Documents/GitHub/task-buddy-backend/scratch_test_funcs.json', JSON.stringify(testFunctions, null, 2));
