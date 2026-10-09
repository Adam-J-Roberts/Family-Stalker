// Synthetic setup/login checks. No email is sent and no production data is used.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
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
    await page.getByRole('button',{name:'Sign out',exact:true}).click();
    await page.getByRole('heading', {name:'Welcome home.'}).waitFor();
    assert.deepEqual(errors,[],'No browser errors');
    console.log('Browser setup, login, saved settings, phone layout and logout passed.');
  } finally {
    if (browser) await browser.close();
    server.kill('SIGTERM');
    if (server.exitCode === null) await new Promise(resolve => server.once('exit',resolve));
    await fs.rm(directory,{recursive:true,force:true});
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
