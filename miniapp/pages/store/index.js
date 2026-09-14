const api = require('../../common/api')

Page({
  data: { products: [], loading: true },
  async onShow() {
    try {
      await getApp().ensureLogin()
      const products = await api.products()
      getApp().globalData.products = products
      this.setData({ products, loading: false })
    } catch (error) {
      this.setData({ loading: false })
      wx.showToast({ title: error.message || '加载失败', icon: 'none' })
    }
  },
  openProduct(event) {
    wx.navigateTo({ url: `/pages/product/index?id=${event.currentTarget.dataset.id}` })
  }
})
