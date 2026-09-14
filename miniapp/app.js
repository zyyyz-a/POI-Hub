const api = require('./common/api')

function defaultStoreCode() {
  try {
    return require('./config').storeCode || ''
  } catch (error) {
    return require('./config.example').storeCode || ''
  }
}

function parseStoreCode(options) {
  const query = (options && options.query) || {}
  if (query.store_code) return String(query.store_code)
  if (query.scene) {
    const scene = decodeURIComponent(String(query.scene))
    const match = scene.match(/(?:^|&)store_code=([^&]+)/)
    return match ? match[1] : scene
  }
  return defaultStoreCode()
}

App({
  globalData: { accessToken: '', storeCode: '', products: [], currentOrder: null },
  onLaunch(options) {
    this.globalData.storeCode = parseStoreCode(options)
    wx.login({
      success: async ({ code }) => {
        try {
          const result = await api.login(code)
          this.globalData.accessToken = result.access_token
          if (this.loginReady) this.loginReady(result.access_token)
        } catch (error) {
          wx.showModal({ title: '登录失败', content: error.message || '请稍后重试', showCancel: false })
        }
      }
    })
  },
  ensureLogin() {
    if (this.globalData.accessToken) return Promise.resolve(this.globalData.accessToken)
    return new Promise(resolve => { this.loginReady = resolve })
  }
})
