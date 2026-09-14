const api = require('./common/api')
const { parseEntry } = require('./common/entry')

App({
  globalData: {
    accessToken: '',
    storeCode: '',
    store: null,
    products: [],
    currentOrder: null
  },
  onLaunch(options) {
    const storeCode = parseEntry(options)
    this.globalData.storeCode = storeCode
    if (storeCode) {
      try {
        wx.setStorageSync('lastStoreCode', storeCode)
      } catch (error) {
        // storage is best-effort only
      }
    }
  },
  ensureLogin() {
    if (this.globalData.accessToken) return Promise.resolve(this.globalData.accessToken)
    if (this.loginPromise) return this.loginPromise
    this.loginPromise = new Promise((resolve, reject) => {
      if (!this.globalData.storeCode) {
        reject(new Error('门店入口缺失，请从门店页面重新进入'))
        return
      }
      wx.login({
        success: async ({ code }) => {
          try {
            const result = await api.login(code, this.globalData.storeCode)
            this.globalData.accessToken = result.access_token
            resolve(result.access_token)
          } catch (error) {
            this.loginPromise = null
            reject(error)
          }
        },
        fail: () => {
          this.loginPromise = null
          reject(new Error('微信登录失败，请稍后重试'))
        }
      })
    })
    return this.loginPromise
  }
})
