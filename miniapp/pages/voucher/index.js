const api = require('../../common/api')
const util = require('../../common/util')

Page({
  data: { state: 'loading', message: '', voucher: null, code: '', store: null },
  onLoad(options) {
    this.orderId = options.orderId
  },
  onShow() {
    this.load()
  },
  async load() {
    this.setData({ state: 'loading', message: '' })
    try {
      await getApp().ensureLogin()
      const result = await api.voucher(getApp().globalData.storeCode, this.orderId)
      this.setData({
        state: 'content',
        voucher: util.decorateVoucher(result.voucher),
        code: result.code,
        store: getApp().globalData.store
      })
    } catch (error) {
      if (error.status === 409 || error.status === 404) {
        this.setData({ state: 'blocked', message: error.message })
        return
      }
      this.setData({ state: 'error', message: error.message })
    }
  },
  copyCode() {
    if (!this.data.code) return
    wx.setClipboardData({ data: this.data.code })
  },
  goOrders() {
    wx.switchTab({ url: '/pages/orders/index' })
  }
})
