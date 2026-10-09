'use strict';
let csrf = '';
const view = document.getElementById('view');
const message = document.getElementById('message');
const logout = document.getElementById('logout');
function notice(text) { message.textContent = text; }
function escapeHTML(text) { const el = document.createElement('span'); el.textContent = text || ''; return el.innerHTML; }
async function api(path, method = 'GET', body) {
  const headers = {};
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the fields and try again.');
  return data;
}
function bind(id, task) {
  document.getElementById(id).addEventListener('submit', async event => {
    event.preventDefault(); notice('');
    const form = event.currentTarget, button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try { await task(Object.fromEntries(new FormData(form)), form); }
    catch (error) { notice(error.message); }
    finally { if (button) button.disabled = false; }
  });
}
function field(name, label, type = 'text', extra = '') {
  return `<label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" ${extra}>`;
}
function setup() {
  view.innerHTML = `<section class="card"><p class="eyebrow">01 / CREATE YOUR HOUSEHOLD</p><h2>Make this server yours.</h2><p class="subtle">Retrieve the one-time setup token from Docker. It prevents someone else claiming your server.</p><code>docker compose exec stalker python manage.py bootstrap-token</code><form id="setup">${field('token','Setup token','password','required autocomplete="off"')}${field('household','Household name','text','required maxlength="80"')}${field('email','Administrator email','email','required autocomplete="email"')}${field('username','Username','text','required pattern="[a-zA-Z0-9_.-]{3,64}" autocomplete="username"')}${field('password','Administrator password · at least 15 characters','password','required minlength="15" maxlength="128" autocomplete="new-password"')}<button type="submit">Create household</button></form></section>`;
  bind('setup', async (data, form) => { await api('/api/setup', 'POST', data); form.reset(); await login(); notice('Household created. Sign in to finish email setup.'); });
}
async function login() {
  logout.hidden = true;
  view.innerHTML = `<section class="card"><h2>Welcome home.</h2><p class="subtle">Sign in to manage your server.</p><form id="login">${field('email','Email','email','required autocomplete="username"')}${field('password','Password','password','required autocomplete="current-password"')}<button type="submit">Sign in</button></form></section><section class="card"><h3>Already invited?</h3><p class="subtle">You don't need the original invitation. Enter your invited email to request a fresh confirmation.</p><form id="request">${field('invite_email','Invited email','email','required')}<button class="secondary" type="submit">Send confirmation email</button></form></section>`;
  bind('login', async data => { const result = await api('/api/login','POST',data); csrf = result.csrf; await load(); });
  bind('request', async data => { const result = await api('/api/enrollment/request','POST',{email:data.invite_email}); notice(result.message); });
}
async function verification(token) {
  history.replaceState(null, '', '/');
  view.innerHTML = `<section class="card"><h2>Confirm your email.</h2><p class="subtle">New members: choose your username and password. Existing administrator: leave these blank to confirm your email without changing your password.</p><form id="verify">${field('username','Username (new members only)','text','pattern="[a-zA-Z0-9_.-]{3,64}" autocomplete="username"')}${field('password','Password (new members only)','password','minlength="15" maxlength="128" autocomplete="new-password"')}<button type="submit">Confirm email</button></form></section>`;
  bind('verify', async data => { await api('/api/enrollment/verify','POST',{token,username:data.username || null,password:data.password || null}); token = ''; await login(); notice('Email confirmed. Secure device approval is a separate step and is not available yet.'); });
}
async function dashboard(user) {
  if (user.role !== 'admin') {
    view.innerHTML = `<section class="card"><h2>Your account is ready.</h2><p class="subtle">Signed in as ${escapeHTML(user.username)}. Device pairing and location sharing are coming next. No device has been approved by email verification.</p></section>`;
    return;
  }
  const [status, mail, accounts, devices] = await Promise.all([api('/api/admin'),api('/api/mail'),api('/api/accounts'),api('/api/devices')]);
  view.innerHTML = `<section class="card"><p class="eyebrow">YOUR SERVER</p><h2>${escapeHTML(status.household)}</h2><p><code>${escapeHTML(status.public_url)}</code></p><span class="pill ok">Database connected</span><span class="pill ${status.mail_tested?'ok':'warn'}">${status.mail_tested?'Email tested':'Email setup needed'}</span><span class="pill warn">Device pairing not available</span><p class="subtle">${status.pending_mail} emails pending delivery. Your settings survive container updates.</p>${!user.verified?'<button id="confirm-owner" class="secondary">Confirm administrator email</button>':''}</section>
  <div class="grid"><section class="card"><p class="eyebrow">02 / EMAIL</p><h2>Connect your mail server.</h2><p class="subtle">Use your provider's SMTP settings and an app password where required. Only encrypted SMTP connections are supported.</p><form id="mail">${field('host','SMTP hostname','text','required')}${field('port','Port','number','required min="1" max="65535" value="587"')}<label for="mode">Encryption</label><select id="mode" name="mode"><option value="starttls">STARTTLS (usually 587)</option><option value="tls">TLS (usually 465)</option></select>${field('username','SMTP username')}${field('password','SMTP password · blank keeps saved password','password','autocomplete="new-password"')}${field('sender','Sender email','email','required')}<button type="submit">Save email settings</button></form><div class="links"><button id="test-mail" class="secondary">Send test to me</button><button id="retry-mail" class="secondary">Retry queued mail</button></div></section>
  <section class="card"><p class="eyebrow">03 / MEMBERS</p><h2>Invite your household.</h2><form id="invite">${field('email','Member email','email','required')}<button type="submit">Send invitation</button></form><div id="members"></div><h3>Devices</h3><p class="subtle">${devices.devices.length} registered. Cryptographic registration and approval are gated until pairing is implemented.</p></section></div>`;
  if (mail.configured) for (const key of ['host','port','mode','username','sender']) document.querySelector(`#mail [name="${key}"]`).value = mail[key];
  const members = document.getElementById('members');
  accounts.forEach(account => {
    const row = document.createElement('div'); row.className = 'member';
    const info = document.createElement('div'); info.textContent = account.email;
    const status = document.createElement('small'); status.textContent = `${account.status} · ${account.role}${account.verified?' · email confirmed':''}`; info.append(status); row.append(info);
    if (account.role !== 'admin' && account.status !== 'revoked') {
      const button = document.createElement('button'); button.className = 'danger'; button.textContent = 'Revoke';
      button.onclick = async () => { if (!confirm(`Revoke ${account.email}?`)) return; try { await api(`/api/accounts/${account.id}/revoke`,'POST',{}); await load(); } catch(e) {notice(e.message);} }; row.append(button);
    }
    if (account.status === 'pending') {
      const button = document.createElement('button'); button.className='secondary'; button.textContent='Resend';
      button.onclick=async()=>{try {const result=await api('/api/enrollment/request','POST',{email:account.email});notice(result.message);}catch(e){notice(e.message);}}; row.append(button);
    }
    members.append(row);
  });
  bind('mail', async data => { data.port=Number(data.port); data.password=data.password || null; await api('/api/mail','PUT',data); await load(); notice('Email settings saved. Send a test next.'); });
  bind('invite', async data => {const result=await api('/api/invitations','POST',data); await load(); notice(result.delivery === 'pending'?'Account created; email is queued. Check mail settings and retry.':'Invitation sent.');});
  document.getElementById('test-mail').onclick=async()=>{try{await api('/api/mail/test','POST',{});await load();notice('Test email sent. Check your inbox.');}catch(e){notice(e.message);}};
  document.getElementById('retry-mail').onclick=async()=>{try{const result=await api('/api/mail/retry','POST',{});await load();notice(`${result.sent} emails sent; delivery ${result.delivery}.`);}catch(e){notice(e.message);}};
  if(!user.verified) document.getElementById('confirm-owner').onclick=async()=>{try{const result=await api('/api/enrollment/request','POST',{email:user.email});notice(result.message);}catch(e){notice(e.message);}};
}
async function load() {
  const status=await api('/api/setup');
  if(!status.configured) return setup();
  let user;
  try {user=await api('/api/session');}catch(e){return login();}
  csrf=user.csrf; logout.hidden=false; await dashboard(user);
}
logout.onclick=async()=>{try{await api('/api/logout','POST',{});csrf='';notice('');await load();}catch(e){notice(e.message);}};
const token = new URLSearchParams(location.hash.slice(1)).get('verify');
(token?verification(token):load()).catch(error=>notice(error.message));
