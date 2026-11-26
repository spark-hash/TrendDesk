import os
import subprocess
from pathlib import Path

def notify(title, message):
    if os.name != 'nt':
        return False
    # Values travel as data in environment variables, never interpolated into PowerShell.
    env = os.environ.copy()
    env['TREND_DESK_TITLE'] = title[:60]
    env['TREND_DESK_MESSAGE'] = message[:220]
    subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                      '-File',str(Path(__file__).parent.parent/'scripts'/'notify.ps1')],
                     env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    return True
