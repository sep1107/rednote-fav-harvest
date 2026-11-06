const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/harvest.py`, 'utf8');
const initial = source.match(/INITIAL_NOTES = """([\s\S]*?)"""/)[1];
const scroll = JSON.parse(source.match(/^SCROLL = (.*)$/m)[1]);
const note = {id: 'example', xsecToken: 'test-token', noteCard: {
  type: 'video', displayTitle: 'Example', cover: {urlDefault: 'https://example.test/cover.jpg'}
}};
for (const notes of [[[], [note]], {_value: [[], [note]]}, {value: [[], [note]]}]) {
  const result = JSON.parse(vm.runInNewContext(initial, {window: {__INITIAL_STATE__: {user: {notes}}}}));
  assert.deepEqual(result, [{note_id: 'example', type: 'video', display_title: 'Example',
    xsec_token: 'test-token', cover: {url_default: 'https://example.test/cover.jpg'}}]);
}
assert.equal(vm.runInNewContext(initial, {window: {}}), '[]');
for (const mode of ['internal', 'document', 'missing']) {
  const calls = [];
  const inner = mode === 'missing' ? null : {scrollHeight: mode === 'internal' ? 900 : 600,
    clientHeight: 600, scrollBy: (x, y) => calls.push(['internal', y])};
  const document = {querySelector: () => inner, scrollingElement: {scrollBy: (x, y) => calls.push(['document', y])}};
  vm.runInNewContext(scroll, {document, getComputedStyle: () => ({overflowY: 'scroll'}), setTimeout: f => f()});
  const target = mode === 'internal' ? 'internal' : 'document';
  assert.deepEqual(calls, [[target, -300], [target, 900]]);
}
console.log('Passed 4 initial-page and 3 scrolling checks');
