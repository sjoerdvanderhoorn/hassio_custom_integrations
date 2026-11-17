"""Administrator setup and options in Home Assistant's native config flow."""
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import TextSelector,TextSelectorConfig,TextSelectorType
try:
    import probatio as vol
except ImportError:
    import voluptuous as vol
from .const import DOMAIN

def schema(values=None,include_key=True):
    values=values or {}
    fields={vol.Required('model',default=values.get('model','gpt-6.1-sol')):str,
            vol.Required('auto_deploy',default=values.get('auto_deploy',False)):bool,
            vol.Required('auto_restart',default=values.get('auto_restart',False)):bool}
    key=vol.Required('openai_api_key') if include_key else vol.Optional('openai_api_key')
    fields[key]=TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
    return vol.Schema(fields)

class CustomIntegrationsFlow(config_entries.ConfigFlow,domain=DOMAIN):
    VERSION=1
    async def async_step_user(self,user_input=None):
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors={}
        if user_input is not None:
            if not user_input.get('openai_api_key','').strip():errors['base']='missing_key'
            elif not user_input.get('model','').strip():errors['base']='missing_model'
            else:return self.async_create_entry(title='Custom Integrations',data=user_input)
        return self.async_show_form(step_id='user',data_schema=schema(user_input),errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):return CustomIntegrationsOptions()

class CustomIntegrationsOptions(config_entries.OptionsFlow):
    async def async_step_init(self,user_input=None):
        if user_input is not None:
            # Empty password means retain existing key, never render it as a proposed value.
            values={**self.config_entry.options,**user_input}
            if not user_input.get('openai_api_key','').strip():
                values.pop('openai_api_key',None)
                if self.config_entry.options.get('openai_api_key'):values['openai_api_key']=self.config_entry.options['openai_api_key']
            if not values.get('model','').strip():
                return self.async_show_form(step_id='init',data_schema=schema(values,False),errors={'base':'missing_model'})
            return self.async_create_entry(title='',data=values)
        return self.async_show_form(step_id='init',data_schema=schema({**self.config_entry.data,**self.config_entry.options},False))
