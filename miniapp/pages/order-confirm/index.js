const api = require('../../common/api')
const util = require('../../common/util')

Page({
  data: {
    product: null,
    store: null,
    agreed: true,
    paying: false,
    error: ''
  },
  onLoad(options) {
    this.productId = options.id
  },
  async onShow() {
    const app = getApp()
    const store = app.globalData.store
    const product = (app.globalData.products || []).find(item => item.id === this.productId)
    this.setData({ store: store || null, product: product || null })
    if (!product) {
      try {
        this.setData({ product: util.decorateProduct(await api.product(app.globalData.storeCode, this.productId)) })
      } catch (error) {
        this.setData({ error: error.message })
      }
    }
  },
  toggleAgree() {
    this.setData({ agreed: !this.data.agreed })
  },
  async pay() {
    if (this.data.paying) return
    if (!this.data.agreed) {
      wx.showToast({ title: '请先同意退款规则', icon: 'none' })
      return
    }
    const app = getApp()
    const storeCode = app.globalData.storeCode
    this.setData({ paying: true, error: '' })
    try {
      await app.ensureLogin()
      const order = await api.createOrder(storeCode, {
        product_id: this.productId,
        quantity: 1,
        idempotency_key: util.newIdempotencyKey('order')
      })
      app.globalData.currentOrder = order
      this.lastOrderId = order.id
      const payment = await api.pay(storeCode, order.id, {})
      if (payment.payment_parameters && payment.payment_parameters.mock !== 'true') {
        await new Promise((resolve, reject) => {
          wx.requestPayment(Object.assign({}, payment.payment_parameters, { success: resolve, fail: reject }))
        })
      }
      wx.redirectTo({ url: `/pages/pay-result/index?orderId=${order.id}&from=paid` })
    } catch (error) {
      const cancelled = error && error.errMsg && error.errMsg.indexOf('cancel') >= 0
      if (cancelled) {
        wx.redirectTo({ url: `/pages/pay-result/index?orderId=${this.lastOrderId || ''}&from=cancel` })
        return
      }
      this.setData({ error: (error && error.message) || '支付未完成，请稍后重试' })
    } finally {
      this.setData({ paying: false })
    }
  }
})
