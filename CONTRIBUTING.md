# Contributing

## Development

Use Python 3.13+ for the isolated tests. Install `requirements-test.txt`, set `PYTHONPATH=custom_components/custom_integrations`, and run:

```sh
python -m pytest tests -q -rs
playwright install --with-deps chromium
python tests/browser_marketplace.py
```

Set `BROWSER_EXECUTABLE` to use an existing Chromium-based browser. Set `UI_PREVIEW_DIR` to choose the screenshot directory. Backend tests use HTTP mocks and explicit HA test doubles. Browser tests exercise the actual frontend assets against simulated HA shadow DOM; they do not replace runtime testing in Home Assistant.

Run the official source validator:

```sh
docker run --rm -v "$PWD:/github/workspace:ro" ghcr.io/home-assistant/hassfest
```

The GitHub workflow runs tests, browser checks, hassfest and HACS validation. All checks should pass without ignored rules.

## Architecture

`custom_components/custom_integrations` contains the config/options flow, authenticated HA API bridge, worker adapter, agent engine and bundled frontend. Blocking agent/filesystem work runs off the HA event loop. The settings-page adapter captures the overview Add integration action and attaches managed-integration controls/badges. Keep native brand selection, Add entry/device behavior and the unavailable-backend fallback working.

Preserve administrator authorization, path/archive boundaries, code backups, explicit device/uninstall approvals, restart recovery, scoped log access and protection for built-in domains. Never commit keys, user chats, device configuration or runtime storage. Keep English strings/catalogues and native translation files consistent.

## Release

Update the manifest and const.py versions together. Verify backend/browser tests and official validators. Test installation/options, UI attachment, native actions, approved generation/update/removal, Core restart/recovery and non-admin access on a disposable HA instance. A main-branch commit whose message begins with `Release `, or a manual validation workflow run, publishes the versioned GitHub release with a source ZIP and checksum after every validation job passes. Existing releases on a different commit are preserved; increment the version for another release. Marketplace catalog acceptance is an external review; a passing source validator is not runtime certification.

The public repository must have a description, topics, issues enabled, README and license. Follow the [catalog guide](https://contributors.home-assistant.io/marketplace/guides/catalog/) and [repository requirements](https://contributors.home-assistant.io/marketplace/reference/repository-structure/) before a catalog submission.
