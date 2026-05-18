const fs = require('fs');
const path = require('path');

const backendTestsDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\tests';
const frontendTestsDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-frontend\\tests';
const frontendQualityDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-frontend\\quality';

let output = '';

output += '--- SCANNING BACKEND TESTS (PYTHON) ---\n';
if (fs.existsSync(backendTestsDir)) {
  const files = fs.readdirSync(backendTestsDir).filter(f => f.startsWith('test_') && f.endsWith('.py'));
  files.forEach(file => {
    output += `\nFile: tests/${file}\n`;
    const content = fs.readFileSync(path.join(backendTestsDir, file), 'utf8');
    const matches = content.match(/def test_\w+/g);
    if (matches) {
      matches.forEach(m => {
        output += `  - ${m.replace('def ', '')}\n`;
      });
    } else {
      output += '  No test functions found\n';
    }
  });
}

output += '\n--- SCANNING FRONTEND E2E TESTS (PLAYWRIGHT) ---\n';
if (fs.existsSync(frontendTestsDir)) {
  const files = fs.readdirSync(frontendTestsDir).filter(f => f.endsWith('.spec.ts'));
  files.forEach(file => {
    output += `\nFile: tests/${file}\n`;
    const content = fs.readFileSync(path.join(frontendTestsDir, file), 'utf8');
    const testRegex = /test\((['"`])(.*?)\1/g;
    let match;
    const testNames = [];
    while ((match = testRegex.exec(content)) !== null) {
      testNames.push(match[2]);
    }
    testNames.forEach(t => {
      output += `  - test: ${t}\n`;
    });
  });
}

output += '\n--- SCANNING FRONTEND FUNCTIONAL TESTS (VITEST) ---\n';
if (fs.existsSync(frontendQualityDir)) {
  const files = fs.readdirSync(frontendQualityDir).filter(f => f.includes('test'));
  files.forEach(file => {
    output += `\nFile: quality/${file}\n`;
    const content = fs.readFileSync(path.join(frontendQualityDir, file), 'utf8');
    const testRegex = /(test|it)\((['"`])(.*?)\2/g;
    let match;
    const testNames = [];
    while ((match = testRegex.exec(content)) !== null) {
      testNames.push(match[3]);
    }
    testNames.forEach(t => {
      output += `  - test/it: ${t}\n`;
    });
  });
}

console.log(output);
fs.writeFileSync('scratch_test_output.txt', output, 'utf8');
