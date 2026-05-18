const fs = require('fs');
const path = require('path');

const schemasDir = 'c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\app\\schemas';
const files = fs.readdirSync(schemasDir).filter(f => f.endsWith('.py'));

console.log('--- SCHEMA VALIDATIONS ---');
files.forEach(file => {
  const content = fs.readFileSync(path.join(schemasDir, file), 'utf8');
  const lines = content.split('\n');
  lines.forEach((line, idx) => {
    if (line.includes('Field(') || line.includes('min_length') || line.includes('max_length') || line.includes('constr') || line.includes('EmailStr')) {
      console.log(`[${file}:${idx+1}]: ${line.trim()}`);
    }
  });
});
