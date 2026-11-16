// Formatting only: never infer, replace, truncate, or add an account digit.
export function normalizeSettlementAccount(value: string): string {
  return value.replace(/\s/g, '')
}

export function normalizeApplymentFields(fields: Record<string, unknown>): Record<string, unknown> {
  return typeof fields.account_number === 'string'
    ? { ...fields, account_number: normalizeSettlementAccount(fields.account_number) }
    : { ...fields }
}
