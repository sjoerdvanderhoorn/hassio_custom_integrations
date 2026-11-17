# Custom Integrations

**The last integration you should ever need to develop.**

Tell Home Assistant what you need. Custom Integrations uses an AI agent to research, write, install and improve integrations through a conversation—right inside Home Assistant. Connect an unfamiliar device, turn a website into a sensor, or combine several sources into one useful entity.

## What can you build?

- A parcel tracker with delivery updates and an estimated arrival time.
- Sensors for your municipality's collection schedules or local announcements.
- School calendars and notices that fit into your home routines.
- Support for a lamp, appliance or other device without an existing integration.
- One entity that combines information from several devices, APIs or websites.

Describe the outcome, share documentation or a Python library, and let the agent work out the implementation. Add another device, request a new capability, or describe a problem to refine it later. What can be built depends on the available interfaces, data and hardware.

## How it works

Click **Add integration**, then **Create custom integration**. The agent prepares code, explains its actions and asks for approval where required. It can inspect entity states and integration errors, help test supported device actions, and suggest checks you can perform yourself.

Your integrations appear in Home Assistant's normal integration list. Open one and choose **Edit custom integration** to continue the conversation. Previous chats remain available; the dropdown offers **Share** and **Uninstall**. Home Assistant's normal setup and Add entry/device controls remain available where supported.

## The bigger idea

The ambition is to make integration development disappear as a separate task. “I have a new lamp—please add it” should be enough: reuse an existing connection when possible, extend it when needed, and create something new when nothing fits.

In that future, dashboards can be generated dynamically around what you want to see. Home Assistant's enduring foundation becomes its historical-state and statistics database: the record that lets you compare heat-pump efficiency across outdoor temperatures, understand appliance energy use, or see when an alarm was triggered. Describe the devices, information and experiences you want; let software build the connections and interfaces around them.

That is the direction. This release creates and maintains custom integrations; automatic orchestration of every existing integration and dynamic dashboard generation are part of the vision, not shipped features.

## Get started

Requires **Home Assistant 2026.11+**, an administrator account and an **OpenAI Platform API key**. New installations default to `gpt-6.1-sol`.

Install `sjoerdvanderhoorn/hassio_custom_integrations` as an **Integration** repository in Marketplace/HACS, restart Home Assistant, then add **Custom Integrations** under Settings → Devices & services. Manual installation is also supported.

See [Installation and usage](docs/USAGE.md) for setup, controls and permissions, and [Contributing](CONTRIBUTING.md) for development.

Generated code runs with Home Assistant permissions. Review changes and keep backups. Agent/API usage can incur costs; prompts and tool results may be sent to OpenAI. The settings-page enhancements depend on Home Assistant's internal frontend structure and may require updates as HA changes.

[MIT license](LICENSE)
