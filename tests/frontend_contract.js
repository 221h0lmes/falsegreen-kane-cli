// Executes the application's unmodified inline script with a small DOM and
// controlled fetch/timer boundaries. This is not a real-browser test.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const script = fs.readFileSync(0, 'utf8');
const scenario = process.argv[2];
const id = 'a'.repeat(32), statusURL = '/api/bookings/' + id;
const booking = {id, customer:'KANE-OK-2026', date:'2026-12-05', time:'19:00', party_size:2};
const accepted = {id, status:'pending', status_url:statusURL};
const history = [], nodes = new Map(), calls = [];
let clock = 0;
class Node {
  constructor(tag = 'div', id = '') {
    this.tagName = tag; this.id = id; this.children = []; this.listeners = {};
    this.attributes = {}; this.hidden = false; this.disabled = false; this.value = '';
  }
  set textContent(value) { this.text = value; this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(n => n.textContent).join(''); }
  replaceChildren(...nodes) { this.text = ''; this.children = []; this.append(...nodes); }
  append(...nodes) {
    this.children.push(...nodes);
    if (this.id === 'result') history.push(this.textContent);
  }
  setAttribute(name, value) { this.attributes[name] = value; }
  removeAttribute(name) { delete this.attributes[name]; }
  addEventListener(event, handler) { this.listeners[event] = handler; }
}
const $ = id => {
  if (!nodes.has(id)) nodes.set(id, new Node('div', id));
  return nodes.get(id);
};
function response(status, data) {
  return {status, ok:status >= 200 && status < 300, json:async () => data};
}
function deferred() {
  let resolve;
  return {promise:new Promise(r => { resolve = r; }), resolve:value => resolve(value)};
}
const held = deferred();
let statusCalls = 0, recover = false;
async function fetch(url, options) {
  calls.push({url, options});
  assert.equal(options.cache, 'no-store');
  if (options.method === 'POST') {
    if (scenario === 'submission-network-error') throw new Error('Connection lost');
    if (scenario === 'submission-rejected') return response(400, {error:'Invalid date'});
    if (scenario === 'unexpected-acceptance') return response(200, {...booking, status:'confirmed'});
    return response(202, accepted);
  }
  if (url === '/api/bookings') return response(200, {bookings:scenario === 'success' ? [booking] : []});
  assert.equal(url, statusURL, 'Poll the accepted job, never submit it again');
  statusCalls++;
  if (scenario === 'success' || scenario === 'failure') {
    if (statusCalls === 1) return response(200, {...booking, status:'pending'});
    return held.promise;
  }
  if (scenario === 'transient-error') {
    if (statusCalls === 1) throw new Error('Temporarily offline');
    return response(200, {...booking, status:'confirmed'});
  }
  if (scenario === 'retry') {
    if (!recover) throw new Error('Offline');
    return response(200, {...booking, status:'failed', error:'Worker failed before saving.'});
  }
  if (scenario === 'timeout') return response(200, {...booking, status:'pending'});
  if (scenario === 'wrong-job') return response(200, {...booking, id:'b'.repeat(32), status:'confirmed'});
  if (scenario === 'missing-job') return response(404, {error:'Booking not found.'});
  throw new Error('Unexpected fetch');
}
class TestDate extends Date { static now() { return clock; } }
const context = vm.createContext({
  document:{getElementById:$, createElement:tag => new Node(tag)},
  location:{hash:'#book'}, window:{addEventListener() {}}, fetch,
  AbortSignal:{timeout:() => ({})}, Date:TestDate,
  setTimeout:(fn, delay) => { clock += delay; queueMicrotask(fn); },
});
vm.runInContext(script, context, {filename:'app-inline.js'});
$('customer').value = scenario === 'failure' ? 'KANE-FAIL-2026' : booking.customer;
$('date').value = booking.date; $('time').value = booking.time; $('party-size').value = '2';
const submit = () => $('booking-form').listeners.submit({preventDefault() {}});
const title = () => $('result').children[0].textContent;
const noConfirmation = () => assert.ok(history.every(text => !text.includes('Booking confirmed')), history.join('\n'));

(async () => {
  const done = submit();
  if (scenario === 'success' || scenario === 'failure') {
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(title(), 'Booking pending', '202 and nonterminal status must remain pending');
    assert.equal($('book-button').disabled, true);
    noConfirmation();
    await submit();
    assert.equal(calls.filter(c => c.options.method === 'POST').length, 1);
    held.resolve(response(200, {...booking,
      status:scenario === 'success' ? 'confirmed' : 'failed', error:'Worker failed before saving.'}));
  }
  await done;
  if (scenario === 'success' || scenario === 'transient-error') {
    assert.equal(title(), 'Booking confirmed');
    assert.equal($('book-button').disabled, false);
    assert.ok($('result').textContent.includes(booking.customer));
    vm.runInContext('loadBookings()', context);
    await new Promise(resolve => setImmediate(resolve));
    if (scenario === 'success') assert.ok($('bookings-content').textContent.includes(booking.customer));
  } else if (scenario === 'failure' || scenario === 'submission-rejected') {
    assert.equal(title(), 'Booking not confirmed');
    assert.equal($('book-button').disabled, false);
    noConfirmation();
  } else if (scenario.startsWith('submission-') || scenario === 'unexpected-acceptance') {
    assert.equal(title(), 'Booking status unavailable');
    noConfirmation();
  } else {
    assert.equal(title(), 'Booking pending');
    assert.equal($('book-button').disabled, true);
    assert.equal($('booking-form').attributes['aria-busy'], 'false');
    noConfirmation();
    const retry = $('result').children.find(node => node.tagName === 'button');
    assert.equal(retry.textContent, 'Check booking status');
    if (scenario === 'retry') {
      assert.equal(statusCalls, 3);
      recover = true;
      await retry.listeners.click();
      assert.equal(title(), 'Booking not confirmed');
      assert.equal($('book-button').disabled, false);
      noConfirmation();
    }
  }
  assert.equal(calls.filter(c => c.options.method === 'POST').length, 1);
  console.log('PASS ' + scenario);
})().catch(error => { console.error(error); process.exitCode = 1; });
