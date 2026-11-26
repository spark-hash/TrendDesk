"""Stage stable releases alongside the current installation; activation belongs to the launcher."""
import hashlib
import json
import logging
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import tempfile
import time
from urllib.request import build_opener, HTTPRedirectHandler, Request
from urllib.parse import urlsplit
import zipfile

from app import __version__

REPO = "spark-hash/TrendDesk"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET = "TrendDesk-Windows-x64.zip"
MAX_DOWNLOAD = 192 * 1024**2
TAG = re.compile(r"v(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})")
REQUIRED = {"TrendDesk.exe", "runtime/python.exe", "program/desktop_server.py",
            "program/app/__init__.py", "program/web/index.html"}


class ReleaseRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != 'https' or target.netloc not in {
                'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}:
            raise ValueError('Unexpected release redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_release(url):
    return build_opener(ReleaseRedirects()).open(Request(url, headers={
        "User-Agent": "TrendDesk-Desktop/" + __version__,
    }), timeout=30)


def unpack(archive, target):
    seen = set()
    with zipfile.ZipFile(archive) as bundle:
        files = bundle.infolist()
        if len(files) > 20000 or sum(f.file_size for f in files) > 1024**3:
            raise ValueError("Oversized release")
        for entry in files:
            parts = entry.filename.rstrip('/').split('/')
            if parts == ['TrendDesk'] and entry.is_dir():
                continue
            if len(parts) < 2 or parts[0] != 'TrendDesk' or any(
                    not part or part in {'.', '..'} or part.endswith((' ', '.')) or
                    re.search(r'[\\:<>"|?*\x00-\x1f]', part) or PureWindowsPath(part).is_reserved()
                    for part in parts) or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("Unexpected ZIP path")
            name = '/'.join(parts[1:]).casefold()
            if name in seen:
                raise ValueError("Duplicate ZIP path")
            seen.add(name)
            dest = target.joinpath(*parts[1:])
            if entry.is_dir():
                dest.mkdir(exist_ok=True, parents=True)
            else:
                dest.parent.mkdir(exist_ok=True, parents=True)
                with bundle.open(entry) as source, dest.open('xb') as out:
                    shutil.copyfileobj(source, out)
    if not all((target / filename).is_file() for filename in REQUIRED):
        raise ValueError("Incomplete release")


def check_release(cache, fetch=open_release):
    with fetch(LATEST) as response:
        release = json.loads(response.read(1024**2))
    tag = release.get('tag_name', '')
    version = TAG.fullmatch(tag)
    if release.get('draft') or release.get('prerelease') or not version:
        return
    if tuple(map(int, version.groups())) <= tuple(map(int, __version__.split('.'))):
        return
    destination = cache / tag[1:]
    if destination.is_dir():
        return
    asset = next((a for a in release.get('assets', []) if a.get('name') == ASSET), {})
    url = f"https://github.com/{REPO}/releases/download/{tag}/{ASSET}"
    digest = asset.get('digest') or ''
    size = asset.get('size', 0)
    if (asset.get('browser_download_url') != url or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest)
            or not 0 < size <= MAX_DOWNLOAD):
        raise ValueError("Release asset or SHA-256 unavailable")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache, prefix='.download-') as scratch:
        archive = Path(scratch) / ASSET
        sha = hashlib.sha256()
        count = 0
        with fetch(url) as response, archive.open('xb') as out:
            while chunk := response.read(1024**2):
                count += len(chunk)
                if count > size:
                    raise ValueError("Oversized download")
                sha.update(chunk)
                out.write(chunk)
        if count != size or 'sha256:' + sha.hexdigest() != digest:
            raise ValueError("Release verification failed")
        staged = Path(scratch) / 'ready'
        unpack(archive, staged)
        staged.rename(destination)


def monitor_releases():
    cache = Path(os.environ['LOCALAPPDATA']) / 'TrendDesk' / 'versions'
    time.sleep(5)
    while True:
        try:
            check_release(cache)
            time.sleep(6 * 3600)
        except Exception as error:
            logging.warning("TrendDesk update check deferred: %s", type(error).__name__)
            time.sleep(3600)
