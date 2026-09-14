function decodeScene(scene) {
  try {
    return decodeURIComponent(scene)
  } catch (error) {
    return scene
  }
}

function parseEntry(options) {
  const query = (options && options.query) || {}
  if (query.store_code) return String(query.store_code)
  if (query.scene) {
    const scene = decodeScene(String(query.scene))
    const match = scene.match(/(?:^|&)store_code=([^&]+)/)
    return match ? match[1] : scene
  }
  try {
    return wx.getStorageSync('lastStoreCode') || ''
  } catch (error) {
    return ''
  }
}

function entryParams(options) {
  return {
    store_code: parseEntry(options)
  }
}

module.exports = { parseEntry, entryParams }
