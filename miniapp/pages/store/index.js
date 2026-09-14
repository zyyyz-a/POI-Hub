const api = require('../../common/api')

Page({
  data: { store: null, products: [], blocked: '', loading: true },
  async onShow() {
    try {
      await getApp().ensureLogin()
      const store = await api.store()
      const products = store.tradable ? await api.products() : []
      getApp().globalData.products = products
      this.setData({
        store,
        products,
        loading: false,
        blocked: store.tradable ? '' : (store.blockers || []).join('、')
      })
    } catch (error) {
      this.setData({ loading: false })
      wx.showToast({ title: error.message || '加载失败', icon: 'none' })
    }
  },
  openProduct(event) {
    wx.navigateTo({ url: `/pages/product/index?id=${event.currentTarget.dataset.id}` })
  }
})
