"""Bounded code-only ZIP exchange and explicit managed-integration removal."""
import io
import json
import shutil
import stat
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from .integrations import IntegrationError, MARKER, MAX_FILE, MAX_TOTAL, safe_relative, validate_domain
from .brand import PNG_PATHS, validate_png
from .action_logging import logger

MAX_ARCHIVE = 2_000_000

def checked_file(name, data):
    path = safe_relative(name)
    if ':' in name or path.name.lower() in {'secrets.yaml','secrets.yml','options.json'}:
        raise IntegrationError('Credential and runtime configuration files cannot be shared or imported')
    if len(data)>MAX_FILE: raise IntegrationError('Integration file is too large')
    if name in PNG_PATHS: validate_png(data, name)
    else: data.decode('utf-8')
    return path

class Transfers:
    def __init__(self, manager, store, ha, installations):
        self.manager,self.store,self.ha,self.installations=manager,store,ha,installations

    def sources(self, domain):
        validate_domain(domain)
        staged=self.manager.workspace(domain); installed=self.manager.installed_path(domain)
        if self.manager.backups.is_symlink() or (self.manager.backups/domain).is_symlink(): raise IntegrationError('Backup path must not be a symlink')
        if self.manager.workspaces.is_symlink(): raise IntegrationError('Workspace root must not be a symlink')
        if installed.exists() and not (installed/MARKER).is_file():
            raise IntegrationError('An unmanaged integration owns this domain')
        if not staged.is_dir() and not installed.is_dir(): raise IntegrationError('Managed integration not found')
        return staged,installed

    def import_zip(self, raw):
        if len(raw)>MAX_ARCHIVE: raise IntegrationError('ZIP exceeds the 2 MB upload limit')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                members=archive.infolist()
                if len(members)>1000: raise IntegrationError('Too many ZIP entries')
                files={}; seen=set(); total=0
                for item in members:
                    name=item.filename; parts=PurePosixPath(name).parts
                    if not parts or name.startswith('/') or '\\' in name or ':' in name or any(p in {'','.','..'} or p.endswith((' ','.')) for p in name.rstrip('/').split('/')) or '\x00' in name:
                        raise IntegrationError('Unsafe ZIP path')
                    if name.casefold() in seen: raise IntegrationError('Duplicate ZIP path')
                    seen.add(name.casefold())
                    mode=item.external_attr>>16
                    if stat.S_IFMT(mode) not in {0,stat.S_IFREG,stat.S_IFDIR}: raise IntegrationError('ZIP links and special files are not allowed')
                    if item.flag_bits&1: raise IntegrationError('Encrypted ZIP files are not supported')
                    if item.is_dir(): continue
                    total+=item.file_size
                    if item.file_size>MAX_FILE or total>MAX_TOTAL: raise IntegrationError('ZIP contents exceed integration limits')
                    with archive.open(item) as stream: data=stream.read(MAX_FILE+1)
                    if len(data)>MAX_FILE: raise IntegrationError('ZIP file exceeds size limit')
                    files[name]=data
                manifests=[(name,json.loads(data)) for name,data in files.items() if PurePosixPath(name).name=='manifest.json']
                manifests=[(name,m) for name,m in manifests if isinstance(m,dict) and m.get('domain') and m.get('name')]
                if len(manifests)!=1: raise IntegrationError('ZIP must contain exactly one integration manifest')
                manifest_path,manifest=manifests[0]; domain=validate_domain(manifest['domain'])
                if not isinstance(manifest['name'],str) or not manifest['name'].strip(): raise IntegrationError('Integration name must be text')
                prefix=manifest_path[:-len('manifest.json')]
                selected={name[len(prefix):]:data for name,data in files.items() if name.startswith(prefix)}
                if '__init__.py' not in selected: raise IntegrationError('Integration __init__.py is missing')
                checked={}
                for name,data in selected.items():
                    if name==MARKER or '__pycache__' in PurePosixPath(name).parts or name.endswith('.pyc'): continue
                    checked[str(checked_file(name,data))]=data
        except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError) as exc:
            raise IntegrationError('Invalid integration ZIP') from exc
        target=self.manager.workspace(domain)
        if self.manager.workspaces.is_symlink() or target.exists() or self.manager.installed_path(domain).exists():
            raise IntegrationError('Integration domain already exists or workspace root is unsafe; import cannot overwrite it')
        with tempfile.TemporaryDirectory(dir=self.manager.workspaces,prefix='.import-') as temporary:
            staging=Path(temporary)/domain; staging.mkdir()
            for name,data in checked.items():
                path=staging/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
            staging.rename(target)
        logger.info('Integration imported into staging | domain=%s',domain)
        self.store.audit('import_integration',{'domain':domain,'files':len(checked)})
        return {'domain':domain,'name':manifest['name'],'installed':False,'validation':self.manager.validate(domain)}

    def export_zip(self, domain):
        staged,installed=self.sources(domain); source=installed if installed.is_dir() else staged
        output=io.BytesIO(); total=0
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(source.rglob('*')):
                if file.is_symlink(): raise IntegrationError('Cannot share symlinked integration files')
                if not file.is_file(): continue
                name=file.relative_to(source).as_posix()
                if name==MARKER or '__pycache__' in file.relative_to(source).parts or file.suffix=='.pyc': continue
                if file.stat().st_size>MAX_FILE: raise IntegrationError('Integration file exceeds sharing limit')
                with file.open('rb') as stream: data=stream.read(MAX_FILE+1)
                checked_file(name,data); total+=len(data)
                if total>MAX_TOTAL: raise IntegrationError('Integration exceeds sharing limit')
                archive.writestr(f'custom_components/{domain}/{name}',data)
        logger.info('Integration code shared | domain=%s',domain)
        self.store.audit('share_integration',{'domain':domain})
        return output.getvalue()

    def uninstall(self, domain):
        with self.installations.lock:
            staged,installed=self.sources(domain)
            # Resolve/check both paths before backing up or deleting anything.
            for root,path in [(self.manager.workspaces,staged),(self.manager.installed,installed)]:
                if path.is_symlink() or path.resolve().parent!=root.resolve(): raise IntegrationError('Unsafe integration path')
            ident=uuid.uuid4().hex
            logger.info('Integration uninstall started | domain=%s',domain)
            operation={'domain':domain,'phase':'preparing','restart_required':installed.exists()}
            self.store.put('removals',ident,operation)
            try:
                backups=[]
                for source in [installed,staged]:
                    if source.exists():
                        stamp,_=self.manager._backup(domain,source); backups.append(stamp)
                operation['backups']=backups; self.store.put('removals',ident,operation)
                for item in self.installations.list():
                    if item['domain']==domain:
                        flow_id=item.get('flow_id') if item['phase'] not in {'complete','cancelled','removed'} else None
                        self.installations.update(item,'removed','Installation cancelled for uninstall.',values={},flow_id=None)
                        if flow_id:
                            self.ha.core('DELETE','/config/config_entries/flow/'+quote(flow_id,safe=''))
                if installed.exists():
                    for entry in self.ha.entries(domain):
                        if entry.get('domain',domain)!=domain: raise IntegrationError('Config entry domain mismatch')
                        result=self.ha.core('DELETE','/config/config_entries/entry/'+quote(entry['entry_id'],safe=''))
                        if isinstance(result,dict) and result.get('result') is False: raise IntegrationError('Home Assistant refused config entry removal')
                    if self.ha.entries(domain): raise IntegrationError('Config entries remain; source code was preserved')
                for source in [installed,staged]:
                    if source.exists(): shutil.rmtree(source)
                logger.info('Integration uninstall completed | domain=%s',domain)
                operation['phase']='complete'; self.store.put('removals',ident,operation)
                self.store.audit('uninstall_integration',operation)
                return operation
            except Exception:
                logger.info('Integration uninstall interrupted | domain=%s',domain)
                operation['phase']='interrupted'; self.store.put('removals',ident,operation)
                raise
