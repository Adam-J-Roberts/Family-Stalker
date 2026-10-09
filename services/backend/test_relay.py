import base64
import copy
import json
import secrets
import time
import unittest
from unittest.mock import patch, MagicMock
from nacl.public import PrivateKey, SealedBox, PublicKey
from nacl.signing import SigningKey
from sqlalchemy import select
from sqlalchemy.orm import Session
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
import test_setup
from app import Account, HASHER, LoginSession, Settings, create_app, digest
from data_service import ClientDevice, EncryptedRecord, LatestState, PushDelivery, PushSubscription, RosterRevision, ServiceState, canonical

B64=lambda x:base64.b64encode(bytes(x)).decode()


class RelayTests(unittest.TestCase):
    tearDown=test_setup.SetupTests.tearDown
    setup_owner=test_setup.SetupTests.setup_owner
    login=test_setup.SetupTests.login
    configure=test_setup.SetupTests.configure

    def setUp(self):
        test_setup.SetupTests.setUp(self)
        self.configure()
        with Session(self.app.state.engine) as db:
            owner=db.scalar(select(Account).where(Account.email==test_setup.OWNER))
            owner.verified=True
            self.owner_id=owner.id
            self.household=db.get(ServiceState,1).household_id
            db.commit()
        self.devices=[]

    def register(self, client=None, account=None):
        signing,box=SigningKey.generate(),PrivateKey.generate()
        d=dict(id=secrets.token_hex(16),account_id=account or self.owner_id,signing_key=B64(signing.verify_key),box_key=B64(box.public_key),signing=signing,box=box)
        body=dict(domain='family-stalker.device.v1',household=self.household,**self.identity(d))
        response=(client or self.client).post('/api/devices/register',json=dict(id=d['id'],name='Synthetic device',signing_key=d['signing_key'],box_key=d['box_key'],signature=B64(signing.sign(canonical(body)).signature)))
        self.assertEqual(response.status_code,201,response.text)
        d['credential']=response.json()['credential'];self.devices.append(d);return d

    def identity(self,d):
        return {k:d[k] for k in ('id','account_id','signing_key','box_key')}

    def call(self,d,method,path,body=None):
        kwargs=dict(headers={'Authorization':f"Bearer {d['credential']}"})
        if body is not None:kwargs['json']=body
        return self.client.request(method,path,**kwargs)

    def roster(self,signer,devices,token=None):
        with Session(self.app.state.engine) as db:
            state=db.get(ServiceState,1);old=db.get(RosterRevision,state.revision)
            body=dict(domain='family-stalker.roster.v1',household=self.household,revision=state.revision+1,previous=old.hash if old else '',signer=signer['id'],devices=sorted([self.identity(d) for d in devices],key=lambda d:d['id']),issued_at=int(time.time()))
        return dict(body=body,signature=B64(signer['signing'].sign(canonical(body)).signature),bootstrap_token=token)

    def bootstrap(self):
        d=self.register();body=self.roster(d,[d],(self.path/'device-bootstrap-token').read_text())
        result=self.call(d,'POST','/api/roster',body);self.assertEqual(result.status_code,200,result.text);return d

    def pair(self):
        a=self.bootstrap();b=self.register();self.assertEqual(self.call(a,'POST','/api/roster',self.roster(a,[a,b])).status_code,200);return a,b

    def record(self,d,kind='location',data=None,captured=None,sequence=None,recipients=None,entity=None,operation='upsert',replaces='auto'):
        with Session(self.app.state.engine) as db:
            state=db.get(ServiceState,1);device=db.get(ClientDevice,d['id']);all_devices=list(db.scalars(select(ClientDevice).where(ClientDevice.status=='approved')))
            entity=entity or (d['account_id'] if kind in ('location','profile') else secrets.token_hex(16))
            latest=db.get(LatestState,(kind,entity))
            previous=latest.record_id if latest and kind in ('place','profile') else None
            body=dict(domain='family-stalker.record.v1',household=self.household,revision=state.revision,id=secrets.token_hex(16),sender=d['id'],sequence=sequence or device.last_sequence+1,kind=kind,entity_id=entity,operation=operation,replaces=previous if replaces=='auto' else replaces,captured_at=captured or int(time.time()*1000))
            targets=[{k:getattr(v,k) for k in ('id','account_id','signing_key','box_key')} for v in all_devices] if recipients is None else [self.identity(v) for v in recipients]
        payload=dict(body,domain='family-stalker.payload.v1',data=data or {'lat':12.3456789,'lon':-23.4567891,'accuracy':5})
        body['recipients']=sorted([dict(device_id=r['id'],box=B64(SealedBox(PublicKey(base64.b64decode(r['box_key']))).encrypt(canonical(payload)))) for r in targets],key=lambda r:r['device_id'])
        return dict(body=body,signature=B64(d['signing'].sign(canonical(body)).signature))

    def publish(self,d,**kwargs):
        body=self.record(d,**kwargs);r=self.call(d,'POST','/api/records',body);self.assertEqual(r.status_code,201,r.text);return body

    def decrypt(self,d,envelope):
        sender=next(x for x in self.devices if x['id']==envelope['body']['sender'])
        sender['signing'].verify_key.verify(canonical(envelope['body']),base64.b64decode(envelope['signature']))
        box=next(x['box'] for x in envelope['body']['recipients'] if x['device_id']==d['id'])
        return json.loads(SealedBox(d['box']).decrypt(base64.b64decode(box)))

    def test_email_verification_and_local_bootstrap_are_separate(self):
        with Session(self.app.state.engine) as db:
            db.get(Account,self.owner_id).verified=False;db.commit()
        signing,box=SigningKey.generate(),PrivateKey.generate()
        response=self.client.post('/api/devices/register',json=dict(id=secrets.token_hex(16),name='Unverified',signing_key=B64(signing.verify_key),box_key=B64(box.public_key),signature=B64(bytes(64))))
        self.assertEqual(response.status_code,403)
        with Session(self.app.state.engine) as db:
            db.get(Account,self.owner_id).verified=True;db.commit()
        d=self.register();r=self.call(d,'POST','/api/roster',self.roster(d,[d],'wrong'*8));self.assertEqual(r.status_code,403)
        self.assertEqual(self.call(d,'GET','/api/state').status_code,403)

    def test_pending_device_cannot_approve_itself_or_read_data(self):
        a=self.bootstrap();b=self.register()
        self.assertEqual(self.call(b,'POST','/api/roster',self.roster(b,[a,b])).status_code,403)
        self.assertEqual(self.call(b,'GET','/api/records').status_code,403)
        self.assertEqual(self.call(b,'POST','/api/records',self.record(b)).status_code,403)

    def test_two_device_roundtrip_database_has_no_plaintext_payload(self):
        a,b=self.pair();record=self.publish(a)
        for d in (a,b):
            fetched=self.call(d,'GET',f"/api/records/{record['body']['id']}")
            self.assertEqual(fetched.status_code,200)
            self.assertEqual(self.decrypt(d,fetched.json()['envelope'])['data']['lat'],12.3456789)
        with Session(self.app.state.engine) as db:
            stored=db.get(EncryptedRecord,record['body']['id'])
            self.assertNotIn('12.3456789',stored.envelope)
            self.assertNotIn('-23.4567891',stored.envelope)
            self.assertNotEqual(db.get(ClientDevice,a['id']).credential,a['credential'])

    def test_sender_signature_replay_and_duplicate_controls(self):
        a=self.bootstrap();r=self.publish(a)
        duplicate=self.call(a,'POST','/api/records',r);self.assertTrue(duplicate.json()['duplicate'])
        changed=copy.deepcopy(r);changed['body']['captured_at']-=1000
        self.assertEqual(self.call(a,'POST','/api/records',changed).status_code,403)
        replay=self.record(a,sequence=r['body']['sequence'])
        self.assertEqual(self.call(a,'POST','/api/records',replay).status_code,409)
        r['body']['id']=secrets.token_hex(16)
        self.assertEqual(self.call(a,'POST','/api/records',r).status_code,403)

    def test_stale_membership_and_missing_recipients_rejected(self):
        a=self.bootstrap();old=self.record(a);b=self.register()
        self.call(a,'POST','/api/roster',self.roster(a,[a,b]))
        self.assertEqual(self.call(a,'POST','/api/records',old).status_code,409)
        self.assertEqual(self.call(a,'POST','/api/records',self.record(a,recipients=[a])).status_code,409)

    def test_plaintext_fields_and_cross_household_forgery_rejected(self):
        a=self.bootstrap();r=self.record(a);r['body']['latitude']=12.3456789
        self.assertEqual(self.call(a,'POST','/api/records',r).status_code,422)
        r=self.record(a);r['body']['household']='f'*32;r['signature']=B64(a['signing'].sign(canonical(r['body'])).signature)
        self.assertEqual(self.call(a,'POST','/api/records',r).status_code,403)

    def test_old_offline_fix_does_not_replace_newer_latest(self):
        a=self.bootstrap();now=int(time.time()*1000);new=self.publish(a,captured=now);self.publish(a,captured=now-3600000)
        state=self.call(a,'GET','/api/state').json()['records']
        self.assertEqual(state[0]['envelope']['body']['id'],new['body']['id'])

    def test_expiry_hides_records_before_cleanup_and_rejects_old_upload(self):
        a=self.bootstrap();r=self.publish(a);future=time.time()+15*86400
        with patch('data_service.time.time',return_value=future):
            self.assertEqual(self.call(a,'GET',f"/api/records/{r['body']['id']}").status_code,404)
            self.assertEqual(self.call(a,'GET','/api/records').json()['records'],[])
            with Session(self.app.state.engine) as db:
                self.assertIsNotNone(db.get(EncryptedRecord,r['body']['id']))
            self.assertEqual(self.call(a,'POST','/api/records',self.record(a,captured=r['body']['captured_at'])).status_code,422)
            self.app.state.maintenance()
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(EncryptedRecord,r['body']['id']))

    def test_retention_shortening_deletes_history_but_keeps_places(self):
        a=self.bootstrap();old=int((time.time()-2*86400)*1000);r=self.publish(a,captured=old);place=self.publish(a,kind='place',data={'name':'Private School'},captured=old)
        self.assertEqual(self.client.put('/api/storage/retention',json={'days':1}).status_code,200)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(EncryptedRecord,r['body']['id']))
            self.assertIsNotNone(db.get(EncryptedRecord,place['body']['id']))
        self.assertEqual(self.client.put('/api/storage/retention',json={'days':15}).status_code,422)

    def test_place_compare_and_swap_and_tombstone(self):
        a=self.bootstrap();place=self.publish(a,kind='place',data={'name':'Private Home'})
        stale=self.record(a,kind='place',entity=place['body']['entity_id'],replaces=None)
        self.assertEqual(self.call(a,'POST','/api/records',stale).status_code,409)
        deleted=self.publish(a,kind='place',entity=place['body']['entity_id'],operation='delete',data={})
        state=self.call(a,'GET','/api/state').json()['records'][0]['envelope']
        self.assertEqual(state['body']['operation'],'delete')
        with Session(self.app.state.engine) as db:self.assertIsNone(db.get(EncryptedRecord,place['body']['id']))
        self.assertEqual(state['body']['id'],deleted['body']['id'])

    def test_equal_timestamp_pagination_never_drops_records(self):
        a=self.bootstrap();stamp=int(time.time()*1000);r1=self.publish(a,captured=stamp);r2=self.publish(a,captured=stamp)
        first=self.call(a,'GET','/api/records?limit=1').json();second=self.call(a,'GET',f"/api/records?limit=1&cursor={first['next_cursor']}").json()
        ids={first['records'][0]['envelope']['body']['id'],second['records'][0]['envelope']['body']['id']}
        self.assertEqual(ids,{r1['body']['id'],r2['body']['id']});self.assertIsNone(second['next_cursor'])

    def test_pause_hides_latest_and_blocks_new_location(self):
        a=self.bootstrap();self.publish(a)
        self.assertEqual(self.call(a,'PUT','/api/sharing',{'enabled':False}).status_code,200)
        self.assertEqual(self.call(a,'GET','/api/state').json()['records'],[])
        self.assertEqual(self.call(a,'POST','/api/records',self.record(a)).status_code,403)
        self.call(a,'PUT','/api/sharing',{'enabled':True})
        self.publish(a)

    def test_revocation_excludes_future_recipient_and_blocks_credential(self):
        a,b=self.pair();old=self.publish(a)
        self.assertEqual(self.call(a,'POST','/api/roster',self.roster(a,[a])).status_code,200)
        self.assertEqual(self.call(b,'GET','/api/state').status_code,401)
        future=self.publish(a)
        self.assertEqual([r['device_id'] for r in future['body']['recipients']],[a['id']])
        self.assertEqual(self.decrypt(b,old)['data']['lat'],12.3456789)

    def test_delete_own_history_does_not_delete_other_accounts_or_places(self):
        a=self.bootstrap();loc=self.publish(a);place=self.publish(a,kind='place',data={'name':'Persistent place'})
        self.assertEqual(self.call(a,'DELETE','/api/records/mine',{}).json()['deleted'],1)
        with Session(self.app.state.engine) as db:
            self.assertIsNone(db.get(EncryptedRecord,loc['body']['id']))
            self.assertIsNotNone(db.get(EncryptedRecord,place['body']['id']))
        self.assertEqual(self.call(a,'POST','/api/records',loc).status_code,409)

    def test_storage_quota_and_large_request_fail_closed(self):
        a=self.bootstrap();r=self.publish(a)
        with Session(self.app.state.engine) as db:db.get(EncryptedRecord,r['body']['id']).bytes=600*1048576;db.commit()
        self.assertEqual(self.call(a,'POST','/api/records',self.record(a)).status_code,507)
        response=self.client.post('/api/records',content=b'x'*1048577,headers={'Authorization':f"Bearer {a['credential']}",'Content-Type':'application/json'})
        self.assertEqual(response.status_code,413)

    def apns(self):
        key=ec.generate_private_key(ec.SECP256R1()).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        conf={'team_id':'A'*10,'key_id':'B'*10,'topic':'eco.roberts.stalker','sandbox':True,'private_key':key}
        self.assertEqual(self.client.put('/api/push/config',json={'apns':conf,'fcm':None}).status_code,200)
        return conf

    def test_push_secrets_encrypted_event_queue_and_provider_failure_retry(self):
        a,b=self.pair();conf=self.apns();token='c'*64
        self.call(b,'PUT','/api/push/subscription',{'provider':'apns','token':token})
        event=self.publish(a,kind='event',data={'message':'Secret: left Private Home'})
        with Session(self.app.state.engine) as db:
            self.assertNotIn(conf['private_key'],db.get(ServiceState,1).push_config)
            self.assertNotIn(token,db.get(PushSubscription,b['id']).token)
            self.assertEqual(db.query(PushDelivery).count(),1)
        self.assertNotIn('private_key',json.dumps(self.client.get('/api/push/config').json()))
        with patch('push_service.deliver',side_effect=OSError('provider-secret')):self.app.state.maintenance()
        with Session(self.app.state.engine) as db:
            job=db.scalar(select(PushDelivery));self.assertEqual(job.attempts,1);job.retry_at=0;db.commit()
        with patch('push_service.deliver',return_value='sent') as deliver:self.app.state.maintenance()
        self.assertEqual(deliver.call_args.args[2],event['body']['id'])
        self.assertNotIn('Private Home',repr(deliver.call_args))
        with Session(self.app.state.engine) as db:self.assertEqual(db.query(PushDelivery).count(),0)

    def test_apns_request_is_generic_and_invalid_registration_removed(self):
        a,b=self.pair();self.apns();self.call(b,'PUT','/api/push/subscription',{'provider':'apns','token':'c'*64});self.publish(a,kind='event',data={'message':'Coordinates 12.3456789 at Secret Home'})
        with patch('push_service.httpx.Client') as client:
            connection=client.return_value.__enter__.return_value;connection.post.return_value.status_code=410
            self.app.state.maintenance()
        request=connection.post.call_args
        self.assertEqual(request.args[0],'https://api.sandbox.push.apple.com/3/device/'+'c'*64)
        self.assertNotIn('12.3456789',json.dumps(request.kwargs['json']))
        self.assertNotIn('Secret Home',json.dumps(request.kwargs['json']))
        with Session(self.app.state.engine) as db:self.assertIsNone(db.get(PushSubscription,b['id']))

    def test_fcm_configuration_rejects_custom_token_endpoints(self):
        response=self.client.put('/api/push/config',json={'fcm':{'project_id':'synthetic-project','token_uri':'http://127.0.0.1/secret'}})
        self.assertEqual(response.status_code,422)

    def test_native_account_login_uses_bearer_without_browser_csrf(self):
        client=TestClient(self.app,base_url=test_setup.PUBLIC)
        r=client.post('/api/login',json={'email':test_setup.OWNER,'password':test_setup.PASSWORD,'native':True},headers={'X-Stalker-Client':'native'})
        self.assertEqual(r.status_code,200,r.text)
        token=r.json()['access_token'];client.cookies.clear()
        self.assertEqual(client.get('/api/session',headers={'Authorization':f'Bearer {token}'}).status_code,200)
        self.assertEqual(client.post('/api/logout',json={},headers={'Authorization':f'Bearer {token}'}).status_code,200)

    def member(self):
        ident=secrets.token_hex(16)
        with Session(self.app.state.engine) as db:
            db.add(Account(id=ident,email='member@example.invalid',username='member',password=HASHER.hash(test_setup.PASSWORD),status='active',verified=True,role='member'))
            db.commit()
        client=TestClient(self.app,base_url=test_setup.PUBLIC)
        client.headers['Origin']=test_setup.PUBLIC
        result=client.post('/api/login',json={'email':'member@example.invalid','password':test_setup.PASSWORD})
        self.assertEqual(result.status_code,200)
        client.headers['X-CSRF-Token']=result.json()['csrf']
        return ident,client

    def test_trusted_member_can_help_enroll_but_cannot_revoke_owner(self):
        a=self.bootstrap();member,client=self.member();b=self.register(client,member)
        self.assertEqual(self.call(a,'POST','/api/roster',self.roster(a,[a,b])).status_code,200)
        c=self.register()
        self.assertEqual(self.call(b,'POST','/api/roster',self.roster(b,[a,b,c])).status_code,200)
        self.assertEqual(self.call(b,'POST','/api/roster',self.roster(b,[b,c])).status_code,403)
        self.assertEqual(client.get('/api/storage').status_code,403)
        self.assertEqual(client.get('/api/push/config').status_code,403)

    def test_account_revocation_blocks_reads_and_requires_signed_reconciliation(self):
        a=self.bootstrap();member,client=self.member();b=self.register(client,member)
        self.call(a,'POST','/api/roster',self.roster(a,[a,b]));self.publish(a)
        self.assertEqual(self.client.post(f'/api/accounts/{member}/revoke',json={}).status_code,200)
        self.assertEqual(self.call(b,'GET','/api/state').status_code,401)
        self.assertEqual(self.call(a,'POST','/api/records',self.record(a,recipients=[a,b])).status_code,409)
        self.assertEqual(self.call(a,'POST','/api/roster',self.roster(a,[a])).status_code,200)
        self.publish(a)

    def test_new_device_cannot_read_history_encrypted_before_approval(self):
        a=self.bootstrap();old=self.publish(a);b=self.register()
        self.call(a,'POST','/api/roster',self.roster(a,[a,b]))
        self.assertEqual(self.call(b,'GET',f"/api/records/{old['body']['id']}").status_code,404)
        self.assertEqual(self.call(b,'GET','/api/records').json()['records'],[])
        self.publish(a)
        self.assertEqual(len(self.call(b,'GET','/api/records').json()['records']),1)

    def test_fcm_adapter_uses_fixed_google_hosts_and_generic_payload(self):
        a,b=self.pair()
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048).private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
        fcm={'type':'service_account','project_id':'synthetic-project','private_key_id':'synthetic','private_key':private,'client_email':'synthetic@synthetic-project.iam.gserviceaccount.com','token_uri':'https://oauth2.googleapis.com/token'}
        self.assertEqual(self.client.put('/api/push/config',json={'fcm':fcm}).status_code,200)
        self.call(b,'PUT','/api/push/subscription',{'provider':'fcm','token':'synthetic-registration-token'})
        self.publish(a,kind='event',data={'message':'Secret arrival at Private Home'})
        from google.oauth2 import service_account
        def refresh(credentials,request): credentials.token='synthetic-oauth-token'
        with patch.object(service_account.Credentials,'refresh',refresh),patch('push_service.httpx.Client') as client:
            connection=client.return_value.__enter__.return_value;connection.post.return_value.status_code=200
            self.app.state.maintenance()
        call=connection.post.call_args
        self.assertEqual(call.args[0],'https://fcm.googleapis.com/v1/projects/synthetic-project/messages:send')
        self.assertNotIn('Private Home',json.dumps(call.kwargs['json']))
        self.assertEqual(call.kwargs['headers']['authorization'],'Bearer synthetic-oauth-token')
        with Session(self.app.state.engine) as db:self.assertEqual(db.query(PushDelivery).count(),0)

    def test_version_one_upgrade_preserves_accounts_and_requires_matching_key(self):
        with Session(self.app.state.engine) as db:db.get(Settings,1).version=1;db.commit()
        self.app.state.initialize()
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.get(Settings,1).version,2)
            self.assertEqual(db.get(Account,self.owner_id).email,test_setup.OWNER)
        from cryptography.fernet import Fernet
        (self.path/'server.key').write_bytes(Fernet.generate_key())
        wrong=create_app(self.db_url,self.path,test_setup.PUBLIC,mail_worker=False)
        with self.assertRaises(RuntimeError):wrong.state.initialize()


if __name__=='__main__':unittest.main()
