const assert = require('assert')
const { distanceMeters, formatDistance } = require('../common/location')

assert.strictEqual(distanceMeters(33.57, 114.03, null, 114.04), null)
assert.strictEqual(distanceMeters(33.57, 114.03, 33.57, 114.03), 0)
assert.ok(distanceMeters(33.57, 114.03, 33.58, 114.03) > 1000)
assert.strictEqual(formatDistance(0), '100米内')
assert.strictEqual(formatDistance(650), '700米')
assert.strictEqual(formatDistance(1350), '1.4公里')

console.log('location tests passed')
