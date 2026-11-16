import { describe, expect, it } from 'vitest'
import { normalizeApplymentFields, normalizeSettlementAccount } from '../src/common/settlementAccount'

describe('settlement account formatting', () => {
  it('removes formatting spaces while preserving every digit including leading zeroes', () => {
    expect(normalizeSettlementAccount(' 0012 3456\u00a07890\u30001234\t')).toBe('0012345678901234')
  })
  it('does not guess masked, hyphenated or letter-containing accounts', () => {
    expect(normalizeSettlementAccount('6222 **** 2213')).toBe('6222****2213')
    expect(normalizeSettlementAccount('6222-0000-2213')).toBe('6222-0000-2213')
    expect(normalizeSettlementAccount('6222 ABC 2213')).toBe('6222ABC2213')
  })
  it('normalizes saved legacy fields only in a copy for an explicit save', () => {
    const fields = { account_number: '0012 3456 7890', merchant_name: 'Example Store', owner_name: 'A B' }
    expect(normalizeApplymentFields(fields)).toEqual({ ...fields, account_number: '001234567890' })
    expect(fields.account_number).toBe('0012 3456 7890')
  })
})
