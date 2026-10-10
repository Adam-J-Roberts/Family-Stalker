'use strict';
let csrf = '';
const view = document.getElementById('view');
const message = document.getElementById('message');
const logout = document.getElementById('logout');
function notice(text) { message.textContent = text; }
function escapeHTML(text) { const el = document.createElement('span'); el.textContent = text || ''; return el.innerHTML; }
async function api(path, method = 'GET', body, extraHeaders = {}) {
  const headers = {...extraHeaders};
  if (method !== 'GET') headers['X-CSRF-Token'] = csrf;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : 'Please check the fields and try again.'); error.fields = data.fields || []; throw error; }
  return data;
}
function bind(id, task) {
  document.getElementById(id).addEventListener('submit', async event => {
    event.preventDefault(); notice('');
    const form = event.currentTarget;
    form.querySelectorAll('.field-error').forEach(el => el.remove());
    form.querySelectorAll('[aria-invalid]').forEach(el => { el.removeAttribute('aria-invalid'); el.removeAttribute('aria-describedby'); });
    const button = form.querySelector('button[type="submit"]');
    if (button) button.disabled = true;
    try { await task(Object.fromEntries(new FormData(form)), form); }
    catch (error) {
      let first;
      for (const issue of error.fields || []) {
        const input = form.elements.namedItem(issue.field);
        if (!input || !input.tagName) continue;
        const hint = document.createElement('p'); hint.className = 'field-error';
        hint.id = `${form.id}-${input.name}-error`; hint.textContent = issue.message;
        input.setAttribute('aria-invalid', 'true'); input.setAttribute('aria-describedby', hint.id);
        (input.closest('.secret-control') || input).after(hint); first ||= input;
      }
      notice(error.message); first?.focus();
    }
    finally { if (button) button.disabled = false; }
  });
}
function field(name, label, type = 'text', extra = '') {
  const input = `<input id="${name}" name="${name}" type="${type}" ${extra}>`;
  return `<label for="${name}">${label}</label>` + (type === 'password' ? `<div class="secret-control">${input}<button type="button" class="secondary secret-toggle" aria-label="Show ${label}" aria-pressed="false">Show</button></div>` : input);
}
function setup() {
  view.innerHTML = `<section class="card"><p class="eyebrow">01 / CREATE YOUR HOUSEHOLD</p><h2>Make this server yours.</h2><p class="subtle">Enter the setup token from your Docker configuration, or retrieve the generated token using the command below.</p><code>docker compose exec stalker python manage.py bootstrap-token</code><form id="setup">${field('token','Setup token','password','required minlength="8" maxlength="256" autocomplete="off"')}${field('household','Household name','text','required maxlength="80"')}${field('email','Administrator email','email','required autocomplete="email"')}${field('username','Username','text','required pattern="[a-zA-Z0-9_.-]{3,64}" autocomplete="username"')}${field('password','Administrator password · at least 15 characters','password','required minlength="15" maxlength="128" autocomplete="new-password"')}<button type="submit">Create household</button></form></section>`;
  bind('setup', async (data, form) => { await api('/api/setup', 'POST', data); form.reset(); await login(); notice('Household created. Sign in to finish email setup.'); });
}
async function login() {
  window.FamilyClient?.lock(); document.getElementById("app-nav").hidden = true;
  logout.hidden = true;
  view.innerHTML = `<section class="card"><h2>Welcome home.</h2><p class="subtle">Sign in to manage your server.</p><form id="login">${field('email','Email','email','required autocomplete="username"')}${field('password','Password','password','required autocomplete="current-password"')}<button type="submit">Sign in</button></form></section><section class="card"><h3>Already invited?</h3><p class="subtle">You don't need the original invitation. Enter your invited email to request a fresh confirmation.</p><form id="request">${field('invite_email','Invited email','email','required')}<button class="secondary" type="submit">Send confirmation email</button></form></section>`;
  bind('login', async data => { const result = await api('/api/login','POST',data); csrf = result.csrf; await load(); });
  bind('request', async data => { const result = await api('/api/enrollment/request','POST',{email:data.invite_email}); notice(result.message); });
}
async function verification(token) {
  history.replaceState(null, '', '/');
  view.innerHTML = `<section class="card"><h2>Confirm your email.</h2><p class="subtle">New members: choose your username and password. Existing administrator: leave these blank to confirm your email without changing your password.</p><form id="verify">${field('username','Username (new members only)','text','pattern="[a-zA-Z0-9_.-]{3,64}" autocomplete="username"')}${field('password','Password (new members only)','password','minlength="15" maxlength="128" autocomplete="new-password"')}<button type="submit">Confirm email</button></form></section>`;
  bind('verify', async data => { await api('/api/enrollment/verify','POST',{token,username:data.username || null,password:data.password || null}); token = ''; await login(); notice('Email confirmed. Open Household map to enroll your device; trusted-device approval is a separate step.'); });
}
async function dashboard(user) {
  if (user.role !== 'admin') {
    view.innerHTML = `<section class="card"><h2>Your account is ready.</h2><p class="subtle">Signed in as ${escapeHTML(user.username)}. Open the household map to enroll and approve this browser. Email verification does not approve its encryption keys.</p></section>`;
    return;
  }
  const [status, mail, accounts, devices] = await Promise.all([api('/api/admin'),api('/api/mail'),api('/api/accounts'),api('/api/devices')]);
  view.innerHTML = `<section class="card"><p class="eyebrow">YOUR SERVER</p><h2>${escapeHTML(status.household)}</h2><p><code>${escapeHTML(status.public_url)}</code></p><span class="pill ok">Database connected</span><span class="pill ${status.mail_tested?'ok':'warn'}">${status.mail_tested?'Email tested':'Email setup needed'}</span><span class="pill warn">Encrypted device pairing</span><p class="subtle">${status.pending_mail} emails pending delivery. Your settings survive container updates.</p>${!user.verified?'<button id="confirm-owner" class="secondary">Confirm administrator email</button>':''}</section>
  <div class="grid"><section class="card"><p class="eyebrow">02 / EMAIL</p><h2>Connect your mail server.</h2><p class="subtle">Use your provider's SMTP settings and an app password where required. Only encrypted SMTP connections are supported.</p><form id="mail">${field('host','SMTP hostname','text','required')}${field('port','Port','number','required min="1" max="65535" value="587"')}<label for="mode">Encryption</label><select id="mode" name="mode"><option value="starttls">STARTTLS (usually 587)</option><option value="tls">TLS (usually 465)</option></select>${field('username','SMTP username')}${field('password','SMTP password · blank keeps saved password','password','autocomplete="new-password"')}${field('sender','Sender email','email','required')}<button type="submit">Save email settings</button></form><div class="links"><button id="test-mail" class="secondary">Send test to me</button><button id="retry-mail" class="secondary">Retry queued mail</button></div></section>
  <section class="card"><p class="eyebrow">03 / MEMBERS</p><h2>Invite your household.</h2><form id="invite">${field('email','Member email','email','required')}<button type="submit">Send invitation</button></form><div id="members"></div><h3>Devices</h3><p class="subtle">${devices.devices.length} registered. Open Household map to compare device fingerprints and approve trusted devices.</p></section></div>`;
  if (mail.configured) for (const key of ['host','port','mode','username','sender']) document.querySelector(`#mail [name="${key}"]`).value = mail[key];
  const members = document.getElementById('members');
  accounts.forEach(account => {
    const row = document.createElement('div'); row.className = 'member';
    const info = document.createElement('div'); info.textContent = account.email;
    const status = document.createElement('small'); status.textContent = `${account.status} · ${account.role}${account.verified?' · email confirmed':''}`; info.append(status); row.append(info);
    if (account.role !== 'admin' && account.status !== 'revoked') {
      const button = document.createElement('button'); button.className = 'danger'; button.textContent = 'Revoke';
      button.onclick = async () => { if (!confirm(`Revoke ${account.email}?`)) return; try { await api(`/api/accounts/${account.id}/revoke`,'POST',{}); await load(); notice('Member revoked. Open Household map to apply account revocations to encryption membership before publishing.'); } catch(e) {notice(e.message);} }; row.append(button);
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
  await operationalSettings();
  if(!user.verified) document.getElementById('confirm-owner').onclick=async()=>{try{const result=await api('/api/enrollment/request','POST',{email:user.email});notice(result.message);}catch(e){notice(e.message);}};
}
async function operationalSettings() {
  const [storage, push, audit] = await Promise.all([api('/api/storage'),api('/api/push/config'),api('/api/audit')]);
  const section=document.createElement('section');section.className='card';
  section.innerHTML=`<h3>Storage and retention</h3><p id="storage-summary"></p><p class="subtle">Locations and events expire by capture time. Saved places/profiles persist until replaced or deleted. Existing backups need their own expiration policy.</p><form id="retention"><label for="days">History retention (days, maximum 14)</label><input id="days" name="days" type="number" min="1" max="14" required><button type="submit">Save retention</button></form><button id="cleanup-storage" class="secondary">Clean expired data now</button><h3>Optional native push delivery</h3><p id="push-summary"></p><p class="subtle">Apple/Google receive a generic update and opaque record ID, never coordinates or place names. Native apps register their provider tokens separately.</p><form id="push-form"><label for="apns-team">Apple team ID</label><input id="apns-team" name="team"><label for="apns-key">Apple key ID</label><input id="apns-key" name="key"><label for="apns-topic">iOS bundle ID</label><input id="apns-topic" name="topic"><label for="apns-environment">APNs environment</label><select id="apns-environment" name="environment"><option value="sandbox">Sandbox</option><option value="production">Production</option></select><label for="apns-private">Apple .p8 private key (paste to replace configuration)</label><textarea id="apns-private" name="private_key" autocomplete="off"></textarea><label for="fcm-account">FCM service-account JSON (paste to replace configuration)</label><textarea id="fcm-account" name="fcm" autocomplete="off"></textarea><p class="subtle">Saving replaces both provider configurations. Blank provider fields disable that provider.</p><button type="submit">Save push configuration</button></form><button id="test-push" class="secondary">Test push to my native devices</button><h3>Recent security activity</h3><div id="audit-list"></div>`;
  view.append(section);
  section.querySelector('#storage-summary').textContent=`${storage.records} encrypted records · ${(storage.bytes/1048576).toFixed(2)} MiB of ${(storage.quota_bytes/1048576).toFixed(0)} MiB · ${storage.pending_push} push deliveries pending`;
  section.querySelector('#days').value=storage.retention_days;
  section.querySelector('#push-summary').textContent=`APNs: ${push.apns?'configured':'disabled'} · FCM: ${push.fcm_project||'disabled'}`;
  for(const event of audit){const row=document.createElement('p');row.textContent=`${new Date(event.created*1000).toLocaleString()} · ${event.action}`;section.querySelector('#audit-list').append(row);}
  bind('retention',async data=>{await api('/api/storage/retention','PUT',{days:Number(data.days)});await load();notice('Retention saved and expired data deleted.');});
  document.getElementById('cleanup-storage').onclick=async()=>{try{await api('/api/storage/cleanup','POST',{});await load();notice('Expired data cleaned.');}catch(e){notice(e.message);}};
  bind('push-form',async data=>{const apns=data.private_key?{team_id:data.team,key_id:data.key,topic:data.topic,sandbox:data.environment==='sandbox',private_key:data.private_key}:null;const fcm=data.fcm?JSON.parse(data.fcm):null;await api('/api/push/config','PUT',{apns,fcm});await load();notice('Push configuration saved.');});
  document.getElementById('test-push').onclick=async()=>{try{const r=await api('/api/push/test','POST',{});notice(`${r.sent} push tests sent to your registered native devices.`);}catch(e){notice(e.message);}};
}
async function load() {
  window.FamilyClient?.lock();
  const status=await api('/api/setup');
  if(!status.configured) return setup();
  let user;
  try {user=await api('/api/session');}catch(e){return login();}
  csrf=user.csrf; logout.hidden=false;
  document.getElementById('app-nav').hidden=false;
  document.getElementById('open-map').onclick=async()=>{try{await window.FamilyClient.mount({api,user,notice,view});}catch(e){notice(e.message);}};
  document.getElementById('open-settings').onclick=async()=>{window.FamilyClient?.lock();try{await dashboard(user);}catch(e){notice(e.message);}};
  await dashboard(user);
}
logout.onclick=async()=>{try{await api('/api/logout','POST',{});csrf='';notice('');await load();}catch(e){notice(e.message);}};
const token = new URLSearchParams(location.hash.slice(1)).get('verify');
(token?verification(token):load()).catch(error=>notice(error.message));

view.addEventListener('click', event => {
  const button = event.target.closest('.secret-toggle');
  if (!button) return;
  const input = button.parentElement.querySelector('input');
  const visible = input.type === 'password'; input.type = visible ? 'text' : 'password';
  button.textContent = visible ? 'Hide' : 'Show'; button.setAttribute('aria-pressed', String(visible));
  const label = input.labels?.[0]?.textContent || 'password';
  button.setAttribute('aria-label', `${visible ? 'Hide' : 'Show'} ${label}`);
});
