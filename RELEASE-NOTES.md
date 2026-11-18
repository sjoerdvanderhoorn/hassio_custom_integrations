# Version 1.0.3

Changes since published version 1.0.1 (including the improvements previously supplied as local test builds).

## Integration creation and maintenance

- Before creating a new integration, the agent checks for existing integrations and presents matching options. Users can explicitly choose to build their own instead.
- Created or updated integrations are identified by name with a link to their Home Assistant integration page for review.
- The agent can read multiple source files in one call and is instructed to batch related reads and updates.
- Automatic compressed code snapshots preserve staged and installed revisions around changes. The agent can list/read revisions and restore a selected version to staging with explicit approval, including requests such as “go back to yesterday”. Snapshots start after this update and do not include Home Assistant configuration or credentials.

## Chat and reliability

- Compact tool-action rows with SVG disclosure icons, cleaner borders, aligned status labels and inline expandable diagnostics.
- Previous-step groups and individual diagnostics expand independently and retain their own state during refreshes.
- Intermediate agent replies appear as Markdown between tool-action groups in conversation order, without being repeated in the final response.
- Enter sends a message; Shift+Enter and Ctrl+Enter insert a new line. Automatic scrolling follows new messages.
- Faster attachment of the Add integration choice and Edit custom integration controls during navigation and page updates.
- Interrupted agent streams reconnect automatically up to three times, with visible retry notes. If recovery still fails, a Retry button reconnects to the same job and explains that a smaller request may help.
- Recovery preserves completed tool results to avoid repeating actions when acknowledging a result fails.

## Translations

- All native setup and options strings are supplied for the 66 languages in Home Assistant's linked Assist language list, including regional/script variants.
- English remains the canonical strings.json source; translated catalogues use Home Assistant's translations/<language>.json format.
- The embedded chat and extension controls retain their separate English catalogue. Voice-language coverage does not imply that every language is selectable in the Home Assistant interface. Translations are AI-assisted and have not all received native-speaker review.

## Upgrade

Update through HACS or replace /config/custom_components/custom_integrations with the folder from the ZIP. Restart Home Assistant Core and refresh the browser (Ctrl+F5). Existing managed integrations and conversations are retained. Keep normal Home Assistant backups; code snapshots are not full-system backups.
