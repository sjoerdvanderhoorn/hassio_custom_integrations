import json
from pathlib import Path
import pytest

from app.integrations import IntegrationManager, IntegrationError, safe_relative, validate_domain


@pytest.fixture
def manager(tmp_path):
    return IntegrationManager(tmp_path / 'data', tmp_path / 'config')


def files(domain='wifi_lamp'):
    return [
        {'path': 'manifest.json', 'content': json.dumps({'domain': domain, 'name': 'WiFi Lamp', 'version': '0.0.1', 'documentation': 'https://example.org', 'codeowners': [], 'iot_class': 'local_polling', 'config_flow': True, 'requirements': []})},
        {'path': '__init__.py', 'content': 'async def async_setup_entry(hass, entry):\n    return True\n'},
        {'path': 'config_flow.py', 'content': 'from homeassistant import config_entries\nclass ConfigFlow(config_entries.ConfigFlow, domain="wifi_lamp"):\n    pass\n'},
    ]


def test_write_validate_deploy_and_backup(manager):
    first = manager.write_files('wifi_lamp', files())
    assert first['validation']['ok'] is True
    result = manager.deploy('wifi_lamp')
    assert result['restart_required'] is True
    assert manager.list_domains() == [{'domain': 'wifi_lamp', 'staged': True, 'installed': True}]
    assert 'staged/manifest.json' not in manager.preview('wifi_lamp')
    manager.write_files('wifi_lamp', [{'path': '__init__.py', 'content': '# second version\n'}])
    assert 'second version' in manager.preview('wifi_lamp')
    second = manager.deploy('wifi_lamp')
    assert second['backup']
    restore = manager.rollback('wifi_lamp', second['backup'])
    assert restore['restart_required'] is True
    assert 'async_setup_entry' in (manager.installed_path('wifi_lamp') / '__init__.py').read_text()


@pytest.mark.parametrize('path', ['/etc/passwd', '../secrets.yaml', 'nested/../../ha/.storage', 'test\\..\\x.py', '.hidden.py', 'foo.sh', 'x.py/../y.py'])
def test_forbid_bad_paths(path):
    with pytest.raises(IntegrationError):
        safe_relative(path)


@pytest.mark.parametrize('domain', ['ha-bridge', '../core', 'HOME', 'hacs', 'a', ''])
def test_forbid_bad_domain(domain):
    with pytest.raises(IntegrationError):
        validate_domain(domain)


def test_refuse_ownership_collision(manager):
    manager.write_files('wifi_lamp', files())
    foreign = manager.installed_path('wifi_lamp')
    foreign.mkdir(parents=True)
    (foreign / 'manifest.json').write_text('{}')
    with pytest.raises(IntegrationError, match='unmanaged'):
        manager.deploy('wifi_lamp')


def test_python_syntax_and_no_dangerous_functions(manager):
    with pytest.raises(SyntaxError):
        manager.write_files('wifi_lamp', [{'path': 'x.py', 'content': 'def broken(\n'}])
    manager.write_files('wifi_lamp', files() + [{'path':'evil.py','content':'import subprocess\nexec("x")\n'}])
    report = manager.validate('wifi_lamp')
    assert not report['ok']
    assert 'potentially dangerous import' in ' '.join(report['errors'])
    assert 'dynamic code' in ' '.join(report['errors'])


def test_cannot_read_unmanaged_integration(manager):
    foreign = manager.installed_path('some_device')
    foreign.mkdir(parents=True)
    (foreign / 'manifest.json').write_text('some secrets')
    with pytest.raises(IntegrationError):
        manager.read_file('some_device', 'manifest.json', deployed=True)


def test_no_symlink_writes(manager, tmp_path):
    path = manager.workspace('wifi_lamp')
    path.mkdir()
    try:
        (path / 'nested').symlink_to(tmp_path, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, 'winerror', None) == 1314:
            pytest.skip('Windows account cannot create symlinks; run this check on Linux')
        raise
    with pytest.raises(IntegrationError):
        manager.write_files('wifi_lamp', [{'path':'nested/test.py','content':'x=1'}])
