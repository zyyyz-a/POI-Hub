const api = require('./common/api')

App({
  globalData: { accessToken: '', products: [], currentOrder: null },
  onLaunch() {
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
