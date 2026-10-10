// Synthetic setup/login checks. No email is sent and no production data is used.
const {chromium} = require('../../web/client/node_modules/playwright');
const {spawn,spawnSync} = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');

(async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'stalker-browser-'));
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  const server = spawn(process.env.STALKER_TEST_PYTHON || 'python3', ['-m','uvicorn','app:create_app','--factory','--host','127.0.0.1','--port',String(port),'--no-access-log','--no-proxy-headers'], {
    cwd: __dirname,
    env: {...process.env, DATABASE_URL:`sqlite:///${directory}/test.db`, STALKER_DATA_DIR:directory, STALKER_PUBLIC_URL:origin, STALKER_ALLOW_HTTP:'1'},
    stdio: ['ignore','ignore','ignore']
  });
  let browser;
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (server.exitCode !== null) throw new Error('Synthetic web server exited');
      try { ready = (await fetch(`${origin}/healthz`)).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(ready, 'Synthetic web server ready');
    browser = await chromium.launch();
    const page = await browser.newPage({viewport:{width:1100,height:950}});
    const errors=[];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(origin);
    await page.getByRole('heading', {name:'Make this server yours.'}).waitFor();
    await page.getByLabel('Setup token', {exact:true}).fill((await fs.readFile(path.join(directory,'bootstrap-token'),'utf8')).trim());
    await page.getByLabel('Household name', {exact:true}).fill('Synthetic Household');
    await page.getByLabel('Administrator email', {exact:true}).fill('owner@example.invalid');
    await page.getByLabel('Username', {exact:true}).fill('owner');
    await page.getByLabel('Administrator password · at least 15 characters', {exact:true}).fill('synthetic long test password');
    await page.getByRole('button', {name:'Create household',exact:true}).click();
    await page.getByRole('heading', {name:'Welcome home.'}).waitFor();
    await assert.rejects(fs.access(path.join(directory,'bootstrap-token')));
    await page.locator('#login [name=email]').fill('owner@example.invalid');
    await page.locator('#login [name=password]').fill('synthetic long test password');
    await page.getByRole('button', {name:'Sign in',exact:true}).click();
    await page.getByRole('heading', {name:'Synthetic Household',exact:true}).waitFor();
    const mail=page.locator('#mail');
    await mail.locator('[name=host]').fill('smtp.example.invalid');
    await mail.locator('[name=username]').fill('synthetic');
    await mail.locator('[name=password]').fill('synthetic-smtp-secret');
    await mail.locator('[name=sender]').fill('owner@example.invalid');
    await page.getByRole('button',{name:'Save email settings',exact:true}).click();
    await page.getByText('Email settings saved. Send a test next.',{exact:true}).waitFor();
    assert.equal(await mail.locator('[name=password]').inputValue(),'');
    await page.reload();
    await page.getByRole('heading', {name:'Synthetic Household',exact:true}).waitFor();
    assert.equal(await page.locator('#mail [name=host]').inputValue(),'smtp.example.invalid');
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth <= innerWidth), 'No horizontal overflow on phone');
    // Synthetic email confirmation fixture: no provider credentials or emails.
    const verify=spawnSync(process.env.STALKER_TEST_PYTHON || 'python3',['-c',"from sqlalchemy import create_engine,text; import os; e=create_engine(os.environ['DATABASE_URL']); c=e.connect(); c.execute(text('UPDATE accounts SET verified=true')); c.commit(); c.close()"],{cwd:__dirname,env:{...process.env,DATABASE_URL:`sqlite:///${directory}/test.db`},encoding:'utf8'});
    assert.equal(verify.status,0,verify.stderr);
    await page.reload();
    await page.getByRole('heading',{name:'Synthetic Household',exact:true}).waitFor();
    const recordRequests=[];
    page.on('request',request=>{if(request.url().endsWith('/api/records')&&request.method()==='POST')recordRequests.push(request.postData());});
    await page.getByRole('button',{name:'Household map',exact:true}).click();
    await page.getByRole('heading',{name:'Create a browser device.',exact:true}).waitFor();
    await page.getByLabel('Browser device name',{exact:true}).fill('Browser A');
    await page.getByLabel('Browser-vault passphrase',{exact:true}).fill('synthetic independent vault passphrase');
    await page.getByRole('button',{name:'Create encrypted device',exact:true}).click();
    await page.getByRole('heading',{name:'Approve your first device.',exact:true}).waitFor();
    await page.getByLabel('Device bootstrap token',{exact:true}).fill((await fs.readFile(path.join(directory,'device-bootstrap-token'),'utf8')).trim());
    await page.getByRole('button',{name:'Trust this first device',exact:true}).click();
    await page.getByRole('heading',{name:'Household map',exact:true}).waitFor();
    const rootFingerprint=await page.locator('#root-code').textContent();
    assert.equal(rootFingerprint.length,64);
    await page.getByLabel('Latitude',{exact:true}).fill('12.3456789');
    await page.getByLabel('Longitude',{exact:true}).fill('-23.4567891');
    await page.getByRole('button',{name:'Publish encrypted location',exact:true}).click();
    await page.getByText('Encrypted location published.',{exact:true}).waitFor();
    await page.getByLabel('Place name',{exact:true}).fill('Synthetic Private Home');
    await page.getByLabel('Place latitude',{exact:true}).fill('12.3456789');
    await page.getByLabel('Place longitude',{exact:true}).fill('-23.4567891');
    await page.getByRole('button',{name:'Save encrypted place',exact:true}).click();
    await page.getByText('Encrypted place saved.',{exact:true}).waitFor();
    const context2=await browser.newContext({viewport:{width:390,height:844}}),second=await context2.newPage();
    second.on('pageerror',error=>errors.push(error.message));
    const external=[];
    for(const p of [page,second])p.on('request',request=>{if(/^https?:/.test(request.url())&&!request.url().startsWith(origin))external.push(request.url());});
    await second.goto(origin);
    await second.locator('#login [name=email]').fill('owner@example.invalid');
    await second.locator('#login [name=password]').fill('synthetic long test password');
    await second.getByRole('button',{name:'Sign in',exact:true}).click();
    await second.getByRole('button',{name:'Household map',exact:true}).click();
    await second.getByLabel('Browser device name',{exact:true}).fill('Browser B');
    await second.getByLabel('Browser-vault passphrase',{exact:true}).fill('synthetic second vault passphrase');
    await second.getByRole('button',{name:'Create encrypted device',exact:true}).click();
    await second.getByRole('heading',{name:'Pair with a trusted device.',exact:true}).waitFor();
    const joiningFingerprint=await second.locator('#joining-fingerprint').textContent();
    await second.getByLabel('Owner household fingerprint',{exact:true}).fill(rootFingerprint);
    await second.getByRole('button',{name:'Verify household',exact:true}).click();
    await second.getByRole('heading',{name:'Waiting for trusted approval.',exact:true}).waitFor();
    await page.getByRole('button',{name:'Refresh updates',exact:true}).click();
    const joining=page.locator('.device-row').filter({hasText:'Browser B'});
    await joining.getByLabel('Fingerprint shown on the requesting device').fill(joiningFingerprint);
    await joining.getByRole('button',{name:'Approve trusted device',exact:true}).click();
    await page.getByText('Device approved. Reshare places and publish a new location for it.',{exact:true}).waitFor();
    await second.getByRole('button',{name:'Check approval',exact:true}).click();
    await second.getByRole('heading',{name:'Household map',exact:true}).waitFor();
    await page.getByRole('button',{name:'Publish encrypted location',exact:true}).click();
    await page.getByText('Encrypted location published.',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Share saved places with newly approved devices',exact:true}).click();
    await page.getByText('Places encrypted for the current membership.',{exact:true}).waitFor();
    const png=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=c.height=2;c.getContext('2d').fillRect(0,0,2,2);return c.toDataURL('image/png').split(',')[1];});
    await page.getByLabel('Display name',{exact:true}).fill('Synthetic Private Owner');
    await page.getByLabel('Map photo (optional)',{exact:true}).setInputFiles({name:'synthetic-photo.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
    await page.getByRole('button',{name:'Save encrypted profile',exact:true}).click();
    await page.getByText('Encrypted profile saved.',{exact:true}).waitFor();
    // More than one state page: exercise the browser cursor, not just the API.
    for(let number=0;number<9;number++){
      await page.getByLabel('Place name',{exact:true}).fill(`Synthetic Additional Place ${number}`);
      await page.getByRole('button',{name:'Save encrypted place',exact:true}).click();
      await page.getByText('Encrypted place saved.',{exact:true}).waitFor();
    }
    await second.getByRole('button',{name:'Refresh updates',exact:true}).click();
    await second.locator('#location-list').getByText(/12.3456789/).waitFor();
    await second.locator('#place-list').getByText('Synthetic Private Home · 100 m',{exact:true}).waitFor();
    assert.equal(await second.locator('#place-list .member').count(),10,'All paginated places displayed');
    assert.equal(await second.locator('.map-person img').count(),1,'Encrypted photo displayed on recipient marker');
    await second.locator('#location-list').getByText(/Synthetic Private Owner/).waitFor();
    assert.ok(await second.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'Phone map layout fits');
    await page.locator('#place-list .member').filter({hasText:'Synthetic Private Home'}).getByRole('button',{name:'Test arrival',exact:true}).click();
    await page.getByText('Encrypted test event published.',{exact:true}).waitFor();
    await second.getByRole('button',{name:'Load household events',exact:true}).click();
    await second.locator('#history-list').getByText(/Synthetic Private Home/).waitFor();
    assert.ok(recordRequests.length>=5);
    for(const raw of recordRequests){assert.ok(!raw.includes('12.3456789'));assert.ok(!raw.includes('Synthetic Private Home'));assert.ok(!raw.includes('Synthetic Private Owner'));const value=JSON.parse(raw);assert.equal(value.body.domain,'family-stalker.record.v1');assert.ok(value.signature);}
    const savedVault=await second.evaluate(()=>Object.values(localStorage).find(value=>value.includes('"version":1')));
    assert.ok(savedVault&&!savedVault.includes('signing_secret')&&!savedVault.includes('credential'));
    assert.deepEqual(external,[],'No map-provider requests before consent');
    await second.getByRole('button',{name:'Lock map',exact:true}).click();
    await second.getByRole('heading',{name:'Unlock this browser.',exact:true}).waitFor();
    await second.getByLabel('Browser-vault passphrase',{exact:true}).fill('incorrect passphrase');
    await second.getByRole('button',{name:'Unlock map',exact:true}).click();
    await second.getByText('Could not unlock: check your browser-vault passphrase.',{exact:true}).waitFor();
    await second.getByLabel('Browser-vault passphrase',{exact:true}).fill('synthetic second vault passphrase');
    await second.getByRole('button',{name:'Unlock map',exact:true}).click();
    await second.getByRole('heading',{name:'Household map',exact:true}).waitFor();
    await page.locator('.device-row').filter({hasText:'Browser B'}).getByRole('button',{name:'Revoke device',exact:true}).click();
    await page.getByText('Device revoked; future encryption uses updated membership.',{exact:true}).waitFor();
    await second.getByRole('button',{name:'Refresh updates',exact:true}).click();
    await second.getByText('Device credential not accepted',{exact:true}).waitFor();
    await page.getByRole('button',{name:'Lock map',exact:true}).click();
    await page.getByRole('heading',{name:'Unlock this browser.',exact:true}).waitFor();
    await context2.close();
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    await page.getByRole('heading', {name:'Welcome home.'}).waitFor();
    assert.deepEqual(errors,[],'No browser errors');
    console.log('Browser setup, two-device pairing, encrypted map/places/events, vault locking, revocation and phone layout passed.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    if (server.exitCode === null) await new Promise(resolve => server.once('exit',resolve));
    await fs.rm(directory,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
