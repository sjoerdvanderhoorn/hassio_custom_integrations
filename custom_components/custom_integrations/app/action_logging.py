"""Compact app-console events, deliberately excluding prompts, arguments and results."""
import logging

logger = logging.getLogger('custom_components.custom_integrations.actions')
logger.setLevel(logging.INFO)
logger.propagate = True

HOSTED_LABELS = {
    'web_search_call':'Searching web documentation', 'computer_use_call':'Using the research browser',
    'command_execution':'Running a hosted research command', 'mcp_call':'Calling a connected research tool',
    'create_subagent_call':'Starting a hosted helper', 'wait_for_subagents_call':'Waiting for hosted helpers',
    'send_subagent_input_call':'Guiding a hosted helper', 'interrupt_subagent_call':'Interrupting a hosted helper',
    'close_subagent_call':'Closing a hosted helper', 'resume_subagent_call':'Resuming a hosted helper',
}
