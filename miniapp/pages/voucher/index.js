const api = require('../../common/api')

Page({
  data: { code: '', voucher: null },
  async onLoad(options) {
    try {
      const result = await api.voucher(options.orderId)
      this.setData(result)
    } catch (error) {
      wx.showToast({ title: error.message || '券码加载失败', icon: 'none' })
    }
  }
})
