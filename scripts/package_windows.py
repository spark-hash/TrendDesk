"""Build a relocatable Windows x64 ZIP from the project's installed runtime."""
from importlib.metadata import distribution
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
import runpy

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts'
DIST = ROOT / 'dist'
SKIP = shutil.ignore_patterns('__pycache__', '*.pyc', '*.pyo')


def copy_runtime(target):
    base = Path(sys.base_prefix)
    target.mkdir()
    for name in ['python.exe', 'python3.dll', f'python{sys.version_info.major}{sys.version_info.minor}.dll',
                 'vcruntime140.dll','vcruntime140_1.dll','LICENSE.txt']:
        shutil.copy2(base/name, target/name)
    shutil.copytree(base/'DLLs', target/'DLLs', ignore=shutil.ignore_patterns('*test*','*tk*','tcl*.dll'))
    lib = target/'Lib'
    lib.mkdir()
    for src in (base/'Lib').iterdir():
        if src.name in {'site-packages','__pycache__','test','idlelib','tkinter','ensurepip','turtledemo'}:
            continue
        if src.is_dir():
            shutil.copytree(src, lib/src.name, ignore=SKIP)
        elif src.suffix in ('.py','.txt') or src.name == 'codex-rejected-cas.pem':
            shutil.copy2(src, lib/src.name)

    # Package only files listed in runtime wheel manifests, including data and licenses.
    seen = set()
    requirements = [Requirement(s) for s in (ROOT/'requirements.txt').read_text().splitlines() if s.strip()]
    pending = [r for r in requirements if r.name!='pytest']
    for req in pending:
        if req.marker and not req.marker.evaluate(): continue
        dist = distribution(req.name)
        if not req.specifier.contains(dist.version):
            raise RuntimeError(f'Installed {dist.metadata["Name"]} {dist.version} does not satisfy {req}')
        name = canonicalize_name(req.name)
        if name in seen: continue
        seen.add(name)
        pending.extend(Requirement(s) for s in dist.requires or ())
        if not dist.files: raise RuntimeError(f'Missing wheel manifest for {name}')
        for file in dist.files:
            if file.is_absolute() or any(part in ('..','__pycache__','tests') for part in file.parts):
                continue
            if file.suffix in ('.pyc','.pyo'): continue
            dest = lib/'site-packages'/file
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(dist.locate_file(file),dest)


def build():
    if os.name!='nt' or struct.calcsize('P')!=8 or sys.prefix==sys.base_prefix:
        raise RuntimeError('Run with the project Windows x64 virtual environment.')
    DIST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='trenddesk-build-', dir=DIST) as tmp:
        stage = Path(tmp)/'TrendDesk'
        stage.mkdir()
        copy_runtime(stage/'runtime')
        subprocess.run([str(stage/'runtime/python.exe'), '-I', '-B', '-c',
                        'import ssl; ssl.create_default_context()'], check=True)
        program = stage/'program'
        shutil.copytree(ROOT/'app', program/'app', ignore=SKIP)
        shutil.copytree(ROOT/'web', program/'web')
        shutil.copytree(ROOT/'financialjuice-extension', stage/'financialjuice-extension')
        (program/'scripts').mkdir()
        shutil.copy2(SCRIPTS/'notify.ps1',program/'scripts')
        shutil.copy2(SCRIPTS/'desktop_server.py',program)
        shutil.copy2(SCRIPTS/'desktop_update.py',program)
        shutil.copy2(SCRIPTS/'windows-release.txt',stage/'使用说明.txt')
        compiler = Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        version = runpy.run_path(str(ROOT/'app/__init__.py'))['__version__']
        version_source = Path(tmp)/'Version.cs'
        version_source.write_text(f'[assembly: System.Reflection.AssemblyVersion("{version}.0")]', encoding='utf8')
        subprocess.run([str(compiler),'/nologo','/codepage:65001','/target:winexe','/platform:x64','/optimize+',
                        '/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll',
                        '/win32icon:'+str(SCRIPTS/'trenddesk.ico'),'/out:'+str(stage/'TrendDesk.exe'),
                        str(SCRIPTS/'TrendDesk.cs'), str(version_source)],check=True)
        archive = Path(tmp)/'TrendDesk-Windows-x64.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
            for src in sorted(stage.rglob('*')):
                if src.is_file(): bundle.write(src,src.relative_to(stage.parent))
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None: raise RuntimeError('ZIP verification failed')
        archive.replace(DIST/archive.name)
        print(DIST/archive.name)


if __name__=='__main__':
    build()
