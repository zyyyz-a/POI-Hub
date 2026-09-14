const api = require('../../common/api')

const MESSAGES = {
  missing: '没有识别到门店入口，请从腾讯地图或门店页面重新进入。',
  invalid: '入口可能已失效或门店正在维护，请稍后再试。'
}

Page({
  data: { reason: '', message: '' },
  onLoad(options) {
    const reason = options.reason || 'invalid'
    this.setData({ reason, message: MESSAGES[reason] || MESSAGES.invalid })
  },
  reload() {
    wx.reLaunch({ url: '/pages/store/index' })
  },
  callService() {
    if (api.customerServicePhone) {
      wx.makePhoneCall({ phoneNumber: api.customerServicePhone })
      return
    }
    wx.showToast({ title: '客服电话暂未配置', icon: 'none' })
  }
})
