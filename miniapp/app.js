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
    this.applyStoreCode(parseEntry(options))
  },
  resetStoreState() {
    this.globalData.accessToken = ''
    this.globalData.store = null
    this.globalData.products = []
    this.globalData.currentOrder = null
    this.loginPromise = null
  },
  applyStoreCode(code) {
    const next = code || ''
    if (next && next !== this.globalData.storeCode) this.resetStoreState()
    this.globalData.storeCode = next
    return next
  },
  confirmedStore(code) {
    const next = code || ''
    if (!next) return
    if (next !== this.globalData.storeCode) this.resetStoreState()
    this.globalData.storeCode = next
    try {
      wx.setStorageSync('lastStoreCode', next)
    } catch (error) {
      // storage is best-effort only
    }
  },
  clearStore() {
    this.resetStoreState()
    this.globalData.storeCode = ''
    try {
      wx.removeStorageSync('lastStoreCode')
    } catch (error) {
      // storage is best-effort only
    }
  },
  ensureLogin() {
    if (this.globalData.accessToken) return Promise.resolve(this.globalData.accessToken)
    if (this.loginPromise) return this.loginPromise
    this.loginPromise = new Promise((resolve, reject) => {
      if (!this.globalData.storeCode) {
        reject(new Error('请先选择门店'))
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
