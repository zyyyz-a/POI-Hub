const api = require('../../common/api')
const util = require('../../common/util')
const { parseEntry } = require('../../common/entry')

Page({
  data: {
    state: 'loading',
    message: '',
    store: null,
    products: [],
    blocked: '',
    storeCode: ''
  },
  onLoad(options) {
    const storeCode = parseEntry(options) || getApp().globalData.storeCode
    getApp().globalData.storeCode = storeCode
    this.setData({ storeCode })
  },
  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },
  async load() {
    const storeCode = this.data.storeCode
    if (!storeCode) {
      wx.redirectTo({ url: '/pages/entry-error/index?reason=missing' })
      return
    }
    this.setData({ state: 'loading', message: '' })
    try {
      const store = await api.store(storeCode)
      getApp().globalData.store = store
      if (!store.tradable) {
        const blocked = (store.blockers || []).join('、')
        this.setData({ state: 'blocked', store, blocked, message: blocked })
        return
      }
      const products = (await api.products(storeCode)).map(util.decorateProduct)
      getApp().globalData.products = products
      this.setData({ state: products.length ? 'content' : 'empty', store, products })
    } catch (error) {
      if (error.status === 404) {
        wx.redirectTo({ url: '/pages/entry-error/index?reason=invalid' })
        return
      }
      this.setData({ state: 'error', message: error.message })
    }
  },
  openProduct(event) {
    wx.navigateTo({ url: `/pages/product/index?id=${event.currentTarget.dataset.id}` })
  },
  openLocation() {
    const store = this.data.store
    if (!store || !store.latitude || !store.longitude) {
      wx.showToast({ title: '暂无门店坐标', icon: 'none' })
      return
    }
    wx.openLocation({
      latitude: store.latitude,
      longitude: store.longitude,
      name: store.store_name,
      address: store.address
    })
  },
  callStore() {
    const store = this.data.store
    if (!store || !store.contact_phone_masked || store.contact_phone_masked.includes('*')) {
      wx.showToast({ title: '电话未公开，请咨询客服', icon: 'none' })
      return
    }
    wx.makePhoneCall({ phoneNumber: store.contact_phone_masked })
  }
})
