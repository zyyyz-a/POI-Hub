const STATUS_TEXT = {
  payment_pending: '待付款',
  paid: '待使用',
  partially_refunded: '部分退款',
  refunded: '已退款',
  expired: '已关闭',
  closed: '已关闭',
  requested: '退款申请中',
  pending: '退款处理中',
  processing: '退款处理中',
  success: '退款成功',
  failed: '退款失败',
  available: '待使用',
  consumed: '已核销',
  cancelled: '已取消'
}

function money(cents) {
  const value = Number(cents || 0) / 100
  return `¥${value.toFixed(2)}`
}

function moneyParts(cents) {
  const value = (Number(cents || 0) / 100).toFixed(2)
  const [yuan, fraction] = value.split('.')
  return { yuan, fraction }
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

function formatDateTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const hh = `${date.getHours()}`.padStart(2, '0')
  const mm = `${date.getMinutes()}`.padStart(2, '0')
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hh}:${mm}`
}

function statusText(value) {
  return STATUS_TEXT[value] || value || ''
}

function statusTone(value) {
  if (value === 'available' || value === 'paid') return 'success'
  if (value === 'consumed' || value === 'refunded' || value === 'expired' || value === 'closed') return 'muted'
  if (value === 'requested' || value === 'pending' || value === 'processing' || value === 'partially_refunded') return 'warning'
  if (value === 'failed') return 'danger'
  return 'default'
}

function newIdempotencyKey(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function toastError(error) {
  const message = (error && (error.message || error.errMsg)) || '操作失败，请稍后重试'
  wx.showToast({ title: message, icon: 'none' })
}

function decorateProduct(product) {
  return Object.assign({}, product, {
    price_text: money(product.sale_price),
    market_text: money(product.market_price),
    stock_text: product.stock > 0 ? `剩余 ${product.stock} 份` : '已售罄'
  })
}

function decorateOrder(order) {
  return Object.assign({}, order, {
    total_text: money(order.paid_amount || order.total_amount),
    status_text: statusText(order.status),
    status_tone: statusTone(order.status),
    created_text: formatDateTime(order.created_at),
    can_pay: order.status === 'payment_pending',
    can_use: ['paid', 'partially_refunded'].includes(order.status)
  })
}

function decorateVoucher(voucher) {
  return Object.assign({}, voucher, {
    valid_text: formatDateTime(voucher.valid_until),
    state_text: statusText(voucher.state),
    state_tone: statusTone(voucher.state)
  })
}

module.exports = {
  money,
  moneyParts,
  formatDate,
  formatDateTime,
  statusText,
  statusTone,
  newIdempotencyKey,
  toastError,
  decorateProduct,
  decorateOrder,
  decorateVoucher
}

