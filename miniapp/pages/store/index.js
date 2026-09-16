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
    const app = getApp()
    const storeCode = parseEntry(options) || app.globalData.storeCode
    app.applyStoreCode(storeCode)
    this.setData({ storeCode })
  },
  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },
  goStorePicker() {
    wx.reLaunch({ url: '/pages/store-picker/index' })
  },
  async load() {
    const storeCode = this.data.storeCode || getApp().globalData.storeCode
    if (!storeCode) {
      this.goStorePicker()
      return
    }
    this.setData({ state: 'loading', message: '' })
    try {
      const store = await api.store(storeCode)
      getApp().confirmedStore(store.store_code || storeCode)
      let products = []
      try {
        products = (await api.products(storeCode)).map(util.decorateProduct)
      } catch (error) {
        products = []
      }
      getApp().globalData.store = store
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
        getApp().clearStore()
        this.setData({ storeCode: '' })
        wx.showToast({ title: '门店入口无效', icon: 'none' })
        setTimeout(() => this.goStorePicker(), 800)
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
