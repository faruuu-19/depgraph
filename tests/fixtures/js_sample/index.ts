import { greet } from './lib/utils';
const api = require('./lib/api');

console.log(greet('world'));
console.log(api.fetch());
