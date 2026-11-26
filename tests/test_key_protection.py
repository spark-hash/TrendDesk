import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from uuid import uuid4
import pytest
from app.advisor import Advisor, AIConfig
from app.store import Store

pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='Windows DPAPI')


def test_dpapi_save_restart_update_clear(tmp_path, monkeypatch):
    path = tmp_path/'restart.db'
    db = Store(path)
    first = Advisor(db)
    key = 'test-only-'+uuid4().hex
    status = first.configure(AIConfig(model='demo', key=key))
    assert status['key_storage']=='dpapi' and key not in str(status)
    ciphertext = db.get('ai_key_dpapi_v1')
    assert ciphertext and key not in ciphertext
    first.configure(AIConfig(model='changed'))
    assert ciphertext == db.get('ai_key_dpapi_v1')
    db.db.close()
    assert all(key.encode() not in file.read_bytes() for file in tmp_path.iterdir() if file.is_file())

    # Only a digest of a disposable test value crosses into the second process.
    import hashlib
    child = """
import hashlib,sys
from app.store import Store
from app.advisor import Advisor
api = Advisor(Store(sys.argv[1]))
assert api.status()['key_storage']=='dpapi'
assert hashlib.sha256(api.key.encode()).hexdigest()==sys.argv[2]
"""
    subprocess.run([sys.executable,'-c',child,str(path),hashlib.sha256(key.encode()).hexdigest()],
                   cwd=Path(__file__).resolve().parents[1],check=True)
    monkeypatch.setenv('OPENAI_API_KEY','test-environment')
    reopened=Store(path)
    advisor=Advisor(reopened)
    assert advisor.key==key
    advisor.configure(AIConfig(model='changed',key=''))
    assert not Advisor(reopened).status()['configured']
    assert reopened.get('ai_key_dpapi_v1')==''


def test_unreadable_key_is_recoverable_and_write_failure_keeps_current(tmp_path, monkeypatch):
    store=Store(tmp_path/'recovery.db')
    store.set('ai_key_dpapi_v1','invalid!')
    advisor=Advisor(store)
    assert advisor.status()['key_storage']=='unreadable' and not advisor.key
    advisor.configure(AIConfig(model='baseline', key='test-replacement'))
    def fail(values):
        raise sqlite3.OperationalError('test disk full')
    monkeypatch.setattr(store,'set_many',fail)
    with pytest.raises(sqlite3.OperationalError):
        advisor.configure(AIConfig(model='new',key='test-different'))
    assert advisor.key=='test-replacement' and Advisor(store).key==advisor.key
    assert advisor.status()['model']=='baseline'
