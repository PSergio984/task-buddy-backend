const fs = require('fs');
const path = require('path');

const funcs = JSON.parse(fs.readFileSync('c:\\Users\\admin\\OneDrive\\Documents\\GitHub\\task-buddy-backend\\scratch_test_funcs.json', 'utf8'));

console.log('--- BACKEND PYTEST FUNCTIONS (First 60) ---');
funcs.slice(0, 60).forEach((tf, i) => {
  console.log(`${i+1}. [${tf.file}] ${tf.func}`);
});

console.log('--- BACKEND PYTEST FUNCTIONS (Remaining) ---');
funcs.slice(60).forEach((tf, i) => {
  console.log(`${i+61}. [${tf.file}] ${tf.func}`);
});
