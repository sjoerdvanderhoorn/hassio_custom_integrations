"""Human-facing tool labels and bounded, credential-free persisted diagnostics."""
import json
import re
from .ha import redact

LABELS = {
    'report_integration_discovery':'Checking existing integration options',
    'read_integration_files':'Reading integration source files',
    'list_revisions':'Reviewing code history',
    'read_revision_files':'Reading a saved revision',
    'restore_revision':'Restoring a code revision',
    'uninstall_integration': 'Uninstalling the integration',
    'list_integrations': 'Reviewing generated integrations',
    'write_files': 'Updating integration code',
    'generate_integration_icon': 'Designing the integration icon',
    'read_integration_file': 'Reading integration code',
    'validate_integration': 'Checking integration code',
    'deploy_integration': 'Installing integration code',
    'install_integration': 'Installing and configuring the integration',
    'installation_status': 'Checking installation progress',
    'rollback_integration': 'Restoring the previous integration version',
    'list_backups': 'Finding restore points',
    'home_assistant_info': 'Checking Home Assistant availability',
    'registered_entries': 'Checking integration configuration',
    'start_config_flow': 'Configuring the integration',
    'read_integration_logs': 'Reading integration error logs',
    'inspect_entities': 'Checking entities and their current states',
    'reload_config_entry': 'Reconnecting the integration',
    'restart_home_assistant': 'Restarting Home Assistant',
    'wait_for_home_assistant': 'Waiting for Home Assistant to return',
    'test_light_or_switch': 'Testing device control',
}


def public_details(value):
    """Never persist source, config values or credential-bearing fields as tool diagnostics."""
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if re.search(r'password|token|secret|key|auth|credential|content|values|user_input|data_schema|url', k, re.I)
                    else public_details(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [public_details(v) for v in value[:100]]
    if isinstance(value, str):
        return redact(value)[:12000]
    return value
