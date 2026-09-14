const api = require('../../common/api')

const USER_AGREEMENT = '本小程序仅提供到店服务的预约与购买。使用前请确认门店、套餐和退款规则。'
const PRIVACY_POLICY = '我们仅在必要时收集手机号和位置信息，用于预约和到店导航，不会向无关第三方提供。'

Page({
  data: {
    customerServicePhone: api.customerServicePhone,
    version: '1.0.0'
  },
  openOrders() {
    wx.switchTab({ url: '/pages/orders/index' })
  },
  callCustomerService() {
    if (this.data.customerServicePhone) {
      wx.makePhoneCall({ phoneNumber: this.data.customerServicePhone })
      return
    }
    wx.showToast({ title: '客服电话暂未配置', icon: 'none' })
  },
  showAgreement() {
    wx.showModal({ title: '用户协议', content: USER_AGREEMENT, showCancel: false })
  },
  showPrivacy() {
    wx.showModal({ title: '隐私政策', content: PRIVACY_POLICY, showCancel: false })
  },
  requestDeletion() {
    wx.showModal({
      title: '注销 / 个人信息处理',
      content: '如需注销账号或处理个人信息，请通过客服电话联系我们。',
      confirmText: '联系客服',
      success: result => {
        if (result.confirm) this.callCustomerService()
      }
    })
  }
})
