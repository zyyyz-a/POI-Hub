const api = require('../../common/api')
const util = require('../../common/util')

Page({
  data: { state: 'loading', message: '', product: null, purchasable: true, notice: '' },
  onLoad(options) {
    this.productId = options.id
  },
  onShow() {
    if (!this.data.product || this.data.state !== 'content') this.load()
  },
  async load() {
    const storeCode = getApp().globalData.storeCode
    this.setData({ state: 'loading', message: '' })
    try {
      const [product, store] = await Promise.all([
        api.product(storeCode, this.productId),
        api.store(storeCode)
      ])
      getApp().globalData.store = store
      const purchasable = store.purchasable !== false && store.tradable !== false
      this.setData({
        state: 'content',
        product: util.decorateProduct(product),
        purchasable,
        notice: store.notice || ''
      })
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  buy() {
    if (!this.data.purchasable) {
      wx.showToast({ title: this.data.notice || '门店服务准备中，暂不可购买', icon: 'none' })
      return
    }
    if (this.data.product && this.data.product.stock <= 0) {
      wx.showToast({ title: '该套餐已售罄', icon: 'none' })
      return
    }
    wx.navigateTo({ url: `/pages/order-confirm/index?id=${this.productId}` })
  }
})
