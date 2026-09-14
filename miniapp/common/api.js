let config
try {
  config = require('../config')
} catch (error) {
  config = require('../config.example')
}

function request(path, options = {}) {
  return new Promise((resolve, reject) => {
    const app = getApp && getApp()
    const token = app && app.globalData ? app.globalData.accessToken : ''
    wx.request({
      url: `${config.apiBaseUrl}${path}`,
      method: options.method || 'GET',
      data: options.data,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: response => {
        if (response.statusCode >= 200 && response.statusCode < 300) {
          resolve(response.data)
          return
        }
        const body = response.data || {}
        const detail = body.detail || {}
        const message = detail.message || body.message || '请求失败，请稍后重试'
        const error = new Error(message)
        error.status = response.statusCode
        error.code = detail.code || body.code
        reject(error)
      },
      fail: error => {
        const wrapped = new Error('网络异常，请检查网络后重试')
        wrapped.cause = error
        reject(wrapped)
      }
    })
  })
}

function root(storeCode) {
  return `/public/platform/stores/${storeCode}`
}

module.exports = {
  apiBaseUrl: config.apiBaseUrl,
  customerServicePhone: config.customerServicePhone || '',
  login: (code, storeCode) => request(`${root(storeCode)}/login`, { method: 'POST', data: { code } }),
  store: storeCode => request(root(storeCode)),
  products: storeCode => request(`${root(storeCode)}/products`),
  product: (storeCode, productId) => request(`${root(storeCode)}/products/${productId}`),
  orders: storeCode => request(`${root(storeCode)}/orders`),
  createOrder: (storeCode, data) => request(`${root(storeCode)}/orders`, { method: 'POST', data }),
  getOrder: (storeCode, orderId) => request(`${root(storeCode)}/orders/${orderId}`),
  pay: (storeCode, orderId, data) => request(`${root(storeCode)}/orders/${orderId}/pay`, { method: 'POST', data: data || {} }),
  voucher: (storeCode, orderId) => request(`${root(storeCode)}/orders/${orderId}/voucher`),
  appoint: (storeCode, orderId, data) => request(`${root(storeCode)}/orders/${orderId}/appointment`, { method: 'POST', data }),
  refund: (storeCode, orderId, data) => request(`${root(storeCode)}/orders/${orderId}/refund`, { method: 'POST', data })
}
