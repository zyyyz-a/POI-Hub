const api = require('../../common/api')
const util = require('../../common/util')
const { parseEntry } = require('../../common/entry')

Page({
  data: {
    state: 'loading',
    message: '',
    store: null,
    products: [],
    purchasable: false,
    notice: '',
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
      let products = []
      try {
        products = (await api.products(storeCode)).map(util.decorateProduct)
      } catch (error) {
        products = []
      }
      getApp().globalData.products = products
      this.setData({
        state: 'content',
        store,
        products,
        purchasable: store.purchasable !== false && store.tradable !== false,
        notice: store.notice || ''
      })
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
    const phone = store && (store.public_phone || '')
    if (!phone || phone.includes('*')) {
      wx.showToast({ title: '电话暂未公开，请咨询客服', icon: 'none' })
      return
    }
    wx.makePhoneCall({ phoneNumber: phone })
  },
  previewImage(event) {
    const urls = this.data.store.environment_images || []
    if (!urls.length) return
    wx.previewImage({ current: event.currentTarget.dataset.url, urls })
  }
})
