const fs = require('fs');

const masterSpecPath = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\docs\\MASTER_SPEC.md';
const uatCasesPath = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\quality\\UAT_TEST_CASES.md';

console.log('--- HEAD OF UAT_TEST_CASES.md ---');
const uatContent = fs.readFileSync(uatCasesPath, 'utf8');
console.log(uatContent.split('\n').slice(0, 50).join('\n'));

console.log('\n--- HEAD OF MASTER_SPEC.md (Test Section) ---');
const masterContent = fs.readFileSync(masterSpecPath, 'utf8');
const testSectionIndex = masterContent.indexOf('## 📋 System Test Cases');
if (testSectionIndex !== -1) {
  console.log(masterContent.substring(testSectionIndex, testSectionIndex + 1000));
} else {
  console.log('Test section not found in MASTER_SPEC.md');
}
