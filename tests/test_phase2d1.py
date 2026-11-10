"""Portable protocol and packaging tests; no Frappe/Press installation required."""
import base64
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'app/frappe_restic_portal/frappe_restic_portal'
spec=importlib.util.spec_from_file_location('portal_crypto',PKG/'crypto.py')
crypto=importlib.util.module_from_spec(spec)
spec.loader.exec_module(crypto)

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.key=self.base/'key.pem'; self.pub=self.base/'pub.pem'
        subprocess.run(['openssl','genpkey','-algorithm','Ed25519','-out',str(self.key)],check=True,capture_output=True)
        subprocess.run(['openssl','pkey','-in',str(self.key),'-pubout','-out',str(self.pub)],check=True,capture_output=True)
        self.p={'format':'restic-site-portal-v1','site':'erp-standard-test.frappe.netlinkz.co.za',
                'request_id':'f'*32,'action':'inventory',
                'created_at':datetime.now(timezone.utc).isoformat(),
                'data':{'snapshots':[]}}
    def signed(self,p=None,domain=crypto.DOMAIN):
        payload=p or self.p
        body=self.base/'body';body.write_bytes(domain+crypto.canonical(payload))
        cp=subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(self.key),'-in',str(body)],check=True,capture_output=True)
        return {'payload':payload,'signature':base64.b64encode(cp.stdout).decode()}
    def test_signature_and_scope(self):
        result=crypto.verify_envelope(self.signed(),self.pub)
        self.assertEqual(crypto.validate_payload(result,self.p['site']),self.p)
        with self.assertRaises(ValueError):crypto.validate_payload(result,'other.frappe.netlinkz.co.za')
    def test_modified_payload_rejected(self):
        e=self.signed();e['payload']['action']='status'
        with self.assertRaises(ValueError):crypto.verify_envelope(e,self.pub)
    def test_cross_protocol_signature_rejected(self):
        with self.assertRaises(ValueError):crypto.verify_envelope(self.signed(domain=b'FRAPPE_RESTIC_RESTORE_CONTROL_V1\n'),self.pub)
    def test_expiration(self):
        p=dict(self.p);p['created_at']=(datetime.now(timezone.utc)-timedelta(minutes=6)).isoformat()
        with self.assertRaises(ValueError):crypto.validate_payload(p,p['site'])
    def test_unexpected_action(self):
        p=dict(self.p);p['action']='execute-restore'
        with self.assertRaises(ValueError):crypto.validate_payload(p,p['site'])
    def test_doctype_permissions(self):
        dt=PKG/'restic_portal/doctype'
        req=json.loads((dt/'restic_restore_request/restic_restore_request.json').read_text())
        self.assertEqual(req['name'],'Restic Restore Request')
        self.assertTrue(all(not p.get('write') and not p.get('delete') for p in req['permissions']))
        self.assertTrue(any(p.get('create') for p in req['permissions']))
        point=json.loads((dt/'restic_recovery_point/restic_recovery_point.json').read_text())
        self.assertTrue(all(not p.get('create') for p in point['permissions']))
        self.assertTrue(all(not p.get('write') for p in point['permissions']))
    def test_no_customer_restore_execution(self):
        s=(PKG/'api.py').read_text()
        self.assertNotIn('bench restore',s)
        self.assertNotIn('restore_site(',s)
        self.assertNotIn('mariadb_root_password',s)
        self.assertNotIn('restic_password',s)
        self.assertIn('Replay rejected',s)

if __name__=='__main__': unittest.main()
