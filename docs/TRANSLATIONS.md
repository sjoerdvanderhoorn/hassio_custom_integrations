# Translations

Native integration setup/options, errors and abort messages use Home Assistant's translation loader. `strings.json` is the canonical English source; `translations/en.json` mirrors it. Every language catalogue has the same keys. The product name Custom Integrations is unchanged across locales.

This release supplies the 66 language codes from the [Assist language list](https://contributors.home-assistant.io/translate/voice/languages/#languages), checked on 18 November 2026. That list concerns voice intents, not Home Assistant's interface languages. A catalogue is used when Home Assistant requests its matching locale; shipping a catalogue does not register a new interface language. Regional and script filenames preserve the reference codes.

The embedded chat iframe has its own English catalogue. These native catalogues do not translate chat/extension controls, backend diagnostics, generated integration code, or model replies. The AI can respond in the user's language, but replies are generated rather than catalogue strings.

Translations are AI-assisted and have not all received native-speaker review. Corrections are welcome: edit the appropriate JSON catalogue, preserve keys and placeholders, and run the translation tests. Do not put multiple languages inside strings.json or silently replace untranslated prose with English.

## Included language codes

`af`, `ar`, `bg`, `bn`, `ca`, `cs`, `cy`, `da`, `de`, `de-CH`, `el`, `en`, `es`, `et`, `eu`, `fa`, `fi`, `fr`, `ga`, `gl`, `gu`, `he`, `hi`, `hr`, `hu`, `hy`, `id`, `is`, `it`, `ja`, `ka`, `kn`, `ko`, `kw`, `lb`, `lt`, `lv`, `ml`, `mn`, `mr`, `ms`, `nb`, `ne`, `nl`, `pa`, `pl`, `pt`, `pt-BR`, `ro`, `ru`, `sk`, `sl`, `sr`, `sr-Latn`, `sv`, `sw`, `ta`, `te`, `th`, `tr`, `uk`, `ur`, `vi`, `zh-CN`, `zh-HK`, `zh-TW`
