const api = require('../../common/api')

Page({
  data: { orderId: '', date: '', time: '10:00', contactName: '', contactPhone: '', note: '' },
  onLoad(options) { this.setData({ orderId: options.orderId }) },
  setDate(event) { this.setData({ date: event.detail.value }) },
  setTime(event) { this.setData({ time: event.detail.value }) },
  field(event) { this.setData({ [event.currentTarget.dataset.name]: event.detail.value }) },
  async submit() {
    try {
      await api.appoint(this.data.orderId, {
        starts_at: `${this.data.date}T${this.data.time}:00+08:00`,
        contact_name: this.data.contactName,
        contact_phone: this.data.contactPhone,
        note: this.data.note
      })
      wx.navigateTo({ url: `/pages/voucher/index?orderId=${this.data.orderId}` })
    } catch (error) {
      wx.showToast({ title: error.message || '预约失败', icon: 'none' })
    }
  }
})
