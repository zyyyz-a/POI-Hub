const api = require('../../common/api')
const { extractFromScene } = require('../../common/entry')
const { distanceMeters, formatDistance } = require('../../common/location')

const STATUS_TEXT = { open: '营业中', preparing: '准备中', closed: '暂停营业' }

function codeFromScan(result) {
  const candidates = [result.path, result.scene, result.result, result.rawData]
  for (let index = 0; index < candidates.length; index += 1) {
    const code = extractFromScene(candidates[index])
    if (code) return code
  }
  return ''
}

Page({
  data: {
    state: 'loading',
    message: '',
    stores: [],
    visible: [],
    keyword: '',
    locating: false,
    located: false,
    location: null
  },
  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },
  async load() {
    this.setData({ state: 'loading', message: '' })
    try {
      const result = await api.stores()
      const items = (result && result.items) || result || []
      const stores = items.map(item => Object.assign({}, item, {
        status_text: STATUS_TEXT[item.business_status] || '营业中'
      }))
      this.setData({ stores, state: stores.length ? 'content' : 'empty' })
      this.applyKeyword(this.data.keyword, stores, this.data.location)
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  onKeyword(event) {
    this.applyKeyword(event.detail.value, this.data.stores, this.data.location)
  },
  applyKeyword(keyword, stores, location) {
    const text = String(keyword || '').trim()
    const filtered = text
      ? stores.filter(item => (item.store_name || '').indexOf(text) >= 0)
      : stores
    const visible = filtered.map(item => {
      const distance = location
        ? distanceMeters(location.latitude, location.longitude, item.latitude, item.longitude)
        : null
      return Object.assign({}, item, {
        distance_meters: distance,
        distance_text: distance === null ? '' : formatDistance(distance)
      })
    }).sort((left, right) => {
      if (left.distance_meters === null && right.distance_meters === null) return 0
      if (left.distance_meters === null) return 1
      if (right.distance_meters === null) return -1
      return left.distance_meters - right.distance_meters
    })
    this.setData({ keyword: text, visible })
  },
  locate() {
    if (this.data.locating) return
    this.setData({ locating: true })
    wx.getLocation({
      type: 'gcj02',
      success: location => {
        const current = { latitude: location.latitude, longitude: location.longitude }
        this.setData({ locating: false, located: true, location: current })
        this.applyKeyword(this.data.keyword, this.data.stores, current)
      },
      fail: () => {
        this.setData({ locating: false })
        wx.showToast({ title: '未获得位置权限，仍可浏览全部门店', icon: 'none' })
      }
    })
  },
  choose(event) {
    getApp().confirmedStore(event.currentTarget.dataset.code)
    wx.reLaunch({ url: '/pages/store/index' })
  },
  scan() {
    wx.scanCode({
      success: result => {
        const code = codeFromScan(result)
        if (!code) {
          wx.showToast({ title: '未识别到门店', icon: 'none' })
          return
        }
        getApp().confirmedStore(code)
        wx.reLaunch({ url: '/pages/store/index' })
      },
      fail: () => {}
    })
  }
})
