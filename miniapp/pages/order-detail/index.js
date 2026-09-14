const api = require('../../common/api')
const util = require('../../common/util')

const REFUNDABLE = ['paid', 'partially_refunded']

Page({
  data: { state: 'loading', message: '', order: null, paying: false, canRefund: false },
  onLoad(options) {
    this.orderId = options.orderId
    this.autoPay = options.pay === '1'
  },
  onShow() {
    this.load()
  },
  async load() {
    this.setData({ state: 'loading', message: '' })
    try {
      const order = util.decorateOrder(await api.getOrder(getApp().globalData.storeCode, this.orderId))
      this.setData({
        state: 'content',
        order,
        canRefund: REFUNDABLE.includes(order.status)
      })
      if (this.autoPay) {
        this.autoPay = false
        this.pay()
      }
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  async pay() {
    if (this.data.paying) return
    const storeCode = getApp().globalData.storeCode
    this.setData({ paying: true })
    try {
      await getApp().ensureLogin()
      const payment = await api.pay(storeCode, this.orderId, {})
      if (payment.payment_parameters && payment.payment_parameters.mock !== 'true') {
        await new Promise((resolve, reject) => {
          wx.requestPayment(Object.assign({}, payment.payment_parameters, { success: resolve, fail: reject }))
        })
      }
      wx.redirectTo({ url: `/pages/pay-result/index?orderId=${this.orderId}&from=paid` })
    } catch (error) {
      const cancelled = error && error.errMsg && error.errMsg.indexOf('cancel') >= 0
      if (!cancelled) util.toastError(error)
    } finally {
      this.setData({ paying: false })
    }
  },
  goAppointment() {
    wx.navigateTo({ url: `/pages/appointment/index?orderId=${this.orderId}` })
  },
  goVoucher() {
    wx.navigateTo({ url: `/pages/voucher/index?orderId=${this.orderId}` })
  },
  goRefund() {
    wx.navigateTo({ url: `/pages/refund/index?orderId=${this.orderId}` })
  }
})
