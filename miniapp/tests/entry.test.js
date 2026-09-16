const assert = require('node:assert')
const { parseEntry, sanitizeStoreCode, extractFromScene } = require('../common/entry')

const RELEASE = { envVersion: 'release', lastStoreCode: '', debugStoreCode: '' }

const cases = [
  ['page direct store_code', () => parseEntry({ store_code: 'disifengshang' }, RELEASE), 'disifengshang'],
  ['app query store_code', () => parseEntry({ query: { store_code: 'a-b_1' } }, RELEASE), 'a-b_1'],
  ['encoded scene', () => parseEntry({ query: { scene: 'store_code%3Ddisifengshang' } }, RELEASE), 'disifengshang'],
  ['raw scene', () => parseEntry({ scene: 'store_code=disifengshang' }, RELEASE), 'disifengshang'],
  ['last visited fallback', () => parseEntry({}, { envVersion: 'release', lastStoreCode: 'lastone', debugStoreCode: '' }), 'lastone'],
  ['debug store in develop', () => parseEntry({}, { envVersion: 'develop', lastStoreCode: '', debugStoreCode: 'disifengshang' }), 'disifengshang'],
  ['debug store in trial', () => parseEntry({}, { envVersion: 'trial', lastStoreCode: '', debugStoreCode: 'disifengshang' }), 'disifengshang'],
  ['debug store ignored in release', () => parseEntry({}, { envVersion: 'release', lastStoreCode: '', debugStoreCode: 'disifengshang' }), ''],
  ['invalid direct rejected', () => parseEntry({ store_code: 'http://evil/x' }, RELEASE), ''],
  ['invalid scene rejected', () => parseEntry({ scene: 'store_code=<script>' }, RELEASE), ''],
  ['sanitize valid', () => sanitizeStoreCode('ok-1_2'), 'ok-1_2'],
  ['sanitize invalid', () => sanitizeStoreCode('bad code'), ''],
  ['extractFromScene', () => extractFromScene('store_code=disifengshang'), 'disifengshang']
]

let failed = 0
for (const [name, run, expected] of cases) {
  try {
    assert.strictEqual(run(), expected)
    console.log('ok -', name)
  } catch (error) {
    failed += 1
    console.error('FAIL -', name, '=>', error.message)
  }
}

if (failed > 0) {
  process.exitCode = 1
} else {
  console.log('entry tests passed')
}
