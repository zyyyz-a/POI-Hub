const api = require('../../common/api')
const util = require('../../common/util')

Page({
  data: {
    state: 'loading',
    message: '',
    order: null,
    reason: '',
    submitting: false,
    error: '',
    done: false
  },
  onLoad(options) {
    this.orderId = options.orderId
  },
  onShow() {
    if (!this.data.done) this.load()
  },
  async load() {
    this.setData({ state: 'loading', message: '' })
    try {
      const order = util.decorateOrder(await api.getOrder(getApp().globalData.storeCode, this.orderId))
      this.setData({ state: 'content', order })
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  field(event) {
    this.setData({ reason: event.detail.value })
  },
  async submit() {
    if (this.data.submitting) return
    this.setData({ submitting: true, error: '' })
    try {
      await getApp().ensureLogin()
      await api.refund(getApp().globalData.storeCode, this.orderId, {
        reason: this.data.reason,
        idempotency_key: util.newIdempotencyKey('refund')
      })
      this.setData({ done: true })
    } catch (error) {
      this.setData({ error: error.message || '退款申请失败' })
    } finally {
      this.setData({ submitting: false })
    }
  },
  goOrders() {
    wx.switchTab({ url: '/pages/orders/index' })
  }
})
