const api = require('../../common/api')
const { extractFromScene } = require('../../common/entry')

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
  data: { state: 'loading', message: '', stores: [], visible: [], keyword: '' },
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
      this.applyKeyword(this.data.keyword, stores)
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  onKeyword(event) {
    this.applyKeyword(event.detail.value, this.data.stores)
  },
  applyKeyword(keyword, stores) {
    const text = String(keyword || '').trim()
    const visible = text
      ? stores.filter(item => (item.store_name || '').indexOf(text) >= 0)
      : stores
    this.setData({ keyword: text, visible })
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
