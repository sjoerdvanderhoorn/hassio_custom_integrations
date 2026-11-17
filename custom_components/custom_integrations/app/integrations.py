"""Staging, validation, versioned deployments, rollback and path isolation.

Generated Python is untrusted until the administrator approves installation.
Static checks prevent accidents, not malicious behavior after installation.
"""
from __future__ import annotations

import ast
import difflib
import json
import os
import re
import shutil
import tempfile
import hashlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from .brand import PNG_PATHS, render_icon, validate_png

DOMAIN = re.compile(r"^[a-z][a-z0-9_]{2,47}$")
ALLOWED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".md", ".txt"}
MAX_FILE = 160_000
MAX_TOTAL = 1_500_000
MARKER = ".ai_builder_managed.json"


class IntegrationError(ValueError):
    pass


def validate_domain(domain: str):
    if not isinstance(domain, str) or not DOMAIN.fullmatch(domain) or domain.startswith("_"):
        raise IntegrationError("Invalid domain; use a-z, 0-9 and _." )
    if domain in {"custom_integrations", "homeassistant", "hacs", "default_config", "config", "persistent_notification"}:
        raise IntegrationError("This integration domain is reserved.")
    return domain


def safe_relative(path: str) -> Path:
    if not isinstance(path, str) or "\\" in path or "\x00" in path:
        raise IntegrationError("Invalid file path")
    pure = PurePosixPath(path)
    if pure.is_absolute() or len(pure.parts) > 5 or not pure.parts or any(p in {"", ".", ".."} for p in pure.parts):
        raise IntegrationError("File path is outside the integration")
    if any(p.startswith(".") for p in pure.parts):
        raise IntegrationError("Hidden files are not allowed")
    result = Path(*pure.parts)
    if result.suffix.lower() not in ALLOWED_SUFFIXES and pure.as_posix() not in PNG_PATHS:
        raise IntegrationError("Only Python, JSON, YAML and documentation files are allowed")
    return result


def is_below(base: Path, target: Path):
    return target.resolve().is_relative_to(base.resolve())


class IntegrationManager:
    def __init__(self, data: Path, ha_config: Path):
        self.blocked_domains = set()
        self.workspaces = data / "workspaces"
        self.backups = data / "backups"
        self.installed = ha_config / "custom_components"
        self.workspaces.mkdir(parents=True, exist_ok=True)
        self.backups.mkdir(parents=True, exist_ok=True)

    def check_domain(self, domain):
        validate_domain(domain)
        if domain in self.blocked_domains:
            raise IntegrationError("Replacing a built-in Home Assistant integration is not supported; choose a unique custom domain")

    def workspace(self, domain: str) -> Path:
        self.check_domain(domain)
        target = self.workspaces / domain
        if target.is_symlink():
            raise IntegrationError("Symbolic links are not allowed")
        return target

    def installed_path(self, domain: str) -> Path:
        self.check_domain(domain)
        if self.installed.is_symlink():
            raise IntegrationError("Symbolic links are not allowed")
        path = self.installed / domain
        if path.is_symlink() or not is_below(self.installed, path):
            raise IntegrationError("Symbolic links are not allowed")
        return path

    def write_files(self, domain: str, files: list[dict]):
        base = self.workspace(domain)
        if not isinstance(files, list) or not 1 <= len(files) <= 30:
            raise IntegrationError("Write 1 to 30 files at a time")
        checked = []
        size = 0
        for item in files:
            rel = safe_relative(item.get("path"))
            if rel.suffix=='.png':
                raise IntegrationError('Use generate_integration_icon to create binary brand images')
            content = item.get("content")
            if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE:
                raise IntegrationError(f"File too large: {rel}")
            if rel.suffix == ".py":
                ast.parse(content, filename=str(rel))
            if rel.suffix == ".json":
                json.loads(content)
            size += len(content.encode("utf-8"))
            checked.append((rel, content))
        if size > MAX_TOTAL:
            raise IntegrationError("Total size too large")
        base.mkdir(parents=True, exist_ok=True)
        for rel, content in checked:
            path = base / rel
            if not is_below(base, path) or any(p.is_symlink() for p in [*path.parents, path] if p != Path("/")):
                raise IntegrationError("Symbolic links are not allowed")
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(content, encoding="utf-8")
            os.replace(temp, path)
        return {"domain": domain, "written": [str(p) for p, _ in checked], "validation": self.validate(domain)}

    def generate_icon(self, domain, background, shapes):
        content=render_icon(background,shapes)
        base=self.workspace(domain);path=base/'brand'/'icon.png'
        if not is_below(base,path) or any(p.is_symlink() for p in [*path.parents,path]):
            raise IntegrationError('Symbolic links are not allowed')
        path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name('icon.png.tmp');temp.write_bytes(content);os.replace(temp,path)
        return {'domain':domain,'path':'brand/icon.png','width':256,'height':256,'sha256':hashlib.sha256(content).hexdigest()}

    def has_icon(self, domain):
        path=self.workspace(domain)/'brand'/'icon.png'
        if not path.is_file() or any(p.is_symlink() for p in [*path.parents,path]):return False
        if path.stat().st_size>MAX_FILE:return False
        try:validate_png(path.read_bytes());return True
        except (ValueError,OSError):return False

    def read_file(self, domain: str, file: str, deployed: bool = False):
        base = self.installed_path(domain) if deployed else self.workspace(domain)
        if deployed and not (base / MARKER).is_file():
            raise IntegrationError("Only managed integrations can be read")
        p = base / safe_relative(file)
        if not is_below(base, p) or p.is_symlink():
            raise IntegrationError("Invalid path")
        if p.stat().st_size > MAX_FILE:
            raise IntegrationError("File is too large")
        if p.suffix=='.png':
            content=p.read_bytes()
            return {'domain':domain,'path':file,'format':'PNG','bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
        return {"domain": domain, "path": file, "content": p.read_text(encoding="utf-8")}

    def validate(self, domain: str):
        base = self.workspace(domain)
        errors = []
        warnings = []
        files = []
        if not base.is_dir():
            return {"ok": False, "errors": ["Workspace is missing"], "warnings": [], "files": []}
        total = 0
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                errors.append(f"Symbolic link is not allowed: {path.name}")
                continue
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            try:
                safe_relative(rel)
                size = path.stat().st_size
                total += size
                if size > MAX_FILE:
                    errors.append(f"File too large: {rel}")
                elif path.suffix == ".py":
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.Import, ast.ImportFrom)):
                            mods = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                            if any(m.split(".")[0] in {"subprocess", "ctypes", "pickle", "marshal", "runpy"} for m in mods):
                                errors.append(f"{rel}: potentially dangerous import is prohibited")
                        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "__import__"}:
                            errors.append(f"{rel}: dynamic code execution is prohibited")
                elif path.suffix == ".json":
                    json.loads(path.read_text(encoding="utf-8"))
                elif path.suffix=='.png':
                    validate_png(path.read_bytes(),rel)
            except (IntegrationError, SyntaxError, ValueError, UnicodeError) as exc:
                errors.append(f"{rel}: {exc}")
            files.append(rel)
        if total > MAX_TOTAL:
            errors.append("Integration exceeds 1.5 MB")
        if "__init__.py" not in files:
            errors.append("__init__.py is missing")
        if "manifest.json" not in files:
            errors.append("manifest.json is missing")
        else:
            try:
                manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
                if manifest.get("domain") != domain:
                    errors.append("Domain in manifest.json does not match")
                for key in ("name", "version", "documentation", "codeowners", "iot_class"):
                    if key not in manifest:
                        errors.append(f"Manifest is missing {key}")
                if manifest.get("config_flow") and "config_flow.py" not in files:
                    errors.append("config_flow.py is missing")
                if not manifest.get("config_flow"):
                    warnings.append("No config flow: automatic registration is unavailable")
                requirements = manifest.get("requirements", [])
                if not isinstance(requirements, list) or len(requirements) > 15:
                    errors.append("Invalid dependencies")
            except (ValueError, OSError) as exc:
                errors.append(f"Manifest: {exc}")
        if 'brand/icon.png' not in files:
            warnings.append('Generate a matching brand/icon.png before installing a new integration')
        return {"ok": not errors, "errors": errors, "warnings": warnings, "files": files}

    def preview(self, domain: str):
        """Human-reviewable diff between staged files and deployed version."""
        source = self.workspace(domain)
        target = self.installed_path(domain)
        pieces = []
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            rel = safe_relative(path.relative_to(source).as_posix())
            if path.suffix=='.png':
                oldfile=target/rel
                content=path.read_bytes()
                if not oldfile.is_file() or any(p.is_symlink() for p in [*oldfile.parents,oldfile]) or oldfile.read_bytes()!=content:
                    pieces.append(f'Binary brand image: {rel.as_posix()}; PNG; {len(content)} bytes; SHA256 {hashlib.sha256(content).hexdigest()}\n')
                continue
            new = path.read_text(encoding="utf-8").splitlines(keepends=True)
            oldfile = target / rel
            old = oldfile.read_text(encoding="utf-8").splitlines(keepends=True) if oldfile.is_file() and not oldfile.is_symlink() else []
            pieces.extend(difflib.unified_diff(old, new, fromfile=f"installed/{rel}", tofile=f"staged/{rel}"))
        return "".join(pieces)[:100000]

    def list_domains(self):
        domains = set()
        for base in (self.workspaces, self.installed):
            if base.exists():
                for p in base.iterdir():
                    if p.is_dir() and DOMAIN.fullmatch(p.name):
                        if base == self.workspaces or (p / MARKER).exists():
                            domains.add(p.name)
        return [{"domain": d, "staged": self.workspace(d).exists(), "installed": (self.installed_path(d) / MARKER).exists()} for d in sorted(domains - self.blocked_domains)]

    def _backup(self, domain: str, target: Path):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self.backups / domain / stamp
        destination.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.copytree(target, destination, symlinks=True)
        return stamp, destination

    def deploy(self, domain: str):
        report = self.validate(domain)
        if not report["ok"]:
            raise IntegrationError("Validation failed: " + "; ".join(report["errors"]))
        source = self.workspace(domain)
        target = self.installed_path(domain)
        if target.exists() and not (target / MARKER).is_file():
            raise IntegrationError("An unmanaged integration with this domain already exists; refusing to overwrite")
        self.installed.mkdir(parents=True, exist_ok=True)
        stamp, backup = self._backup(domain, target)
        temp_parent = Path(tempfile.mkdtemp(prefix="ai_builder_", dir=self.installed))
        staged = temp_parent / domain
        try:
            shutil.copytree(source, staged, symlinks=False)
            # Legacy workspaces can omit artwork already present in a managed deployment.
            for relative in PNG_PATHS:
                existing=target/relative;destination=staged/relative
                if not destination.exists() and existing.is_file() and not any(p.is_symlink() for p in [*existing.parents,existing]):
                    if existing.stat().st_size>MAX_FILE:raise IntegrationError('Existing brand image is too large')
                    validate_png(existing.read_bytes(),relative)
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(existing,destination)
            (staged / MARKER).write_text(json.dumps({"domain": domain, "installed_at": stamp}))
            if target.exists():
                shutil.rmtree(target)
            os.replace(staged, target)
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if backup.exists():
                shutil.copytree(backup, target)
            raise
        finally:
            shutil.rmtree(temp_parent, ignore_errors=True)
        return {"deployed": domain, "backup": stamp if backup.exists() else None, "restart_required": True}

    def rollback(self, domain: str, backup: str):
        validate_domain(domain)
        if not re.fullmatch(r"\d{8}T\d{12}Z", backup):
            raise IntegrationError("Invalid backup ID")
        original = self.backups / domain / backup
        if not original.is_dir() or original.is_symlink():
            raise IntegrationError("Backup not found")
        target = self.installed_path(domain)
        if target.exists() and not (target / MARKER).exists():
            raise IntegrationError("Refusing to overwrite an unmanaged integration")
        new_backup, _ = self._backup(domain, target)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(original, target, symlinks=False)
        return {"restored": domain, "backup": backup, "pre_rollback_backup": new_backup, "restart_required": True}

    def backups_for(self, domain: str):
        p = self.backups / validate_domain(domain)
        return sorted([x.name for x in p.iterdir() if x.is_dir()], reverse=True) if p.exists() else []
