const api = require('../../common/api')

Page({
  data: { product: null, paying: false },
  onLoad(options) {
    const product = getApp().globalData.products.find(item => item.id === options.id)
    this.setData({ product })
  },
  async buy() {
    if (this.data.paying) return
    this.setData({ paying: true })
    try {
      await getApp().ensureLogin()
      const order = await api.createOrder({
        product_id: this.data.product.id,
        quantity: 1,
        idempotency_key: `wx-${Date.now()}-${Math.random()}`
      })
      const payment = await api.pay(order.id)
      if (payment.payment_parameters?.mock !== 'true') {
        await new Promise((resolve, reject) => wx.requestPayment({ ...payment.payment_parameters, success: resolve, fail: reject }))
      }
      getApp().globalData.currentOrder = payment.order
      wx.navigateTo({ url: `/pages/appointment/index?orderId=${order.id}` })
    } catch (error) {
      wx.showModal({ title: '未完成购买', content: error.message || '请稍后重试', showCancel: false })
    } finally {
      this.setData({ paying: false })
    }
  }
})
