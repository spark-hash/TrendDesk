import hashlib
import io
import json
import zipfile

import pytest
from scripts import desktop_update as updater


def release(tmp_path, *, tag='v2.0.0', digest=None, extra=None, prerelease=False, approve=True):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as bundle:
        for name in updater.REQUIRED:
            bundle.writestr('TrendDesk/' + name, 'fixture')
        if extra:
            bundle.writestr(extra, 'fixture')
    payload = archive.getvalue()
    url = f'https://github.com/{updater.REPO}/releases/download/{tag}/{updater.ASSET}'
    metadata = {'tag_name': tag, 'prerelease': prerelease, 'assets': [{
        'name': updater.ASSET, 'size': len(payload), 'browser_download_url': url,
        'digest': 'sha256:' + (digest or hashlib.sha256(payload).hexdigest()),
    }]}
    calls = []

    def fetch(address):
        calls.append(address)
        return io.BytesIO({updater.LATEST: json.dumps(metadata).encode(), url: payload}[address])

    updater.check_release(tmp_path, lambda tag,size: approve, fetch)
    return calls


def test_stage_new_version_once(tmp_path):
    assert release(tmp_path, approve=False) == [updater.LATEST]
    assert not list(tmp_path.iterdir())
    assert len(release(tmp_path)) == 2
    assert (tmp_path / '2.0.0/TrendDesk.exe').is_file()
    assert release(tmp_path) == [updater.LATEST]


@pytest.mark.parametrize('options', [{'tag': 'v0.1.0'}, {'tag': 'v2.0.1-beta'}, {'prerelease': True}])
def test_ignore_ineligible_release(tmp_path, options):
    assert release(tmp_path, **options) == [updater.LATEST]
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('options', [{'digest': '0' * 64}, {'extra': 'TrendDesk/../outside'},
                                    {'extra': 'TrendDesk/runtime/python.exe:side'}])
def test_failed_update_preserves_current_version(tmp_path, options):
    old = tmp_path / '1.0.0'
    old.mkdir()
    with pytest.raises(ValueError):
        release(tmp_path, **options)
    assert list(tmp_path.iterdir()) == [old]
