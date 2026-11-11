#!/usr/bin/env python3
"""Install the owner's daily independent DB backup check."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess

os.umask(0o077)
label = 'ru.zeraigr.media-knowledge.db-backup-check'
home = Path.home()
assert (home / '.config/media-knowledge/database-backup.json').is_file()
app = home / 'Library/Application Support/MediaKnowledgeBackup'
app.mkdir(parents=True, exist_ok=True, mode=0o700)
script = app / 'verify-from-mac.py'
shutil.copyfile(Path(__file__).with_name('verify-from-mac.py'), script)
agents = home / 'Library/LaunchAgents'
agents.mkdir(exist_ok=True)
plist = agents / (label + '.plist')
document = {'Label': label, 'ProgramArguments': [shutil.which('python3'), str(script)],
            'StartCalendarInterval': {'Hour': 11, 'Minute': 30},
            'StandardOutPath': str(app / 'check.log'), 'StandardErrorPath': str(app / 'error.log'),
            'ProcessType': 'Background', 'LowPriorityIO': True,
            'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'}}
plist.write_bytes(plistlib.dumps(document))
subprocess.run(['plutil', '-lint', str(plist)], check=True)
domain = 'gui/' + str(os.getuid())
subprocess.run(['launchctl', 'bootout', domain + '/' + label], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
subprocess.run(['launchctl', 'bootstrap', domain, str(plist)], check=True)
print('Daily independent DB check installed at 11:30 local Mac time')
