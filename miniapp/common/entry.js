const CONFIG = (() => {
  try {
    return require('../config')
  } catch (error) {
    try {
      return require('../config.example')
    } catch (fallbackError) {
      return {}
    }
  }
})()

const STORE_CODE_PATTERN = /^[A-Za-z0-9_-]+$/

function sanitizeStoreCode(value) {
  if (value === undefined || value === null) return ''
  const text = String(value).trim()
  if (!text || !STORE_CODE_PATTERN.test(text)) return ''
  return text
}

function decodeSafe(value) {
  try {
    return decodeURIComponent(value)
  } catch (error) {
    return value
  }
}

function extractFromScene(scene) {
  const text = String(scene === undefined || scene === null ? '' : scene).trim()
  if (!text) return ''
  const decoded = decodeSafe(text)
  const match = decoded.match(/(?:^|&)store_code=([^&]+)/)
  return sanitizeStoreCode(match ? match[1] : decoded)
}

function detectEnvVersion() {
  try {
    const info = wx.getAccountInfoSync()
    return (info && info.miniProgram && info.miniProgram.envVersion) || ''
  } catch (error) {
    return ''
  }
}

function readLastStoreCode() {
  try {
    return wx.getStorageSync('lastStoreCode') || ''
  } catch (error) {
    return ''
  }
}

function parseEntry(options, overrides) {
  const opts = options || {}
  const ctx = overrides || {}
  const envVersion = ctx.envVersion !== undefined ? ctx.envVersion : detectEnvVersion()
  const isDebugEnv = envVersion === 'develop' || envVersion === 'trial' || envVersion === ''
  const debugSource = ctx.debugStoreCode !== undefined ? ctx.debugStoreCode : CONFIG.debugStoreCode
  const debugCode = isDebugEnv ? sanitizeStoreCode(debugSource) : ''
  const lastSource = ctx.lastStoreCode !== undefined ? ctx.lastStoreCode : readLastStoreCode()
  const lastCode = sanitizeStoreCode(lastSource)

  const directSources = [
    opts.store_code,
    opts.storeCode,
    opts.query && (opts.query.store_code || opts.query.storeCode)
  ]
  for (let index = 0; index < directSources.length; index += 1) {
    const code = sanitizeStoreCode(directSources[index])
    if (code) return code
  }

  const sceneSource = (opts.query && opts.query.scene) || opts.scene
  const sceneCode = extractFromScene(sceneSource)
  if (sceneCode) return sceneCode

  if (lastCode) return lastCode
  return debugCode
}

module.exports = { parseEntry, sanitizeStoreCode, extractFromScene }
