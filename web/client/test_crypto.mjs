import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import * as C from './crypto.mjs';
await C.ready;
const household=C.uuid(),account=C.uuid(),a=C.keys(account,household,'A'),b=C.keys(account,household,'B'),stranger=C.keys(C.uuid(),household,'Other');
const first={domain:'family-stalker.roster.v1',household,revision:1,previous:'',signer:a.id,devices:[C.identity(a)],issued_at:Math.floor(Date.now()/1000)};
const revision=body=>{const value={body,signature:C.sign(body,a.signing_secret)};return {...value,hash:C.hash(C.canonical(value))};};
const one=revision(first),two=revision({...first,revision:2,previous:one.hash,devices:[C.identity(a),C.identity(b)].sort((x,y)=>x.id.localeCompare(y.id))});
const chain=C.verifyChain([one,two],household,a.signing_key);
assert.equal(chain.revision,2);
assert.throws(()=>C.verifyChain([one,two],household,stranger.signing_key));
const changed=structuredClone(two);changed.body.devices[0].box_key=stranger.box_key;assert.throws(()=>C.verifyChain([one,changed],household,a.signing_key));
const substituted=revision({...two.body,devices:two.body.devices.map(d=>d.id===a.id?{...d,box_key:stranger.box_key}:d)});assert.throws(()=>C.verifyChain([one,substituted],household,a.signing_key));
a.sequence=0;
const message=C.encryptedRecord(a,chain.current,'location',account,{lat:12.3456789,lon:-23.4567891,accuracy:10});
assert.equal(C.decryptRecord(message,a,chain.rosters).data.lat,12.3456789);
assert.equal(C.decryptRecord(message,b,chain.rosters).data.lat,12.3456789);
assert.throws(()=>C.decryptRecord(message,stranger,chain.rosters));
const tampered=structuredClone(message);tampered.body.captured_at--;assert.throws(()=>C.decryptRecord(tampered,b,chain.rosters));
assert.ok(!JSON.stringify(message).includes('12.3456789'));
const salt=crypto.getRandomValues(new Uint8Array(16)),password='synthetic independent vault password';
const key=await C.vaultKey(password,salt),saved=await C.sealVault(a,key,salt,'synthetic-origin/account');
assert.ok(!JSON.stringify(saved).includes(a.signing_secret));
assert.equal((await C.openVault(saved,password,'synthetic-origin/account')).value.id,a.id);
await assert.rejects(C.openVault(saved,'incorrect synthetic password','synthetic-origin/account'));
await assert.rejects(C.openVault(saved,password,'other-origin/account'));
const python=spawnSync(process.env.STALKER_TEST_PYTHON||'python3',['-c',`import sys,json,base64
from nacl.signing import SigningKey,VerifyKey
from nacl.public import PrivateKey,PublicKey,SealedBox
v=json.load(sys.stdin);e=v['envelope'];enc=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode();b64=lambda x:base64.b64encode(x).decode()
VerifyKey(base64.b64decode(v['a']['signing_key'])).verify(enc(e['body']),base64.b64decode(e['signature']))
box=next(r['box'] for r in e['body']['recipients'] if r['device_id']==v['b']['id'])
payload=json.loads(SealedBox(PrivateKey(base64.b64decode(v['b']['box_secret']))).decrypt(base64.b64decode(box)))
assert payload['data']['lat']==12.3456789
body=e['body'];body['recipients']=[{'device_id':d['id'],'box':b64(SealedBox(PublicKey(base64.b64decode(d['box_key']))).encrypt(enc(payload)))} for d in sorted([v['a'],v['b']],key=lambda d:d['id'])]
print(json.dumps({'body':body,'signature':b64(SigningKey(base64.b64decode(v['a']['signing_secret'])[:32]).sign(enc(body)).signature)}))`],{input:JSON.stringify({envelope:message,a,b}),encoding:'utf8'});
assert.equal(python.status,0,python.stderr);
assert.equal(C.decryptRecord(JSON.parse(python.stdout),b,chain.rosters).data.lon,-23.4567891);
console.log('JS/Python crypto interoperability, separate recipients, signed membership, tamper rejection and encrypted vault checks passed.');
