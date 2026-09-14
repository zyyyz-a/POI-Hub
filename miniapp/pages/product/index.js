const api = require('../../common/api')
const util = require('../../common/util')

Page({
  data: { state: 'loading', message: '', product: null },
  onLoad(options) {
    this.productId = options.id
  },
  onShow() {
    if (!this.data.product) this.load()
  },
  async load() {
    const storeCode = getApp().globalData.storeCode
    this.setData({ state: 'loading', message: '' })
    try {
      const product = util.decorateProduct(await api.product(storeCode, this.productId))
      this.setData({ state: 'content', product })
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  buy() {
    if (this.data.product && this.data.product.stock <= 0) {
      wx.showToast({ title: '该套餐已售罄', icon: 'none' })
      return
    }
    wx.navigateTo({ url: `/pages/order-confirm/index?id=${this.productId}` })
  }
})
