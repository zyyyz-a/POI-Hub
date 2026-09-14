const api = require('../../common/api')
const util = require('../../common/util')

const FILTERS = [
  { key: 'all', label: '全部' },
  { key: 'pending', label: '待付款', match: order => order.status === 'payment_pending' },
  { key: 'usable', label: '待使用', match: order => ['paid', 'partially_refunded'].includes(order.status) },
  { key: 'done', label: '已完成/退款', match: order => ['refunded', 'expired', 'closed'].includes(order.status) }
]

Page({
  data: {
    state: 'loading',
    message: '',
    filter: 'all',
    filters: FILTERS.map(item => ({ key: item.key, label: item.label })),
    orders: [],
    visible: []
  },
  onShow() {
    this.load()
  },
  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh())
  },
  async load() {
    const storeCode = getApp().globalData.storeCode
    if (!storeCode) {
      this.setData({ state: 'empty', orders: [], visible: [] })
      return
    }
    this.setData({ state: 'loading', message: '' })
    try {
      await getApp().ensureLogin()
      const orders = (await api.orders(storeCode)).map(util.decorateOrder)
      this.setData({ orders, state: orders.length ? 'content' : 'empty' })
      this.applyFilter(this.data.filter, orders)
    } catch (error) {
      this.setData({ state: 'error', message: error.message })
    }
  },
  setFilter(event) {
    this.applyFilter(event.currentTarget.dataset.key, this.data.orders)
  },
  applyFilter(key, orders) {
    const filter = FILTERS.find(item => item.key === key)
    const visible = filter && filter.match ? orders.filter(filter.match) : orders
    this.setData({ filter: key, visible })
  },
  openDetail(event) {
    wx.navigateTo({ url: `/pages/order-detail/index?orderId=${event.currentTarget.dataset.id}` })
  },
  openVoucher(event) {
    wx.navigateTo({ url: `/pages/voucher/index?orderId=${event.currentTarget.dataset.id}` })
  }
})
