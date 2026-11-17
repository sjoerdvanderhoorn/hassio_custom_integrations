# Installation and usage

## Requirements

- Home Assistant 2026.11 or newer, with writable configuration storage.
- An administrator account and network access to OpenAI.
- An OpenAI Platform API key with access to the Agents API and selected model. A ChatGPT subscription alone does not provide an API key.

## Install

In Marketplace/HACS, add `https://github.com/sjoerdvanderhoorn/hassio_custom_integrations` as a custom repository of type **Integration** if it is not already listed. Install Custom Integrations and restart Home Assistant Core. Under **Settings → Devices & services → Add integration**, select **Custom Integrations** and enter your API key and model. Refresh the browser.

For manual installation, download a release ZIP and copy `custom_components/custom_integrations` into your configuration's `custom_components` directory. Check that `<config>/custom_components/custom_integrations/manifest.json` exists, restart Core, and complete the same setup flow.

The repository identifier is `hassio_custom_integrations`; the Home Assistant domain/folder is `custom_integrations`. No sidebar panel is registered. The UI and management API are administrator-only.

## Create and manage integrations

On the integration overview, **Add integration** opens a choice. **Create custom integration** opens the AI chat. **Select from existing brands** opens Home Assistant's normal brand selector. Describe the device, information or behavior you need; documentation and existing libraries help the agent research an implementation.

Code is staged and validated before deployment. Newly generated integrations receive matching artwork. Deployment can require a Core restart, followed by setup and entity verification. The agent provides a How to test checklist with expected results. Home Assistant reports are not physical confirmation: check the actual device where appropriate.

Installed/configured integrations appear in the normal overview. A sparkle marks integrations managed by this tool. On a managed integration's detail page, **Edit custom integration** opens its chat. Use the conversation selector to open previous chats or start another. The issue/device/capability suggestions prefill the composer. Native Add entry/device controls remain available when the integration supports them.

The composer grows with your text. Enter adds a line; Ctrl+Enter or Shift+Enter sends. You can send a follow-up while an agent that supports steering is working. **Stop** blocks further local actions and requests remote cancellation. Escape closes either popup. Closing a chat keeps the agent working.

If source is staged but not installed/configured, ask the agent in a creation chat to inspect and continue its domain. Only named managed integrations retain discoverable related conversations; abandoned drafts do not appear as integration entries.

## Options and approvals

Configure the model, **Automatically approve code deployment**, and **Automatically approve Core restarts** through the native options flow. Automatic approvals are off by default. Device tests and uninstall always require explicit approval. Leave the replacement API-key field empty to keep the current key.

Enter device credentials in Home Assistant's native setup forms, not in chat. API keys and options are stored through HA's config-entry system. Protect configuration files and backups.

## Upload, share and uninstall

**Or upload an existing integration** opens a ZIP picker. An archive must contain exactly one named integration manifest and `__init__.py`, directly or inside an integration/custom_components/repository folder. Upload stages code only; it does not execute, install dependencies or deploy it. Existing domains are never overwritten.

Limits are 2 MB uploaded, 1.5 MB expanded, 160 KB per file and 1,000 archive entries. Accepted files are Python, JSON, YAML, Markdown/text and supported brand PNGs. Unsafe paths, links, encrypted ZIPs, duplicate paths, multiple manifests and unsupported files are rejected. Review validation findings before installing imported code.

The Edit split menu offers **Share** and **Uninstall**. Share downloads a code ZIP, preferring installed managed code over staging. It excludes runtime caches, ownership markers, chats, options and HA config entries. Check for hardcoded secrets and license obligations before sharing. A code ZIP is not a complete configuration backup or an automatic Marketplace publication package.

Uninstall requires confirmation. It backs up code, cancels queued installation plans, removes managed config entries/associated entities and then removes source/staging files. If entry removal fails, source is preserved; partial entry removal is not automatically reversed. Chats and backups remain. Remove references in YAML, scripts, automations and dashboards yourself. Restart Core to finish unloading removed code. Use a full HA backup to recover credentials/configuration entries. Historical-data retention follows HA's behavior.

Upload, Share and menu-based Uninstall require an idle agent. Unmanaged installed integrations are not adopted silently. This manager and built-in Core integration domains are protected.

## Data, restarts and troubleshooting

Chat history, staged source, installation records and code backups live in `<config>/.storage/custom_integrations/`. Preserve this directory and generated integration folders when updating. For updates, install the release, restart Core and hard-refresh the browser. Restore a matching full HA backup for rollback; do not edit HA's config-entry storage manually.

A Core restart interrupts the local chat task. Installation progress is persisted and checked after startup; uncertain actions are not automatically replayed. Send a message to continue an interrupted discussion. Remote cancellation is best effort, so network failure can leave remote work/billing active until the session settles.

Integration error inspection reads HA's bounded `system_log` warning/error buffer, filtered to the managed integration with best-effort redaction. Compact agent activity is logged under `custom_components.custom_integrations.actions` without intentionally logging entire prompts or API calls. Inspect Settings → System → Logs when setup or UI loading fails.

If controls are missing, verify that the config entry is loaded, use an administrator account, and hard-refresh the browser. The UI attaches to internal settings-page elements. When the backend is unavailable, the ordinary Add integration action remains available.

## Privacy and limitations

The chat runs in a same-origin modal frame and uses the signed-in administrator's HA authentication. Static assets contain no credentials; access tokens are not put in URLs or browser storage. Config/options use HA translation files; the chat has an English catalogue/fallback and additional controls are English.

Prompts, recent conversation context and returned tool results can be sent to OpenAI. Hosted research/browsing and API usage can incur charges. The integration does not silently substitute another API or model if access is unavailable.

Generated Python runs with Core permissions. Static checks, explicit approvals and backups reduce accidents; they do not prove code safe. Review source, use trusted administrators, and test new integrations on a disposable HA instance before relying on them.
