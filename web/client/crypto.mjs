import sodium from 'libsodium-wrappers-sumo';
export const ready = sodium.ready;
export const canonical = value => JSON.stringify(sort(value));
function sort(value) {
  if (Array.isArray(value)) return value.map(sort);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key=>[key,sort(value[key])]));
  return value;
}
export const b64 = value => sodium.to_base64(value,sodium.base64_variants.ORIGINAL);
export const unb64 = value => sodium.from_base64(value,sodium.base64_variants.ORIGINAL);
export const hex = value => sodium.to_hex(value);
export const hash = value => hex(sodium.crypto_hash_sha256(typeof value==='string'?sodium.from_string(value):value));
export const uuid = () => hex(sodium.randombytes_buf(16));
export const sign = (body,key) => b64(sodium.crypto_sign_detached(canonical(body),unb64(key)));
export const verify = (body,signature,key) => sodium.crypto_sign_verify_detached(unb64(signature),canonical(body),unb64(key));
export const identity = vault => ({id:vault.id,account_id:vault.account_id,signing_key:vault.signing_key,box_key:vault.box_key});
export function keys(account,household,name) {
  const signing = sodium.crypto_sign_keypair(), box = sodium.crypto_box_keypair();
  return {id:uuid(),account_id:account,household,name,signing_key:b64(signing.publicKey),signing_secret:b64(signing.privateKey),box_key:b64(box.publicKey),box_secret:b64(box.privateKey),revision:0,chain_hash:'',anchor:null,sequence:0};
}
export function encryptedRecord(vault,roster,kind,entity,data,operation='upsert',replaces=null,capturedAt=Date.now()) {
  const body={domain:'family-stalker.record.v1',household:vault.household,revision:roster.revision,id:uuid(),sender:vault.id,sequence:vault.sequence+1,kind,entity_id:entity,operation,replaces,captured_at:capturedAt};
  const payload={domain:'family-stalker.payload.v1',...Object.fromEntries(Object.entries(body).filter(([key])=>key!=='domain')),data};
  body.recipients=roster.devices.map(device=>({device_id:device.id,box:b64(sodium.crypto_box_seal(canonical(payload),unb64(device.box_key)))})).sort((a,b)=>a.device_id.localeCompare(b.device_id));
  return {body,signature:sign(body,vault.signing_secret)};
}
export function decryptRecord(envelope,vault,rosters) {
  const body=envelope.body, roster=rosters.get(body.revision), sender=roster?.devices.find(d=>d.id===body.sender);
  if(body.domain!=='family-stalker.record.v1'||body.household!==vault.household||!sender||!verify(body,envelope.signature,sender.signing_key)) throw new Error('Encrypted record signature or household rejected.');
  const recipient=body.recipients.find(r=>r.device_id===vault.id);
  if(!recipient) throw new Error('This record predates approval of this device.');
  const payload=JSON.parse(sodium.to_string(sodium.crypto_box_seal_open(unb64(recipient.box),unb64(vault.box_key),unb64(vault.box_secret))));
  if(payload.domain!=='family-stalker.payload.v1') throw new Error('Payload format rejected.');
  for(const key of ['household','revision','id','sender','sequence','kind','entity_id','operation','replaces','captured_at']) if(payload[key]!==body[key]) throw new Error('Encrypted record context rejected.');
  return payload;
}
export function verifyChain(changes,household,anchor) {
  const rosters=new Map(); let previous='', revision=0, current;
  for(const change of changes) {
    const b=change.body;
    if(b.domain!=='family-stalker.roster.v1'||b.household!==household||b.revision!==revision+1||b.previous!==previous) throw new Error('Membership chain rejected.');
    const ids=b.devices.map(d=>d.id);
    if(new Set(ids).size!==ids.length||canonical([...ids].sort())!==canonical(ids)) throw new Error('Duplicate or unordered membership.');
    const signer=revision?current.devices.find(d=>d.id===b.signer):b.devices.find(d=>d.id===b.signer);
    if(!signer||(!revision&&(b.devices.length!==1||signer.signing_key!==anchor))||!verify(b,change.signature,signer.signing_key)) throw new Error('Untrusted membership signature.');
    if(revision) for(const old of current.devices) {
      const next=b.devices.find(d=>d.id===old.id);
      if(next&&canonical(next)!==canonical(old)) throw new Error('A device key was substituted.');
    }
    previous=hash(canonical({body:b,signature:change.signature}));
    if(change.hash!==previous) throw new Error('Membership digest rejected.');
    revision=b.revision;current=b;rosters.set(revision,b);
  }
  return {rosters,current,hash:previous,revision};
}
export async function vaultKey(password,salt,usage=['encrypt','decrypt']) {
  const base=await crypto.subtle.importKey('raw',new TextEncoder().encode(password),'PBKDF2',false,['deriveKey']);
  return crypto.subtle.deriveKey({name:'PBKDF2',hash:'SHA-256',salt,iterations:600000},base,{name:'AES-GCM',length:256},false,usage);
}
export async function sealVault(value,key,salt,context) {
  const iv=crypto.getRandomValues(new Uint8Array(12));
  const box=await crypto.subtle.encrypt({name:'AES-GCM',iv,additionalData:new TextEncoder().encode(context)},key,new TextEncoder().encode(JSON.stringify(value)));
  return {version:1,salt:b64(salt),iv:b64(iv),box:b64(new Uint8Array(box))};
}
export async function openVault(saved,password,context) {
  if(saved.version!==1) throw new Error('Unsupported browser vault.');
  const salt=unb64(saved.salt),key=await vaultKey(password,salt);
  try {
    const value=JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:unb64(saved.iv),additionalData:new TextEncoder().encode(context)},key,unb64(saved.box))));
    return {value,key,salt};
  } catch {throw new Error('Could not unlock: check your browser-vault passphrase.');}
}
export function wipe(vault) {
  if(vault) for(const key of ['signing_secret','box_secret','credential']) vault[key]='';
}
