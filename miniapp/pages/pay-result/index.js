const api = require('../../common/api')
const util = require('../../common/util')

Page({
  data: { state: 'confirming', order: null, message: '' },
  onLoad(options) {
    this.orderId = options.orderId
    this.from = options.from || ''
  },
  onShow() {
    if (!this.orderId) {
      this.setData({ state: 'cancel', order: null })
      return
    }
    this.poll(0)
  },
  onUnload() {
    if (this.timer) clearTimeout(this.timer)
  },
  async poll(attempt) {
    const storeCode = getApp().globalData.storeCode
    try {
      const order = util.decorateOrder(await api.getOrder(storeCode, this.orderId))
      getApp().globalData.currentOrder = order
      if (['paid', 'partially_refunded', 'refunded'].includes(order.status)) {
        this.setData({ state: 'success', order })
        return
      }
      if (['expired', 'closed'].includes(order.status)) {
        this.setData({ state: 'closed', order })
        return
      }
      if (order.status === 'payment_pending' && attempt < 5) {
        this.timer = setTimeout(() => this.poll(attempt + 1), 1500)
        return
      }
      this.setData({ state: 'pending', order })
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  refresh() {
    this.poll(0)
  },
  goAppointment() {
    wx.navigateTo({ url: `/pages/appointment/index?orderId=${this.orderId}` })
  },
  goVoucher() {
    wx.navigateTo({ url: `/pages/voucher/index?orderId=${this.orderId}` })
  },
  goOrderDetail() {
    wx.navigateTo({ url: `/pages/order-detail/index?orderId=${this.orderId}` })
  },
  goOrders() {
    wx.switchTab({ url: '/pages/orders/index' })
  }
})
