const api = require('../../common/api')

const TIMES = ['09:00', '10:00', '11:00', '13:00', '14:00', '15:00', '16:00', '17:00', '18:00', '19:00']

function nextDays(count) {
  const days = []
  const now = new Date()
  for (let index = 0; index < count; index += 1) {
    const date = new Date(now.getTime() + index * 86400000)
    const month = date.getMonth() + 1
    const day = date.getDate()
    days.push({
      value: `${date.getFullYear()}-${`${month}`.padStart(2, '0')}-${`${day}`.padStart(2, '0')}`,
      label: index === 0 ? '今天' : index === 1 ? '明天' : `${month}月${day}日`
    })
  }
  return days
}

Page({
  data: {
    orderId: '',
    days: [],
    day: '',
    times: TIMES,
    time: TIMES[0],
    name: '',
    phone: '',
    note: '',
    submitting: false,
    error: '',
    done: false,
    order: null
  },
  onLoad(options) {
    const days = nextDays(7)
    this.setData({ orderId: options.orderId || '', days, day: days[0].value })
  },
  selectDay(event) {
    this.setData({ day: event.currentTarget.dataset.value })
  },
  selectTime(event) {
    this.setData({ time: event.currentTarget.dataset.value })
  },
  field(event) {
    this.setData({ [event.currentTarget.dataset.name]: event.detail.value })
  },
  async submit() {
    if (this.data.submitting) return
    if (!this.data.name || !this.data.phone) {
      this.setData({ error: '请填写联系人和手机号' })
      return
    }
    this.setData({ submitting: true, error: '' })
    try {
      await getApp().ensureLogin()
      const order = await api.appoint(getApp().globalData.storeCode, this.data.orderId, {
        starts_at: `${this.data.day}T${this.data.time}:00+08:00`,
        contact_name: this.data.name,
        contact_phone: this.data.phone,
        note: this.data.note
      })
      this.setData({ done: true, order })
    } catch (error) {
      this.setData({ error: error.message || '预约失败' })
    } finally {
      this.setData({ submitting: false })
    }
  },
  goVoucher() {
    wx.redirectTo({ url: `/pages/voucher/index?orderId=${this.data.orderId}` })
  }
})
