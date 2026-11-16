export const ASSISTANT_HELP_EVENT = 'poi-assistant-help'

export function askAboutField(field: string, label: string) {
  window.dispatchEvent(new CustomEvent(ASSISTANT_HELP_EVENT, { detail: { field, label } }))
}
