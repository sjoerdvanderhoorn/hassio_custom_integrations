"""Compressed, dated code revisions, separate from deployment backups."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


class History:
    def __init__(self, manager):
        self.manager = manager
        self.root = manager.workspaces.parent / 'snapshots'

    def directory(self, domain):
        self.manager.check_domain(domain)
        target = self.root / domain
        if self.root.is_symlink() or target.is_symlink():
            raise ValueError('Snapshot links are not allowed')
        return target

    def save(self, domain, reason, source=None):
        from .integrations import MARKER, MAX_FILE, MAX_TOTAL, safe_relative, IntegrationError
        source = source or self.manager.workspace(domain)
        if not source.exists(): return None
        if source.is_symlink(): raise IntegrationError('Snapshot source must not be a link')
        files = []; total = 0; digest = hashlib.sha256()
        for path in sorted(source.rglob('*')):
            if path.is_symlink(): raise IntegrationError('Cannot snapshot linked source')
            if not path.is_file(): continue
            name = path.relative_to(source).as_posix()
            if name == MARKER or '__pycache__' in path.parts or path.suffix == '.pyc': continue
            safe_relative(name)
            if path.stat().st_size > MAX_FILE: raise ValueError('Snapshot file exceeds size limit')
            data = path.read_bytes(); total += len(data)
            if total > MAX_TOTAL: raise ValueError('Snapshot exceeds integration size limit')
            digest.update(name.encode() + b'\0' + data + b'\0'); files.append((name, data))
        if not files: return None
        folder = self.directory(domain); folder.mkdir(parents=True, exist_ok=True)
        previous = self.list(domain)
        kind = 'installed' if source == self.manager.installed_path(domain) else 'staged'
        if previous and previous[0]['sha256'] == digest.hexdigest() and previous[0]['source'] == kind:
            return previous[0]['id']
        moment = datetime.now(timezone.utc); ident = moment.strftime('%Y%m%dT%H%M%S%fZ')
        target = folder / (ident + '.zip'); temporary = folder / (ident + '.tmp')
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in files: archive.writestr(name, data)
        os.replace(temporary, target)
        metadata = {'id': ident, 'created': moment.isoformat(), 'reason': reason, 'source': kind,
                    'sha256': digest.hexdigest(), 'files': [name for name, _ in files], 'bytes': target.stat().st_size}
        meta = folder / (ident + '.json'); meta.write_text(json.dumps(metadata), encoding='utf-8')
        self.prune(domain)
        return ident

    def list(self, domain):
        folder = self.directory(domain)
        if not folder.exists(): return []
        entries = []
        for path in folder.glob('*.json'):
            if path.is_symlink(): continue
            try:
                item = json.loads(path.read_text(encoding='utf-8'))
                if re.fullmatch(r'\d{8}T\d{12}Z', item['id']) and (folder/(item['id']+'.zip')).is_file(): entries.append(item)
            except (ValueError, KeyError, OSError): continue
        return sorted(entries, key=lambda item: item['id'], reverse=True)

    def prune(self, domain):
        entries = self.list(domain); keep = {item['id'] for item in entries[:100]}; days = set()
        for item in entries:
            day = item['created'][:10]
            if day not in days and len(days) < 30: keep.add(item['id']); days.add(day)
        folder = self.directory(domain)
        for item in entries:
            if item['id'] not in keep:
                for suffix in ('.zip', '.json'): (folder/(item['id']+suffix)).unlink(missing_ok=True)

    def contents(self, domain, revision):
        from .integrations import MAX_FILE, MAX_TOTAL, safe_relative
        if not re.fullmatch(r'\d{8}T\d{12}Z', revision): raise ValueError('Invalid revision ID')
        folder = self.directory(domain); path = folder/(revision+'.zip')
        if path.is_symlink(): raise ValueError('Snapshot links are not allowed')
        result = {}; total = 0
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 1000: raise ValueError('Too many snapshot files')
            for item in archive.infolist():
                safe_relative(item.filename)
                if item.file_size > MAX_FILE: raise ValueError('Snapshot file too large')
                with archive.open(item) as stream: data = stream.read(MAX_FILE+1)
                total += len(data)
                if len(data)>MAX_FILE or total>MAX_TOTAL: raise ValueError('Snapshot exceeds size limits')
                result[item.filename] = data
        return result

    def read(self, domain, revision, paths):
        from .integrations import safe_relative
        if not isinstance(paths, list) or not 1 <= len(paths) <= 30: raise ValueError('Read 1 to 30 snapshot files')
        files = self.contents(domain, revision); result = []; size = 0
        for name in dict.fromkeys(paths):
            safe_relative(name); data = files[name]; size += len(data)
            if size > 90000: raise ValueError('Snapshot read exceeds 90 KB; request fewer files')
            result.append({'path':name, 'sha256':hashlib.sha256(data).hexdigest()} if name.endswith('.png') else {'path':name,'content':data.decode('utf-8').replace('\r\n','\n').replace('\r','\n')})
        return {'domain':domain,'revision':revision,'files':result}

    def restore(self, domain, revision):
        self.manager.check_domain(domain)
        files = self.contents(domain, revision); target = self.manager.workspace(domain)
        self.save(domain, 'Before restoring revision')
        with tempfile.TemporaryDirectory(dir=self.manager.workspaces, prefix='.restore-') as temporary:
            stage = Path(temporary)/domain; stage.mkdir()
            for name,data in files.items():
                path=stage/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
            previous=Path(temporary)/'previous'
            if target.exists(): target.rename(previous)
            try: stage.rename(target)
            except Exception:
                if previous.exists(): previous.rename(target)
                raise
        self.save(domain, 'Restored '+revision)
        return {'domain':domain,'revision':revision,'restored_to':'staging','installed_code_changed':False,
                'message':'Revision restored to staging. Review and approve installation/restart to apply it to Home Assistant.'}
